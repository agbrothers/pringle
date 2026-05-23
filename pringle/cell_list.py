"""
CellListWidget — scrollable list of CellWidget instances.

Manages:
- Ordered list of cells (visual order)
- Shared namespace built via DAG-ordered evaluation
- Topological re-evaluation on content_changed / value_changed signals
- Signaling the viewport to update rendered objects

The viewport is updated by calling an injected callback:
    on_cell_result(cell_id, result, style)

Phase 7: evaluation order follows the dependency graph (DAG) rather than
visual order; cycle detection and undefined-name warnings are surfaced inline.
Slider changes trigger incremental re-evaluation of only their downstream cells.
"""

from __future__ import annotations

import time
import warnings
from collections import deque
from dataclasses import dataclass
from typing import Callable
import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QPushButton,
    QFrame, QSizePolicy, QLabel, QApplication,
)
from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal, pyqtSlot

from pringle.cell_widget import CellWidget
from pringle.slider_widget import SliderWidget
from pringle.style import CellStyle, palette_color
from pringle.grid import Grid, make_grid, GridConfig
from pringle.evaluator import run_cell, CellResult, _detect_shape
from pringle.preprocess import is_slider_cell

_MAX_UNDO = 50
_SLOW_EVAL_MS = 100


# ---------------------------------------------------------------------------
# Off-thread evaluation helpers (PERF-015)
# ---------------------------------------------------------------------------

@dataclass
class _CellSpec:
    """Snapshot of one cell's mutable state; safe to pass to the eval thread."""
    cell_id: str
    source: str
    style: CellStyle
    constraint_exprs: list[str]
    condition_exprs: list[str]
    recurrence_expr: str | None
    initial_condition_exprs: list[str]
    is_visible: bool


@dataclass
class _CellWorkerResult:
    """Computation output from the eval thread; applied on the main thread."""
    cell_id: str
    result: CellResult
    style: CellStyle
    error: str | None
    warning: str | None
    preview: str | None
    shape_preview: str | None
    should_be_data: bool
    is_vector: bool
    is_visible: bool


def _eval_spec(spec: _CellSpec, shared: dict, grid: Grid) -> _CellWorkerResult:
    """Evaluate one cell from a snapshot. Thread-safe; no Qt widget access."""
    if not spec.source.strip():
        return _CellWorkerResult(
            cell_id=spec.cell_id, result=CellResult(), style=spec.style,
            error=None, warning=None, preview=None, shape_preview=None,
            should_be_data=False, is_vector=False, is_visible=spec.is_visible,
        )
    try:
        result = run_cell(
            spec.source, shared, grid,
            constraint_exprs=spec.constraint_exprs,
            condition_exprs=spec.condition_exprs,
        )
    except Exception as exc:
        result = CellResult()
        result.error = f"{type(exc).__name__}: {exc}"

    if spec.recurrence_expr and not result.error:
        from pringle.recurrence import parse_recurrence, execute_recurrence
        from pringle.namespace import build_equation_namespace
        is_valid, arr_name, _ = parse_recurrence(spec.recurrence_expr)
        if is_valid and arr_name in result.exports:
            arr = result.exports[arr_name]
            if isinstance(arr, np.ndarray):
                arr, warn = execute_recurrence(
                    arr_name, arr, spec.initial_condition_exprs, spec.recurrence_expr,
                    {**build_equation_namespace(), **shared, **result.exports},
                )
                result.exports[arr_name] = arr
                rt, data = _detect_shape(arr)
                if rt is not None:
                    with warnings.catch_warnings(record=True) as _w:
                        warnings.simplefilter("always")
                        result.data = data.astype(np.float32)
                    result.render_type = rt
                    if _w:
                        result.warning = "Overflow: values exceed float32 range — integration may have diverged"
                    elif warn:
                        result.warning = warn
                else:
                    result.render_type = None
                    result.data = None
                    if warn:
                        result.warning = warn
            else:
                result.error = f"Recurrence: '{arr_name}' is not an array"
                result.render_type = None
                result.data = None
        elif not is_valid:
            result.error = f"Cannot parse recursion rule: {spec.recurrence_expr!r}"
            result.render_type = None
            result.data = None

    should_be_data = (
        result.from_shape_inference
        and result.render_type in ("scatter", "scatter_2d")
    )
    is_vector = result.render_type in ("vectors", "vectors_2d")
    return _CellWorkerResult(
        cell_id=spec.cell_id,
        result=result,
        style=spec.style,
        error=result.error,
        warning=result.warning,
        preview=result.preview,
        shape_preview=result.shape_preview,
        should_be_data=should_be_data,
        is_vector=is_vector,
        is_visible=spec.is_visible,
    )


class _EvalWorker(QObject):
    """Runs cell evaluation on a background QThread."""

    results_ready = pyqtSignal(dict, list, int)  # (new_shared, [_CellWorkerResult], generation)

    @pyqtSlot(object)
    def run_eval(self, work: tuple) -> None:
        generation, shared, grid, specs = work
        worker_results: list[_CellWorkerResult] = []
        for spec in specs:
            wr = _eval_spec(spec, shared, grid)
            shared.update(wr.result.exports)
            worker_results.append(wr)
        self.results_ready.emit(shared, worker_results, generation)


def _ns_value(v: float) -> int | float:
    """Return v as int when it is a whole number, so e.g. zeros(k) works."""
    return int(v) if v == int(v) else v


