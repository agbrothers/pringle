"""
FolderCellWidget — a collapsible section header inside the equation panel.

A folder cell acts as a visual group divider.  It does not participate in
expression evaluation; the DAG and namespace builder skip it.

Layout:
  [▶/▼] [name label/edit] [edit] [✕]

The body (content area) below the header can hold other widgets when
drag-and-drop grouping is implemented in a future phase.  For now it is
always empty — the folder is purely a collapsible banner.
"""

from __future__ import annotations

import uuid

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QLineEdit, QFrame, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt

from pringle.style import CellStyle


class FolderCellWidget(QWidget):
    """Collapsible section header — can be added to CellListWidget like any cell."""

    delete_requested = pyqtSignal(str)   # cell_id
    content_changed = pyqtSignal(str)    # cell_id (name change)

    def __init__(
        self,
        cell_id: str | None = None,
        name: str = "Group",
        style: CellStyle | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.cell_id: str = cell_id or str(uuid.uuid4())
        self.style: CellStyle = style or CellStyle(color=(0.55, 0.55, 0.55, 1.0))
        self._name: str = name
        self._collapsed: bool = False
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 0)
        outer.setSpacing(0)

        # Header row
        header = QWidget()
        header.setStyleSheet(
            "background: #f0f0f0; border-top: 1px solid #ccc; border-bottom: 1px solid #ccc;"
        )
        row = QHBoxLayout(header)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(4)

        self._toggle_btn = QPushButton("▼")
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._on_toggle)
        row.addWidget(self._toggle_btn)

        self._name_label = QLabel(self._name)
        self._name_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #444;")
        row.addWidget(self._name_label, 1)

        self._name_edit = QLineEdit(self._name)
        self._name_edit.setStyleSheet(
            "font-weight: bold; font-size: 12px; border: 1px solid #bbb; border-radius: 2px;"
        )
        self._name_edit.setVisible(False)
        self._name_edit.returnPressed.connect(self._commit_rename)
        self._name_edit.editingFinished.connect(self._commit_rename)
        row.addWidget(self._name_edit, 1)

        edit_btn = QPushButton("✏")
        edit_btn.setFixedSize(22, 22)
        edit_btn.setFlat(True)
        edit_btn.setToolTip("Rename group")
        edit_btn.clicked.connect(self._on_edit_clicked)
        row.addWidget(edit_btn)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setFlat(True)
        del_btn.setToolTip("Delete group")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.cell_id))
        row.addWidget(del_btn)

        outer.addWidget(header)

        # Collapsible body (empty — placeholder for drag-drop in a future phase)
        self._body = QWidget()
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._body.setVisible(True)
        outer.addWidget(self._body)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ddd;")
        outer.addWidget(sep)

    # ------------------------------------------------------------------
    # CellWidget interface (so CellListWidget can treat it uniformly)
    # ------------------------------------------------------------------

    def source(self) -> str:
        return ""

    def is_visible_cell(self) -> bool:
        return False

    def focus(self) -> None:
        pass

    def set_error(self, msg: str | None) -> None:
        pass

    def set_warning(self, msg: str | None) -> None:
        pass

    def clear_diagnostics(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._toggle_btn.setText("▶" if collapsed else "▼")
        self._body.setVisible(not collapsed)

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_toggle(self):
        self.toggle()

    def _on_edit_clicked(self):
        self._name_label.setVisible(False)
        self._name_edit.setVisible(True)
        self._name_edit.setText(self._name)
        self._name_edit.selectAll()
        self._name_edit.setFocus()

    def _commit_rename(self):
        new_name = self._name_edit.text().strip() or self._name
        self._name = new_name
        self._name_label.setText(new_name)
        self._name_label.setVisible(True)
        self._name_edit.setVisible(False)
        self.content_changed.emit(self.cell_id)
