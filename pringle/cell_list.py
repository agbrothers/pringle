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
    QWidget, QScrollArea, QVBoxLayout, QPushButton,
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
        self._cell_index: int = 0  # for palette cycling
        self._undo_history: deque[list[dict]] = deque(maxlen=_MAX_UNDO)
        self._redo_history: deque[list[dict]] = deque(maxlen=_MAX_UNDO)
        self._in_undo_restore: bool = False
        self.last_eval_ms: float = 0.0

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

        # "+" button to add a new cell at the bottom
        self._add_btn = QPushButton("+ Add expression")
        self._add_btn.setFlat(True)
        self._add_btn.setStyleSheet(
            "QPushButton { color: #555; padding: 8px; font-size: 13px; }"
            "QPushButton:hover { color: #222; }"
        )
        self._add_btn.clicked.connect(lambda: self.add_cell())
        outer.addWidget(self._add_btn)

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

        shared: dict = {}
        for cell in ordered_cells:
            if isinstance(cell, SliderWidget):
                shared[cell.name] = cell.value
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
        return result

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

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
        shared[name] = value

        for cell in descendants:
            if isinstance(cell, SliderWidget):
                shared[cell.name] = cell.value
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
    # Helpers
    # ------------------------------------------------------------------

    def _index_of(self, cell_id: str) -> int:
        for i, c in enumerate(self._cells):
            if c.cell_id == cell_id:
                return i
        return -1
