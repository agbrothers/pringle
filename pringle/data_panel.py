"""
DataPanelWidget — scrollable list of run-on-demand data cells.

Data cells differ from equation cells in three ways:
  1. They do not auto-evaluate; clicking ▷ runs them explicitly.
  2. They receive a more permissive namespace (full numpy via `np`).
  3. They can carry recurrence sub-cells (initial_condition + recursion rule).

The panel maintains a shared namespace that accumulates outputs from all
successfully run cells.  Other components (e.g. CellListWidget) can call
get_namespace() to read these exports.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal

from pringle.data_cell_widget import DataCellWidget
from pringle.evaluator import run_cell, CellResult
from pringle.namespace import build_data_namespace
from pringle.grid import Grid, make_grid
from pringle.style import CellStyle
from pringle.recurrence import parse_recurrence, execute_recurrence


class DataPanelWidget(QWidget):
    """Scrollable list of data cells that run on demand."""

    namespace_changed = pyqtSignal()

    def __init__(
        self,
        on_cell_result: Callable[[str, CellResult, CellStyle], None] | None = None,
        grid: Grid | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._on_cell_result = on_cell_result
        self._grid = grid or make_grid()
        self._cells: list[DataCellWidget] = []
        self._namespace: dict = {}

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(6, 4, 6, 4)
        run_all_btn = QPushButton("▷▷ Run All")
        run_all_btn.setFixedHeight(28)
        run_all_btn.clicked.connect(self.run_all)
        header.addWidget(run_all_btn)
        header.addStretch(1)
        outer.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ddd;")
        outer.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        scroll.setWidget(self._container)

        self._add_btn = QPushButton("+ Add data cell")
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

    def add_cell(self, source: str = "") -> DataCellWidget:
        cell = DataCellWidget()
        cell.run_requested.connect(self._on_run_requested)
        cell.delete_requested.connect(self._on_delete_requested)

        stretch_pos = self._layout.count() - 1
        self._layout.insertWidget(stretch_pos, cell)
        self._cells.append(cell)

        if source:
            cell.set_source(source)
        return cell

    def remove_cell(self, cell_id: str) -> None:
        idx = self._index_of(cell_id)
        if idx < 0:
            return
        cell = self._cells.pop(idx)
        self._layout.removeWidget(cell)
        cell.deleteLater()
        self._rebuild_namespace()

    def run_all(self) -> None:
        """Run all cells in order, rebuilding the namespace."""
        self._namespace = {}
        for cell in self._cells:
            self._run_cell(cell)

    def get_namespace(self) -> dict:
        """Return a copy of the current data namespace."""
        return dict(self._namespace)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _run_cell(self, cell: DataCellWidget) -> None:
        source = cell.source().strip()
        if not source:
            cell.set_status("idle")
            return

        ns = build_data_namespace()
        ns.update(self._namespace)

        result = run_cell(source, ns, self._grid, is_data_cell=True)

        if result.error:
            cell.set_status("error", result.error)
            return

        # Handle recurrence sub-cells
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

        self._namespace.update(result.exports)

        if self._on_cell_result and result.render_type:
            self._on_cell_result(cell.cell_id, result, CellStyle())

        self.namespace_changed.emit()

    def _rebuild_namespace(self) -> None:
        """Rerun all cells to rebuild namespace after structural change."""
        self._namespace = {}
        for cell in self._cells:
            self._run_cell(cell)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_run_requested(self, cell_id: str) -> None:
        idx = self._index_of(cell_id)
        if idx >= 0:
            self._run_cell(self._cells[idx])

    def _on_delete_requested(self, cell_id: str) -> None:
        self.remove_cell(cell_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _index_of(self, cell_id: str) -> int:
        for i, c in enumerate(self._cells):
            if c.cell_id == cell_id:
                return i
        return -1
