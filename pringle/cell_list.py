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
from collections import deque
from typing import Callable
import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QPushButton,
    QFrame, QSizePolicy, QLabel, QApplication,
)
from PyQt6.QtCore import Qt

from pringle.cell_widget import CellWidget
from pringle.slider_widget import SliderWidget
from pringle.style import CellStyle, palette_color
from pringle.grid import Grid, make_grid, GridConfig
from pringle.evaluator import run_cell, CellResult
from pringle.preprocess import is_slider_cell

_MAX_UNDO = 50
_SLOW_EVAL_MS = 100


def _ns_value(v: float) -> int | float:
    """Return v as int when it is a whole number, so e.g. zeros(k) works."""
    return int(v) if v == int(v) else v


class CellListWidget(QWidget):
    """
    Scrollable ordered list of CellWidget objects.

    Parameters
    ----------
    on_cell_result : callable(cell_id, result, style) invoked after each
                     successful re-evaluation.  The viewport connects here.
    grid : the spatial grid used for all evaluations.
    """

    def __init__(
        self,
        on_cell_result: Callable[[str, CellResult, CellStyle], None],
        grid: Grid | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._on_cell_result = on_cell_result
        self._grid = grid or make_grid()
        self._cells: list[CellWidget] = []
        self._shared_ns: dict = {}
        self._data_cell_ns: dict = {}  # exports from manually-run data cells
        self._cell_index: int = 0  # for palette cycling
        self._undo_history: deque[list[dict]] = deque(maxlen=_MAX_UNDO)
        self._redo_history: deque[list[dict]] = deque(maxlen=_MAX_UNDO)
        self._in_undo_restore: bool = False
        self.last_eval_ms: float = 0.0
        self._drag_cell_id: str | None = None
        self._drag_target_idx: int = 0

        self._build_ui()

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
        outer.addWidget(scroll)

        self._container = QWidget()
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
            "QPushButton { color: #555; padding: 8px; font-size: 13px; }"
            "QPushButton:hover { color: #222; }"
        )
        add_row = QHBoxLayout()
        add_row.setContentsMargins(0, 0, 0, 0)
        add_row.setSpacing(0)

        self._add_eq_btn = QPushButton("+ Equation")
        self._add_eq_btn.setFlat(True)
        self._add_eq_btn.setStyleSheet(_btn_style)
        self._add_eq_btn.clicked.connect(lambda: self.add_cell())
        add_row.addWidget(self._add_eq_btn)

        self._add_data_btn = QPushButton("+ Data cell")
        self._add_data_btn.setFlat(True)
        self._add_data_btn.setStyleSheet(_btn_style)
        self._add_data_btn.clicked.connect(lambda: self.add_data_cell())
        add_row.addWidget(self._add_data_btn)

        outer.addLayout(add_row)

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
            cell.delete_requested.connect(self._on_delete_requested)
        else:
            cell = CellWidget(style=style)
            cell.content_changed.connect(self._on_cell_changed)
            cell.delete_requested.connect(self._on_delete_requested)
            cell.enter_pressed.connect(self._on_enter_pressed)
            cell.run_requested.connect(self._on_run_requested)

        cell.drag_started.connect(self._on_drag_started)
        cell.drag_moved.connect(self._on_drag_moved)
        cell.drag_ended.connect(self._on_drag_ended)

        if after_id is not None:
            idx = self._index_of(after_id)
            if idx >= 0:
                self._cells.insert(idx + 1, cell)
                self._layout.insertWidget(idx + 1, cell)
                if source and not is_sl:
                    cell.set_source(source)
                cell.focus()
                if source:
                    self._rebuild_namespace()
                self._update_placeholder()
                return cell

        # Append before the stretch
        stretch_pos = self._layout.count() - 1
        self._layout.insertWidget(stretch_pos, cell)
        self._cells.append(cell)

        if source and not is_sl:
            cell.set_source(source)
        cell.focus()
        if source:
            self._rebuild_namespace()
        self._update_placeholder()
        return cell

    def add_data_cell(
        self,
        source: str = "",
        after_id: str | None = None,
        style: CellStyle | None = None,
    ):
        """Add a run-on-demand data cell."""
        from pringle.data_cell_widget import DataCellWidget
        self._push_undo()
        if style is None:
            style = CellStyle(color=palette_color(self._cell_index))
        self._cell_index += 1

        cell = DataCellWidget(style=style)
        cell.run_requested.connect(self._run_data_cell)
        cell.delete_requested.connect(self._on_delete_requested)
        cell.visibility_toggled.connect(self._on_data_cell_visibility_toggled)
        cell.drag_started.connect(self._on_drag_started)
        cell.drag_moved.connect(self._on_drag_moved)
        cell.drag_ended.connect(self._on_drag_ended)

        if after_id is not None:
            idx = self._index_of(after_id)
            if idx >= 0:
                self._cells.insert(idx + 1, cell)
                self._layout.insertWidget(idx + 1, cell)
                if source:
                    cell.set_source(source)
                cell.focus()
                self._update_placeholder()
                return cell

        stretch_pos = self._layout.count() - 1
        self._layout.insertWidget(stretch_pos, cell)
        self._cells.append(cell)
        if source:
            cell.set_source(source)
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

        if after_id is not None:
            idx = self._index_of(after_id)
            if idx >= 0:
                self._cells.insert(idx + 1, folder)
                self._layout.insertWidget(idx + 1, folder)
                self._update_placeholder()
                return folder

        stretch_pos = self._layout.count() - 1
        self._layout.insertWidget(stretch_pos, folder)
        self._cells.append(folder)
        self._update_placeholder()
        return folder

    def remove_cell(self, cell_id: str) -> None:
        idx = self._index_of(cell_id)
        if idx < 0:
            return
        self._push_undo()
        cell = self._cells.pop(idx)
        self._layout.removeWidget(cell)
        cell.deleteLater()
        # Focus the cell above (or below if first)
        if self._cells:
            target_idx = max(0, idx - 1)
            self._cells[target_idx].focus()
        # Remove from viewport
        self._on_cell_result(cell_id, CellResult(), cell.style)
        self._rebuild_namespace()
        self._update_placeholder()

    def cell_sources(self) -> list[tuple[str, str]]:
        """Return (cell_id, source) pairs in visual order."""
        return [(c.cell_id, c.source()) for c in self._cells]

    def update_grid(self, grid: Grid) -> None:
        self._grid = grid
        self._rebuild_namespace()

    def _run_data_cell(self, cell_id: str) -> None:
        """Run a data cell on demand, using the current equation namespace as input."""
        from pringle.data_cell_widget import DataCellWidget
        from pringle.namespace import build_data_namespace
        from pringle.recurrence import parse_recurrence, execute_recurrence

        idx = self._index_of(cell_id)
        if idx < 0:
            return
        cell = self._cells[idx]
        if not isinstance(cell, DataCellWidget):
            return

        source = cell.source().strip()
        if not source:
            cell.set_status("idle")
            return

        # Data namespace + full current shared namespace (sliders + equation exports
        # + previous data cell outputs) so data cells see everything
        ns = build_data_namespace()
        ns.update(self._shared_ns)

        result = run_cell(source, ns, self._grid, is_data_cell=True)

        if result.error:
            cell.set_status("error", result.error)
            return

        rule_expr = cell.recurrence_expr()
        initial_exprs = cell.initial_condition_exprs()

        if rule_expr:
            is_valid, arr_name, _ = parse_recurrence(rule_expr)
            if is_valid and arr_name in result.exports:
                arr = result.exports[arr_name]
                if isinstance(arr, np.ndarray):
                    arr, warn = execute_recurrence(
                        arr_name, arr, initial_exprs, rule_expr,
                        {**ns, **result.exports},
                    )
                    result.exports[arr_name] = arr
                    if warn:
                        cell.set_status("stale", warn)
                    else:
                        cell.set_status("ok")
                    if arr.ndim == 2 and arr.shape[1] in (2, 3):
                        result.render_type = "scatter"
                        result.data = arr.astype(np.float32)
                else:
                    cell.set_status("error", f"'{arr_name}' is not an array")
                    return
            else:
                cell.set_status("error", f"Cannot parse rule or missing array: {rule_expr!r}")
                return
        else:
            cell.set_status("ok", result.warning or "")

        # Merge exports into the persistent data-cell namespace, then rebuild
        self._data_cell_ns.update(result.exports)
        self._rebuild_namespace()

        cell._last_result = result
        if result.render_type:
            if cell.is_visible_cell():
                self._on_cell_result(cell.cell_id, result, cell.style)
            else:
                self._on_cell_result(cell.cell_id, CellResult(), cell.style)

    # ------------------------------------------------------------------
    # Undo / redo (structural: add / remove cell)
    # ------------------------------------------------------------------

    def _push_undo(self) -> None:
        if self._in_undo_restore:
            return
        from pringle.session import cell_to_dict
        snapshot = [cell_to_dict(c) for c in self._cells]
        self._undo_history.append(snapshot)
        self._redo_history.clear()

    def undo(self) -> None:
        if not self._undo_history:
            return
        from pringle.session import cell_to_dict, restore_cell_list
        self._redo_history.append([cell_to_dict(c) for c in self._cells])
        state = self._undo_history.pop()
        self._in_undo_restore = True
        restore_cell_list(self, state)
        self._in_undo_restore = False

    def redo(self) -> None:
        if not self._redo_history:
            return
        from pringle.session import cell_to_dict, restore_cell_list
        self._undo_history.append([cell_to_dict(c) for c in self._cells])
        state = self._redo_history.pop()
        self._in_undo_restore = True
        restore_cell_list(self, state)
        self._in_undo_restore = False

    # ------------------------------------------------------------------
    # Copy / paste
    # ------------------------------------------------------------------

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
        from pringle.dag import build_dag, topo_order, undefined_names
        from pringle.folder_cell_widget import FolderCellWidget

        t0 = time.monotonic()
        evaluable = [c for c in self._cells if not isinstance(c, FolderCellWidget)]

        dag = build_dag(evaluable)
        ordered_cells, cyclic_ids = topo_order(dag, evaluable)
        undef = undefined_names(evaluable)

        from pringle.data_cell_widget import DataCellWidget

        # Seed with previously-run data cell outputs so equation cells can reference them
        shared: dict = dict(self._data_cell_ns)
        for cell in ordered_cells:
            if isinstance(cell, SliderWidget):
                shared[cell.name] = _ns_value(cell.value)
                continue

            # Data cells run on demand only — skip during reactive rebuild
            if isinstance(cell, DataCellWidget):
                cell._mark_stale()
                continue

            if cell.cell_id in cyclic_ids:
                cell.clear_diagnostics()
                cell.set_error("Circular dependency detected")
                self._on_cell_result(cell.cell_id, CellResult(), cell.style)
                continue

            result = self._eval_cell(cell, shared)

            # Augment with undefined-name warning if eval succeeded
            if not result.error and cell.cell_id in undef:
                names_str = ", ".join(f"'{n}'" for n in undef[cell.cell_id])
                extra = f"Undefined: {names_str}"
                if not result.warning:
                    cell.set_warning(extra)

            shared.update(result.exports)
            if cell.is_visible_cell():
                self._on_cell_result(cell.cell_id, result, cell.style)
            else:
                self._on_cell_result(cell.cell_id, CellResult(), cell.style)

        self._shared_ns = shared
        self.last_eval_ms = (time.monotonic() - t0) * 1000

    def _eval_cell(self, cell: CellWidget, shared: dict) -> CellResult:
        """Evaluate one cell against the current shared namespace + grid."""
        cell.clear_diagnostics()
        source = cell.source()
        if not source.strip():
            return CellResult()
        c_exprs = cell.constraint_exprs() if hasattr(cell, "constraint_exprs") else []
        d_exprs = cell.condition_exprs() if hasattr(cell, "condition_exprs") else []
        result = run_cell(
            source, shared, self._grid,
            constraint_exprs=c_exprs, condition_exprs=d_exprs,
        )
        if result.error:
            cell.set_error(result.error)
        elif result.warning:
            cell.set_warning(result.warning)
        if hasattr(cell, "set_preview"):
            cell.set_preview(result.preview, result.shape_preview)

        # Auto-switch cell between expression mode and data-array mode based on return type
        if hasattr(cell, "set_data_mode"):
            should_be_data = (
                result.from_shape_inference
                and result.render_type in ("scatter", "scatter_2d")
            )
            if should_be_data != cell.is_data_mode():
                cell.set_data_mode(should_be_data)

        return result

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_run_requested(self, cell_id: str) -> None:
        """Force re-evaluate a data-mode CellWidget (→ button or focus-out)."""
        self._rebuild_namespace()

    def _on_data_cell_visibility_toggled(self, cell_id: str, is_visible: bool) -> None:
        """Show or clear a DataCellWidget's render when the 👁 is toggled."""
        idx = self._index_of(cell_id)
        if idx < 0:
            return
        cell = self._cells[idx]
        last = getattr(cell, "_last_result", None)
        if is_visible and last is not None and last.render_type:
            self._on_cell_result(cell_id, last, cell.style)
        else:
            self._on_cell_result(cell_id, CellResult(), cell.style)

    def _on_cell_changed(self, cell_id: str) -> None:
        self._maybe_morph_to_slider(cell_id)
        self._rebuild_namespace()

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
        slider.delete_requested.connect(self._on_delete_requested)
        slider.drag_started.connect(self._on_drag_started)
        slider.drag_moved.connect(self._on_drag_moved)
        slider.drag_ended.connect(self._on_drag_ended)

        # Swap in the layout and the cells list
        self._layout.replaceWidget(cell, slider)
        self._cells[idx] = slider
        cell.deleteLater()

    def _on_slider_value_changed(self, name: str, value: float) -> None:
        """
        Incremental re-evaluation: only cells downstream of the changed slider
        are re-evaluated.  All other cell outputs stay as-is from _shared_ns.
        Falls back to full rebuild if the namespace is not yet initialised.
        """
        from pringle.dag import build_dag, downstream_of
        from pringle.folder_cell_widget import FolderCellWidget

        evaluable = [c for c in self._cells if not isinstance(c, FolderCellWidget)]

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

        dag = build_dag(evaluable)
        descendants = downstream_of(dag, slider_cell.cell_id, evaluable)

        # Start from the last full namespace snapshot, updated with the new value
        shared = dict(self._shared_ns)
        shared[name] = _ns_value(value)

        from pringle.data_cell_widget import DataCellWidget

        for cell in descendants:
            if isinstance(cell, SliderWidget):
                shared[cell.name] = _ns_value(cell.value)
                continue
            if isinstance(cell, DataCellWidget):
                cell._mark_stale()
                continue
            result = self._eval_cell(cell, shared)
            shared.update(result.exports)
            if cell.is_visible_cell():
                self._on_cell_result(cell.cell_id, result, cell.style)
            else:
                self._on_cell_result(cell.cell_id, CellResult(), cell.style)

        self._shared_ns = shared

    def _on_delete_requested(self, cell_id: str) -> None:
        self.remove_cell(cell_id)

    def _on_enter_pressed(self, cell_id: str) -> None:
        self.add_cell(after_id=cell_id)

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
            geo = cell.geometry()
            if local_y < geo.top() + geo.height() // 2:
                return i
        return len(self._cells)

    def _position_drop_indicator(self, drop_idx: int) -> None:
        if not self._cells:
            self._drop_indicator.hide()
            return
        n = len(self._cells)
        if drop_idx <= 0:
            y = self._cells[0].geometry().top()
        elif drop_idx >= n:
            y = self._cells[-1].geometry().bottom()
        else:
            prev_bottom = self._cells[drop_idx - 1].geometry().bottom()
            next_top = self._cells[drop_idx].geometry().top()
            y = (prev_bottom + next_top) // 2
        w = self._container.width()
        self._drop_indicator.setGeometry(8, y - 1, w - 16, 2)
        self._drop_indicator.raise_()

    def _move_cell(self, from_idx: int, to_idx: int) -> None:
        # to_idx is the drop slot (0 = before first cell, N = after last)
        # Dropping immediately above or below the source is a no-op
        if to_idx == from_idx or to_idx == from_idx + 1:
            return
        self._push_undo()
        cell = self._cells.pop(from_idx)
        insert_idx = (to_idx - 1) if to_idx > from_idx else to_idx
        self._cells.insert(insert_idx, cell)
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