def _make_resolver(shared_ns: dict):
    """Create a scalar-only namespace resolver for expression bounds (FEAT-045).

    Merges equation-namespace scalar constants (pi, e, inf, nan) with slider
    values from shared_ns; shared_ns takes precedence on name collisions.
    """
    safe_ns = {**_EQ_SCALARS, **{k: v for k, v in shared_ns.items()
               if isinstance(v, (int, float, np.floating, np.integer))}}
    def resolve(expr: str):
        try:
            result = eval(expr, {"__builtins__": {}}, safe_ns)
            if isinstance(result, (int, float, np.floating, np.integer)):
                return float(result)
        except Exception:
            pass
        return None
    return resolve


def _build_eq_scalars() -> dict:
    from pringle.namespace import build_equation_namespace
    return {k: v for k, v in build_equation_namespace().items()
            if isinstance(v, (int, float, np.floating, np.integer))}


_EQ_SCALARS: dict = _build_eq_scalars()


class CellListWidget(QWidget):
    """
    Scrollable ordered list of CellWidget objects.

    Parameters
    ----------
    on_cell_result : callable(cell_id, result, style) invoked after each
                     successful re-evaluation.  The viewport connects here.
    grid : the spatial grid used for all evaluations.
    """

    # Dispatches a (generation, shared, grid, specs) work package to the eval worker.
    eval_requested = pyqtSignal(object)
    # Emitted after _rebuild_namespace completes and slider bounds are re-resolved.
    namespace_rebuilt = pyqtSignal()

    def __init__(
        self,
        on_cell_result: Callable[[str, CellResult, CellStyle], None],
        grid: Grid | None = None,
        on_cell_deleted: Callable[[str], None] | None = None,
        parent=None,
        eval_threaded: bool = False,
    ):
        super().__init__(parent)
        self._on_cell_result = on_cell_result
        self._on_cell_deleted = on_cell_deleted
        self._grid = grid or make_grid()
        self._cells: list[CellWidget] = []
        self._shared_ns: dict = {}
        self._cell_index: int = 0  # for palette cycling
        self._undo_history: deque[list[dict]] = deque(maxlen=_MAX_UNDO)
        self._redo_history: deque[list[dict]] = deque(maxlen=_MAX_UNDO)
        self._in_undo_restore: bool = False
        self.last_eval_ms: float = 0.0
        self._drag_cell_id: str | None = None
        self._drag_target_idx: int = 0

        # Folder membership: cell_id → folder_id (None = top level)
        self._cell_folder: dict[str, str | None] = {}
        # Per-folder state (keyed by folder cell_id)
        self._folder_collapsed: dict[str, bool] = {}
        self._folder_visible: dict[str, bool] = {}
        # Suppress position-based folder inference during bulk restores
        self._skip_folder_inference: bool = False
        # Suppress intermediate namespace rebuilds during bulk restores
        self._skip_rebuild: bool = False

        # Off-thread evaluation (PERF-015): slider animation eval runs on a
        # background QThread so camera events are never blocked by numpy work.
        # eval_threaded=False runs the eval inline (used in tests to avoid thread
        # lifecycle complexity under Python's incremental GC).
        self._eval_threaded: bool = eval_threaded
        self._eval_generation: int = 0
        self._eval_busy: bool = False
        self._pending_eval: tuple[str, float] | None = None

        # DAG cache (PERF-001): keyed on {cell_id: source} for all evaluable cells.
        # Rebuilt only when source text changes; reused across all animation ticks.
        self._dag_cache: object = None  # nx.DiGraph | None
        self._dag_source_key: dict[str, str] = {}

        if eval_threaded:
            self._eval_worker = _EvalWorker()
            self._eval_thread = QThread()
            self._eval_worker.moveToThread(self._eval_thread)
            self.eval_requested.connect(
                self._eval_worker.run_eval,
                Qt.ConnectionType.QueuedConnection,
            )
            self._eval_worker.results_ready.connect(self._on_eval_results)
            self._eval_thread.start()
        else:
            self._eval_worker = None
            self._eval_thread = None

        self._build_ui()

    def shutdown(self) -> None:
        """Stop the eval thread gracefully. Must be called before Qt destroys widgets."""
        if self._eval_thread and self._eval_thread.isRunning():
            self._eval_thread.quit()
            self._eval_thread.wait(3000)

    def _get_dag(self, evaluable: list):
        """Return a cached DAG, rebuilding only when any cell source has changed."""
        from pringle.dag import build_dag
        key = {c.cell_id: c.source() for c in evaluable}
        if key != self._dag_source_key or self._dag_cache is None:
            self._dag_cache = build_dag(evaluable)
            self._dag_source_key = key
        return self._dag_cache

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: #171717; border: none; }")
        outer.addWidget(scroll)

        self._container = QWidget()
        self._container.setStyleSheet("background-color: #171717;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(0)

        # Empty-state placeholder
        self._placeholder = QLabel("Press + to add an expression")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            "color: #aaa; font-size: 13px; padding: 24px;"
        )
        self._layout.addWidget(self._placeholder)
        self._layout.addStretch(1)  # push cells to top
        scroll.setWidget(self._container)

        # Drop indicator: absolutely positioned 2-px accent line (not in layout)
        from PyQt6.QtWidgets import QFrame as _QFrame
        self._drop_indicator = _QFrame(self._container)
        self._drop_indicator.setFixedHeight(2)
        self._drop_indicator.setStyleSheet("background-color: #4a9eff; border: none;")
        self._drop_indicator.hide()

        # Add buttons: equation cell (left) and data cell (right)
        _btn_style = (
            "QPushButton { color: #555; padding: 8px; font-size: 13px; background: transparent; }"
            "QPushButton:hover { color: #ccc; }"
        )
        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_row.setSpacing(0)

        self._add_eq_btn = QPushButton("+ Equation")
        self._add_eq_btn.setFlat(True)
        self._add_eq_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_eq_btn.setStyleSheet(_btn_style)
        self._add_eq_btn.clicked.connect(lambda: self.add_cell(after_id=self._focused_cell_id()))
        add_row.addWidget(self._add_eq_btn)

        self._add_folder_btn = QPushButton("+ Folder")
        self._add_folder_btn.setFlat(True)
        self._add_folder_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._add_folder_btn.setStyleSheet(_btn_style)
        self._add_folder_btn.clicked.connect(lambda: self.add_folder(after_id=self._focused_cell_id()))
        add_row.addWidget(self._add_folder_btn)

        outer.addLayout(add_row)

    # ------------------------------------------------------------------
    # Folder helpers
    # ------------------------------------------------------------------

    def _folder_members(self, folder_id: str) -> list:
        """Return all member cells of folder_id in visual order."""
        return [c for c in self._cells if self._cell_folder.get(c.cell_id) == folder_id]

    def _infer_folder(self, insert_idx: int) -> str | None:
        """Infer folder membership from the cell immediately above insert_idx."""
        from pringle.folder_cell_widget import FolderCellWidget
        if insert_idx <= 0 or not self._cells:
            return None
        prev = self._cells[insert_idx - 1]
        if isinstance(prev, FolderCellWidget):
            return prev.cell_id
        return self._cell_folder.get(prev.cell_id)

    def _assign_folder(self, cell, folder_id: str | None) -> None:
        """Set a cell's folder membership and apply visual effects."""
        from pringle.folder_cell_widget import FolderCellWidget
        if isinstance(cell, FolderCellWidget):
            return  # folders cannot be nested
        self._cell_folder[cell.cell_id] = folder_id
        self._apply_indent(cell, folder_id is not None)
        if folder_id and self._folder_collapsed.get(folder_id, False):
            cell.setVisible(False)
        else:
            cell.setVisible(True)

    def _apply_indent(self, cell, indented: bool) -> None:
        m = cell.contentsMargins()
        left = 16 if indented else 0
        cell.setContentsMargins(left, m.top(), m.right(), m.bottom())

    def _is_render_visible(self, cell) -> bool:
        """True iff the cell should appear in the 3-D viewport."""
        if not cell.is_visible_cell():
            return False
        folder_id = self._cell_folder.get(cell.cell_id)
        if folder_id is not None and not self._folder_visible.get(folder_id, True):
            return False
        return True

    # ------------------------------------------------------------------
    # Cell management
    # ------------------------------------------------------------------

    def add_cell(
        self,
        source: str = "",
        after_id: str | None = None,
        style: CellStyle | None = None,
    ) -> CellWidget | SliderWidget:
        """Add a new cell, optionally after a given cell_id."""
        self._push_undo()
        if style is None:
            style = CellStyle(color=palette_color(self._cell_index))
        self._cell_index += 1

        is_sl, sl_name, sl_val = is_slider_cell(source) if source else (False, "", 0.0)

        if is_sl:
            cell: CellWidget | SliderWidget = SliderWidget(
                name=sl_name, value=sl_val, style=style
            )
            cell.value_changed.connect(self._on_slider_value_changed)
            cell.name_changed.connect(self._on_slider_name_changed)
            cell.enter_pressed.connect(self._on_enter_pressed)
            cell.set_name_validator(self._make_name_validator(cell))
            cell.delete_requested.connect(self._on_delete_requested)
            cell.set_resolver(_make_resolver(self._shared_ns))
        else:
            cell = CellWidget(style=style)
            cell.content_changed.connect(self._on_cell_changed)
            cell.commit_requested.connect(self._maybe_morph_to_slider)
            cell.visibility_toggled.connect(self._on_equation_cell_visibility_toggled)
            cell.style_updated.connect(self._on_equation_cell_style_updated)
            cell.delete_requested.connect(self._on_delete_requested)
            cell.enter_pressed.connect(self._on_enter_pressed)
            cell.new_folder_requested.connect(self._on_new_folder_requested)
            cell.run_requested.connect(self._on_run_requested)

        cell.drag_started.connect(self._on_drag_started)
        cell.drag_moved.connect(self._on_drag_moved)
        cell.drag_ended.connect(self._on_drag_ended)

        if after_id is not None:
            idx = self._index_of(after_id)
            if idx >= 0:
                self._cells.insert(idx + 1, cell)
                self._layout.insertWidget(idx + 2, cell)
                if not self._skip_folder_inference:
                    self._assign_folder(cell, self._infer_folder(idx + 1))
                if source and not is_sl:
                    cell.set_source(source)
                if not self._skip_rebuild:
                    cell.focus()
                if source and not self._skip_rebuild:
                    self._rebuild_namespace()
                self._update_placeholder()
                return cell

        # Append before the stretch
        stretch_pos = self._layout.count() - 1
        self._layout.insertWidget(stretch_pos, cell)
        self._cells.append(cell)
        if not self._skip_folder_inference:
            self._assign_folder(cell, self._infer_folder(len(self._cells) - 1))

        if source and not is_sl:
            cell.set_source(source)
        if not self._skip_rebuild:
            cell.focus()
        if source and not self._skip_rebuild:
            self._rebuild_namespace()
        self._update_placeholder()
        return cell

    def add_comment_cell(
        self,
        source: str = "#",
        after_id: str | None = None,
        style: CellStyle | None = None,
    ):
        """Add a comment/annotation cell (not evaluated)."""
        from pringle.comment_cell_widget import CommentCellWidget
        self._push_undo()
        if style is None:
            style = CellStyle()

        cell = CommentCellWidget(source=source, style=style)
        cell.delete_requested.connect(self._on_delete_requested)
        cell.content_changed.connect(self._on_comment_changed)
        cell.enter_pressed.connect(self._on_enter_pressed)
        cell.new_folder_requested.connect(self._on_new_folder_requested)
        cell.drag_started.connect(self._on_drag_started)
        cell.drag_moved.connect(self._on_drag_moved)
        cell.drag_ended.connect(self._on_drag_ended)

        if after_id is not None:
            idx = self._index_of(after_id)
            if idx >= 0:
                self._cells.insert(idx + 1, cell)
                self._layout.insertWidget(idx + 2, cell)
                if not self._skip_folder_inference:
                    self._assign_folder(cell, self._infer_folder(idx + 1))
                if not self._skip_rebuild:
                    cell.focus()
                self._update_placeholder()
                return cell

        stretch_pos = self._layout.count() - 1
        self._layout.insertWidget(stretch_pos, cell)
        self._cells.append(cell)
        if not self._skip_folder_inference:
            self._assign_folder(cell, self._infer_folder(len(self._cells) - 1))
        if not self._skip_rebuild:
            cell.focus()
        self._update_placeholder()
        return cell

    def add_folder(
        self,
        name: str = "Group",
        after_id: str | None = None,
        style: CellStyle | None = None,
    ):
        """Add a collapsible folder/group header cell."""
        from pringle.folder_cell_widget import FolderCellWidget
        self._push_undo()
        if style is None:
            style = CellStyle(color=(0.55, 0.55, 0.55, 1.0))
        folder = FolderCellWidget(name=name, style=style)
        folder.delete_requested.connect(self._on_delete_requested)
        folder.content_changed.connect(self._on_cell_changed)
        folder.drag_started.connect(self._on_drag_started)
        folder.drag_moved.connect(self._on_drag_moved)
        folder.drag_ended.connect(self._on_drag_ended)
        folder.collapse_changed.connect(self._on_folder_collapse_changed)
        folder.folder_visibility_changed.connect(self._on_folder_visibility_changed)
        self._folder_visible[folder.cell_id] = True

        if after_id is not None:
            idx = self._index_of(after_id)
            if idx >= 0:
                self._cells.insert(idx + 1, folder)
                self._layout.insertWidget(idx + 2, folder)
                self._update_placeholder()
                return folder

        stretch_pos = self._layout.count() - 1
        self._layout.insertWidget(stretch_pos, folder)
        self._cells.append(folder)
        self._update_placeholder()
        return folder

    def remove_cell(self, cell_id: str) -> None:
        from pringle.folder_cell_widget import FolderCellWidget
        idx = self._index_of(cell_id)
        if idx < 0:
            return
        self._push_undo()
        cell = self._cells[idx]
        if isinstance(cell, FolderCellWidget):
            # Detach members: make them visible and top-level before removing folder
            for member in self._folder_members(cell_id):
                self._cell_folder.pop(member.cell_id, None)
                self._apply_indent(member, False)
                member.setVisible(True)
            self._folder_collapsed.pop(cell_id, None)
            self._folder_visible.pop(cell_id, None)
        else:
            self._cell_folder.pop(cell_id, None)
        self._cells.pop(idx)
        self._layout.removeWidget(cell)
        cell.deleteLater()
        # Focus the cell above (or below if first)
        if self._cells:
            target_idx = max(0, idx - 1)
            self._cells[target_idx].focus()
        # Remove from viewport and forget the cell so the next render for
        # that id (if a new cell is later added) correctly re-fits the camera
        self._on_cell_result(cell_id, CellResult(), cell.style)
        if self._on_cell_deleted is not None:
            self._on_cell_deleted(cell_id)
        self._rebuild_namespace()
        self._update_placeholder()

    def cell_sources(self) -> list[tuple[str, str]]:
        """Return (cell_id, source) pairs in visual order."""
        return [(c.cell_id, c.source()) for c in self._cells]

    def update_grid(self, grid: Grid) -> None:
        self._grid = grid
        self._rebuild_namespace()

    # ------------------------------------------------------------------
    # Undo / redo (structural: add / remove cell)
    # ------------------------------------------------------------------

    def _push_undo(self) -> None:
        if self._in_undo_restore:
            return
        from pringle.session import cell_to_dict
        snapshot = [cell_to_dict(c, self._cell_folder.get(c.cell_id)) for c in self._cells]
        self._undo_history.append(snapshot)
        self._redo_history.clear()

    def undo(self) -> None:
        if not self._undo_history:
            return
        from pringle.session import cell_to_dict, restore_cell_list
        self._redo_history.append(
            [cell_to_dict(c, self._cell_folder.get(c.cell_id)) for c in self._cells]
        )
        state = self._undo_history.pop()
        self._in_undo_restore = True
        restore_cell_list(self, state)
        self._in_undo_restore = False

    def redo(self) -> None:
        if not self._redo_history:
            return
        from pringle.session import cell_to_dict, restore_cell_list
        self._undo_history.append(
            [cell_to_dict(c, self._cell_folder.get(c.cell_id)) for c in self._cells]
        )
        state = self._redo_history.pop()
        self._in_undo_restore = True
        restore_cell_list(self, state)
        self._in_undo_restore = False

    # ------------------------------------------------------------------
    # Copy / paste
    # ------------------------------------------------------------------

    def _focused_cell_id(self) -> str | None:
        """Return the cell_id of the cell that currently contains keyboard focus, or None."""
        cell_map = {id(c): c.cell_id for c in self._cells}
        w = QApplication.focusWidget()
        while w is not None:
            cid = cell_map.get(id(w))
            if cid is not None:
                return cid
            w = w.parent() if hasattr(w, "parent") else None
        return None

    def copy_focused_cell(self) -> bool:
        """Copy the source of the currently focused cell to the clipboard.
        Returns True if a cell was found and copied."""
        from PyQt6.QtWidgets import QPlainTextEdit
        fw = QApplication.focusWidget()
        # Walk up to find a CellWidget
        w = fw
        while w is not None:
            if isinstance(w, CellWidget):
                QApplication.clipboard().setText(w.source())
                return True
            w = w.parent() if hasattr(w, "parent") else None
        return False

    def paste_cell(self) -> None:
        """Add a new cell with the clipboard text as source."""
        text = QApplication.clipboard().text().strip()
        if text:
            self.add_cell(text)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_placeholder(self) -> None:
        self._placeholder.setVisible(len(self._cells) == 0)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _rebuild_namespace(self) -> None:
        """
        Re-evaluate all cells in dependency (topological) order.

        Cycle detection: cyclic cells are flagged with an error and skipped.
        Undefined-name detection: cells using names not defined by any cell
        receive an inline warning.
        """
        # Invalidate any in-flight or pending worker result so it doesn't
        # overwrite the namespace we're about to build synchronously.
        self._eval_generation += 1
        self._pending_eval = None

        from pringle.dag import topo_order, undefined_names
        from pringle.folder_cell_widget import FolderCellWidget
        from pringle.comment_cell_widget import CommentCellWidget

        t0 = time.monotonic()
        evaluable = [
            c for c in self._cells
            if not isinstance(c, (FolderCellWidget, CommentCellWidget))
        ]

        dag = self._get_dag(evaluable)
        ordered_cells, cyclic_ids = topo_order(dag, evaluable)
        undef = undefined_names(evaluable)

        shared: dict = {}
        for cell in ordered_cells:
            if isinstance(cell, SliderWidget):
                shared[cell.name] = _ns_value(cell.value)
                continue

            if cell.cell_id in cyclic_ids:
                cell.clear_diagnostics()
                cell.set_error("Circular dependency detected")
                self._on_cell_result(cell.cell_id, CellResult(), cell.style)
                continue

            # Per-cell RNG: inject a fresh RandomState seeded by _rng_seed so draws
            # are reproducible on every rebuild without mutating global np.random state.
            shared["random"] = np.random.RandomState(getattr(cell, "_rng_seed", 0))

            result = self._eval_cell(cell, shared)
            cell._last_result = result

            # Augment with undefined-name warning if eval succeeded
            if not result.error and cell.cell_id in undef:
                names_str = ", ".join(f"'{n}'" for n in undef[cell.cell_id])
                extra = f"Undefined: {names_str}"
                if not result.warning:
                    cell.set_warning(extra)

            shared.update(result.exports)
            if self._is_render_visible(cell):
                self._on_cell_result(cell.cell_id, result, cell.style)
            else:
                self._on_cell_result(cell.cell_id, CellResult(), cell.style)

        shared.pop("random", None)
        self._shared_ns = shared
        self.last_eval_ms = (time.monotonic() - t0) * 1000

        _resolver = _make_resolver(self._shared_ns)
        for cell in self._cells:
            if isinstance(cell, SliderWidget):
                cell.set_resolver(_resolver)   # keep resolver current for future user edits
                cell.re_resolve(_resolver)     # re-evaluate any stored expressions
        self.namespace_rebuilt.emit()

    def _eval_cell(self, cell: CellWidget, shared: dict) -> CellResult:
        """Evaluate one cell against the current shared namespace + grid."""
        cell.clear_diagnostics()
        source = cell.source()
        if not source.strip():
            return CellResult()
        c_exprs = cell.constraint_exprs()
        d_exprs = cell.condition_exprs()
        try:
            result = run_cell(
                source, shared, self._grid,
                constraint_exprs=c_exprs, condition_exprs=d_exprs,
            )
        except Exception as exc:
            result = CellResult()
            result.error = f"{type(exc).__name__}: {exc}"

        # Apply recursion/initial_condition sub-cells if present
        rule_expr = cell.recurrence_expr()
        if rule_expr and not result.error:
            from pringle.recurrence import parse_recurrence, execute_recurrence
            initial_exprs = cell.initial_condition_exprs()
            is_valid, arr_name, _ = parse_recurrence(rule_expr)
            if is_valid and arr_name in result.exports:
                arr = result.exports[arr_name]
                if isinstance(arr, np.ndarray):
                    from pringle.namespace import build_equation_namespace
                    arr, warn = execute_recurrence(
                        arr_name, arr, initial_exprs, rule_expr,
                        {**build_equation_namespace(), **shared, **result.exports},
                    )
                    result.exports[arr_name] = arr
                    rt, data = _detect_shape(arr)
                    if rt is not None:
                        with warnings.catch_warnings(record=True) as _w:
                            warnings.simplefilter("always")
                            result.data = data.astype(np.float32)
                        result.render_type = rt
                        if _w:
                            result.warning = "Overflow: values exceed float32 range — integration may have diverged"
                        elif warn:
                            result.warning = warn
                    else:
                        result.render_type = None
                        result.data = None
                        if warn:
                            result.warning = warn
                else:
                    result.error = f"Recurrence: '{arr_name}' is not an array"
                    result.render_type = None
                    result.data = None
            elif not is_valid:
                result.error = f"Cannot parse recursion rule: {rule_expr!r}"
                result.render_type = None
                result.data = None

        if result.error:
            cell.set_error(result.error)
        elif result.warning:
            cell.set_warning(result.warning)
        cell.set_preview(result.preview, result.shape_preview)

        # Auto-switch cell between expression mode and data-array mode based on return type.
        # Skip if any recursion sub-cell is present (even empty) — adding the sub-cell is the
        # user's explicit intent to use data mode, so we must not auto-disable it before the
        # rule expression has been filled in.
        if not cell.has_recursion_sub_cell():
            should_be_data = (
                result.from_shape_inference
                and result.render_type in ("scatter", "scatter_2d")
            )
            if should_be_data != cell.is_data_mode():
                cell.set_data_mode(should_be_data)

        is_vector = result.render_type in ("vectors", "vectors_2d")
        if is_vector != cell.is_vector_cell():
            cell.set_vector_cell(is_vector)

        return result

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_run_requested(self, cell_id: str) -> None:
        """Force re-evaluate a data-mode CellWidget (→ button or focus-out)."""
        idx = self._index_of(cell_id)
        if idx >= 0:
            cell = self._cells[idx]
            cell._rng_seed = (cell._rng_seed + 1) % 2**32  # new seed → different draws
        self._rebuild_namespace()

    def _on_equation_cell_visibility_toggled(self, cell_id: str, _is_visible: bool) -> None:
        """Show or clear an equation cell's render when the 👁 is toggled — no re-eval."""
        idx = self._index_of(cell_id)
        if idx < 0:
            return
        cell = self._cells[idx]
        last = getattr(cell, "_last_result", None)
        if self._is_render_visible(cell) and last is not None and last.render_type:
            self._on_cell_result(cell_id, last, cell.style)
        else:
            self._on_cell_result(cell_id, CellResult(), cell.style)

    def _on_equation_cell_style_updated(self, cell_id: str) -> None:
        """Re-apply the cached result when color/opacity/size changes — no re-eval."""
        idx = self._index_of(cell_id)
        if idx < 0:
            return
        cell = self._cells[idx]
        last = getattr(cell, "_last_result", None)
        if last is not None and last.render_type and self._is_render_visible(cell):
            self._on_cell_result(cell_id, last, cell.style)

    def _on_folder_collapse_changed(self, folder_id: str, collapsed: bool) -> None:
        """Hide or show all member cells when a folder is collapsed/expanded."""
        self._folder_collapsed[folder_id] = collapsed
        for member in self._folder_members(folder_id):
            member.setVisible(not collapsed)

    def _on_folder_visibility_changed(self, folder_id: str, visible: bool) -> None:
        """Update renderer visibility for all member cells when folder eye is toggled."""
        self._folder_visible[folder_id] = visible
        for member in self._folder_members(folder_id):
            last = getattr(member, "_last_result", None)
            if self._is_render_visible(member) and last is not None and last.render_type:
                self._on_cell_result(member.cell_id, last, member.style)
            else:
                self._on_cell_result(member.cell_id, CellResult(), member.style)

    def _on_comment_changed(self, cell_id: str) -> None:
        pass  # comment edits don't affect the namespace or any render output

    def _on_cell_changed(self, cell_id: str) -> None:
        self._maybe_morph_to_comment(cell_id)
        self._rebuild_namespace()

    def _maybe_morph_to_comment(self, cell_id: str) -> None:
        """
        If a plain CellWidget source now starts with '#', swap it for a
        CommentCellWidget in-place, preserving cell_id and style.
        """
        from pringle.comment_cell_widget import CommentCellWidget
        idx = self._index_of(cell_id)
        if idx < 0:
            return
        cell = self._cells[idx]
        if not isinstance(cell, CellWidget) or isinstance(cell, SliderWidget):
            return

        if not cell.source().startswith("#"):
            return

        source = cell.source()
        style = cell.style
        comment = CommentCellWidget(source=source, style=style, cell_id=cell_id)
        comment.delete_requested.connect(self._on_delete_requested)
        comment.content_changed.connect(self._on_comment_changed)
        comment.enter_pressed.connect(self._on_enter_pressed)
        comment.new_folder_requested.connect(self._on_new_folder_requested)
        comment.drag_started.connect(self._on_drag_started)
        comment.drag_moved.connect(self._on_drag_moved)
        comment.drag_ended.connect(self._on_drag_ended)

        self._layout.replaceWidget(cell, comment)
        self._cells[idx] = comment
        cell.deleteLater()
        comment.focus()

    def _maybe_morph_to_slider(self, cell_id: str) -> None:
        """
        If a plain CellWidget now contains a bare scalar assignment (e.g. `a = 1`),
        swap it for a SliderWidget in-place, preserving cell_id and style.
        """
        idx = self._index_of(cell_id)
        if idx < 0:
            return
        cell = self._cells[idx]
        if not isinstance(cell, CellWidget) or isinstance(cell, SliderWidget):
            return

        is_sl, sl_name, sl_val = is_slider_cell(cell.source())
        if not is_sl:
            return

        style = cell.style
        slider = SliderWidget(
            name=sl_name, value=sl_val, style=style, cell_id=cell_id,
        )
        slider.value_changed.connect(self._on_slider_value_changed)
        slider.name_changed.connect(self._on_slider_name_changed)
        slider.set_name_validator(self._make_name_validator(slider))
        slider.delete_requested.connect(self._on_delete_requested)
        slider.drag_started.connect(self._on_drag_started)
        slider.drag_moved.connect(self._on_drag_moved)
        slider.drag_ended.connect(self._on_drag_ended)
        slider.set_resolver(_make_resolver(self._shared_ns))

        # Swap in the layout and the cells list
        self._layout.replaceWidget(cell, slider)
        self._cells[idx] = slider
        cell.deleteLater()

    def _make_name_validator(self, slider: SliderWidget) -> Callable[[str], bool]:
        """Return a callback that rejects names already used by other sliders."""
        def validate(name: str) -> bool:
            return all(
                c.name != name
                for c in self._cells
                if isinstance(c, SliderWidget) and c is not slider
            )
        return validate

    def _on_slider_name_changed(self, old_name: str, new_name: str, cell_id: str) -> None:
        self._rebuild_namespace()

    def _on_slider_value_changed(self, name: str, value: float) -> None:
        """
        Incremental re-evaluation dispatched to the background eval thread
        so the main thread stays free for camera events during animation.
        Falls back to a full sync rebuild if the namespace is not yet initialised.
        """
        from pringle.folder_cell_widget import FolderCellWidget
        from pringle.comment_cell_widget import CommentCellWidget

        evaluable = [
            c for c in self._cells
            if not isinstance(c, (FolderCellWidget, CommentCellWidget))
        ]

        if not self._shared_ns and evaluable:
            self._rebuild_namespace()
            return

        slider_cell = next(
            (c for c in evaluable if isinstance(c, SliderWidget) and c.name == name),
            None,
        )
        if slider_cell is None:
            self._rebuild_namespace()
            return

        # Record the latest tick; dispatch immediately if the worker is idle.
        self._pending_eval = (name, value)
        if not self._eval_busy:
            self._dispatch_pending_eval()

    def _dispatch_pending_eval(self) -> None:
        """Build a work package from the latest pending tick and hand it to the worker."""
        if self._pending_eval is None:
            return
        name, value = self._pending_eval
        self._pending_eval = None

        from pringle.dag import downstream_of
        from pringle.folder_cell_widget import FolderCellWidget
        from pringle.comment_cell_widget import CommentCellWidget
        import networkx as nx

        evaluable = [
            c for c in self._cells
            if not isinstance(c, (FolderCellWidget, CommentCellWidget))
        ]
        slider_cell = next(
            (c for c in evaluable if isinstance(c, SliderWidget) and c.name == name),
            None,
        )
        if slider_cell is None:
            self._rebuild_namespace()
            return

        dag = self._get_dag(evaluable)
        descendants = downstream_of(dag, slider_cell.cell_id, evaluable)

        visible_ids = {
            c.cell_id for c in descendants
            if not isinstance(c, SliderWidget) and self._is_render_visible(c)
        }
        required_ids = set(visible_ids)
        for vid in visible_ids:
            required_ids.update(nx.ancestors(dag, vid))

        # Snapshot namespace on the main thread; update slider values synchronously.
        shared = dict(self._shared_ns)
        shared[name] = _ns_value(value)
        for cell in descendants:
            if isinstance(cell, SliderWidget):
                shared[cell.name] = _ns_value(cell.value)

        # Snapshot all cell state on the main thread (Qt widget reads are not thread-safe).
        specs: list[_CellSpec] = []
        for cell in descendants:
            if isinstance(cell, SliderWidget) or cell.cell_id not in required_ids:
                continue
            specs.append(_CellSpec(
                cell_id=cell.cell_id,
                source=cell.source(),
                style=cell.style,
                constraint_exprs=cell.constraint_exprs(),
                condition_exprs=cell.condition_exprs(),
                recurrence_expr=cell.recurrence_expr(),
                initial_condition_exprs=cell.initial_condition_exprs(),
                is_visible=self._is_render_visible(cell),
            ))

        if self._eval_threaded:
            self._eval_busy = True
            self.eval_requested.emit((self._eval_generation, shared, self._grid, specs))
        else:
            # Synchronous path (eval_threaded=False): run inline on the main thread.
            gen = self._eval_generation
            worker_results: list[_CellWorkerResult] = []
            for spec in specs:
                wr = _eval_spec(spec, shared, self._grid)
                shared.update(wr.result.exports)
                worker_results.append(wr)
            self._on_eval_results(shared, worker_results, gen)

    def _on_eval_results(self, new_shared: dict, worker_results: list, generation: int) -> None:
        """Receive results from the eval worker (queued signal; runs on main thread)."""
        self._eval_busy = False

        if generation == self._eval_generation:
            self._shared_ns = new_shared
            _resolver = _make_resolver(self._shared_ns)
            for cell in self._cells:
                if isinstance(cell, SliderWidget):
                    cell.re_resolve(_resolver)
            for wr in worker_results:
                idx = self._index_of(wr.cell_id)
                if idx >= 0:
                    cell = self._cells[idx]
                    cell.clear_diagnostics()
                    if wr.error:
                        cell.set_error(wr.error)
                    elif wr.warning:
                        cell.set_warning(wr.warning)
                    cell.set_preview(wr.preview, wr.shape_preview)
                    cell._last_result = wr.result
                    if not cell.has_recursion_sub_cell() and wr.should_be_data != cell.is_data_mode():
                        cell.set_data_mode(wr.should_be_data)
                    if wr.is_vector != cell.is_vector_cell():
                        cell.set_vector_cell(wr.is_vector)
                if wr.is_visible:
                    self._on_cell_result(wr.cell_id, wr.result, wr.style)
                else:
                    self._on_cell_result(wr.cell_id, CellResult(), wr.style)

        # Process any tick that arrived while the worker was busy.
        if self._pending_eval is not None:
            self._dispatch_pending_eval()

    def _on_delete_requested(self, cell_id: str) -> None:
        self.remove_cell(cell_id)

    def _on_enter_pressed(self, cell_id: str) -> None:
        self.add_cell(after_id=cell_id)

    def _on_new_folder_requested(self, cell_id: str) -> None:
        folder = self.add_folder(after_id=cell_id)
        folder.focus()

    # ------------------------------------------------------------------
    # Drag-to-reorder
    # ------------------------------------------------------------------

    def _on_drag_started(self, cell_id: str) -> None:
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        self._drag_cell_id = cell_id
        idx = self._index_of(cell_id)
        if idx < 0:
            return
        self._drag_target_idx = idx
        effect = QGraphicsOpacityEffect()
        effect.setOpacity(0.4)
        self._cells[idx].setGraphicsEffect(effect)
        self._position_drop_indicator(idx)
        self._drop_indicator.show()
        self._drop_indicator.raise_()

    def _on_drag_moved(self, cell_id: str, global_y: int) -> None:
        if self._drag_cell_id != cell_id:
            return
        from PyQt6.QtCore import QPoint
        local_y = self._container.mapFromGlobal(QPoint(0, global_y)).y()
        drop_idx = self._compute_drop_idx(local_y)
        self._drag_target_idx = drop_idx
        self._position_drop_indicator(drop_idx)

    def _on_drag_ended(self, cell_id: str) -> None:
        if self._drag_cell_id != cell_id:
            return
        from_idx = self._index_of(cell_id)
        to_idx = self._drag_target_idx
        self._drag_cell_id = None
        if from_idx >= 0:
            self._cells[from_idx].setGraphicsEffect(None)
        self._drop_indicator.hide()
        if from_idx >= 0:
            self._move_cell(from_idx, to_idx)

    def _compute_drop_idx(self, local_y: int) -> int:
        for i, cell in enumerate(self._cells):
            if not cell.isVisible():
                continue  # skip hidden members of collapsed folders
            geo = cell.geometry()
            if local_y < geo.top() + geo.height() // 4:  # 25% threshold
                return i
        return len(self._cells)

    def _position_drop_indicator(self, drop_idx: int) -> None:
        visible = [c for c in self._cells if c.isVisible()]
        if not visible:
            self._drop_indicator.hide()
            return
        if drop_idx <= 0:
            y = visible[0].geometry().top()
        elif drop_idx >= len(self._cells):
            y = visible[-1].geometry().bottom()
        else:
            # Find the nearest visible cell at or before drop_idx for prev_bottom
            prev = next(
                (self._cells[j] for j in range(drop_idx - 1, -1, -1)
                 if self._cells[j].isVisible()),
                None,
            )
            # Find the nearest visible cell at or after drop_idx for next_top
            nxt = next(
                (self._cells[j] for j in range(drop_idx, len(self._cells))
                 if self._cells[j].isVisible()),
                None,
            )
            if prev and nxt:
                y = (prev.geometry().bottom() + nxt.geometry().top()) // 2
            elif nxt:
                y = nxt.geometry().top()
            else:
                y = visible[-1].geometry().bottom()
        w = self._container.width()
        self._drop_indicator.setGeometry(8, y - 1, w - 16, 2)
        self._drop_indicator.raise_()

    def _move_cell(self, from_idx: int, to_idx: int) -> None:
        from pringle.folder_cell_widget import FolderCellWidget
        cell = self._cells[from_idx]

        if isinstance(cell, FolderCellWidget):
            # Move folder + all its members as a single block
            folder_id = cell.cell_id
            members = [c for c in self._cells
                       if self._cell_folder.get(c.cell_id) == folder_id]
            block = [cell] + members
            block_indices = sorted(
                [self._index_of(b.cell_id) for b in block], reverse=True
            )
            # No-op: drop target is within the block itself
            if to_idx in range(block_indices[-1], block_indices[0] + 2):
                return
            self._push_undo()
            for i in block_indices:
                self._cells.pop(i)
            removed_before = sum(1 for i in block_indices if i < to_idx)
            insert_at = max(0, to_idx - removed_before)
            for j, b in enumerate(block):
                self._cells.insert(insert_at + j, b)
        else:
            # Single-cell move; dropping immediately above/below is a no-op
            if to_idx == from_idx or to_idx == from_idx + 1:
                return
            self._push_undo()
            self._cells.pop(from_idx)
            insert_idx = (to_idx - 1) if to_idx > from_idx else to_idx
            self._cells.insert(insert_idx, cell)
            new_folder = self._infer_folder(self._index_of(cell.cell_id))
            if new_folder != self._cell_folder.get(cell.cell_id):
                self._assign_folder(cell, new_folder)

        # Rebuild layout order without flickering
        self._container.setUpdatesEnabled(False)
        for c in self._cells:
            self._layout.removeWidget(c)
        for i, c in enumerate(self._cells):
            self._layout.insertWidget(i + 1, c)  # +1 skips placeholder at index 0
        self._container.setUpdatesEnabled(True)
        self._rebuild_namespace()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _index_of(self, cell_id: str) -> int:
        for i, c in enumerate(self._cells):
            if c.cell_id == cell_id:
                return i
        return -1
