"""
FolderCellWidget — a collapsible section header inside the equation panel.

A folder cell acts as a visual group divider.  Member cells are tracked
by CellListWidget via an explicit folder_id mapping on each cell.

Layout:
  [drag handle] [▶/▼] [name (clickable)] [👁] [✕]

Signals
-------
collapse_changed(cell_id, collapsed)
    Emitted whenever the folder is toggled open or closed.
folder_visibility_changed(cell_id, visible)
    Emitted when the 👁 button is toggled — controls whether member
    cells render in the 3-D viewport.
"""

from __future__ import annotations

import uuid

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLineEdit, QFrame, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt

from pringle.style import CellStyle
from pringle.cell_widget import DragHandle


class FolderCellWidget(QWidget):
    """Collapsible section header — can be added to CellListWidget like any cell."""

    delete_requested = pyqtSignal(str)          # cell_id
    content_changed = pyqtSignal(str)           # cell_id (name change)
    drag_started = pyqtSignal(str)              # cell_id
    drag_moved = pyqtSignal(str, int)           # cell_id, global_y
    drag_ended = pyqtSignal(str)               # cell_id
    collapse_changed = pyqtSignal(str, bool)    # cell_id, collapsed
    folder_visibility_changed = pyqtSignal(str, bool)  # cell_id, visible

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
        self._folder_visible: bool = True
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer_h = QHBoxLayout(self)
        outer_h.setContentsMargins(0, 2, 0, 0)
        outer_h.setSpacing(0)

        self._drag_handle = DragHandle(self)
        self._drag_handle.drag_started.connect(lambda: self.drag_started.emit(self.cell_id))
        self._drag_handle.drag_moved.connect(lambda y: self.drag_moved.emit(self.cell_id, y))
        self._drag_handle.drag_ended.connect(lambda: self.drag_ended.emit(self.cell_id))
        outer_h.addWidget(self._drag_handle)

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer_h.addWidget(content, 1)

        # Header row
        header = QWidget()
        header.setObjectName("folder_header")
        row = QHBoxLayout(header)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(4)

        self._toggle_btn = QPushButton("▼")
        self._toggle_btn.setObjectName("folder_toggle")
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._on_toggle)
        row.addWidget(self._toggle_btn)

        self._name_label = QPushButton(self._name)
        self._name_label.setObjectName("folder_name")
        self._name_label.setFlat(True)
        self._name_label.setCursor(Qt.CursorShape.IBeamCursor)
        self._name_label.setToolTip("Click to rename group")
        self._name_label.clicked.connect(self._on_edit_clicked)
        row.addWidget(self._name_label, 1)

        self._name_edit = QLineEdit(self._name)
        self._name_edit.setObjectName("folder_name_edit")
        self._name_edit.setVisible(False)
        self._name_edit.returnPressed.connect(self._commit_rename)
        self._name_edit.editingFinished.connect(self._commit_rename)
        self._committing = False
        row.addWidget(self._name_edit, 1)

        self._eye_btn = QPushButton("👁")
        self._eye_btn.setFixedSize(22, 22)
        self._eye_btn.setFlat(True)
        self._eye_btn.setCheckable(True)
        self._eye_btn.setChecked(True)
        self._eye_btn.setToolTip("Toggle folder visibility in viewport")
        self._eye_btn.toggled.connect(self._on_eye_toggled)
        row.addWidget(self._eye_btn)

        del_btn = QPushButton("✕")
        del_btn.setObjectName("folder_del")
        del_btn.setFixedSize(22, 22)
        del_btn.setFlat(True)
        del_btn.setToolTip("Delete group (members are kept)")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.cell_id))
        row.addWidget(del_btn)

        outer.addWidget(header)

        # Collapsible body — empty placeholder; shown/hidden on toggle
        self._body = QWidget()
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        outer.addWidget(self._body)

        # Separator
        sep = QFrame()
        sep.setObjectName("folder_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
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

    @property
    def is_folder_visible(self) -> bool:
        return self._folder_visible

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def set_collapsed(self, collapsed: bool) -> None:
        if self._collapsed == collapsed:
            return
        self._collapsed = collapsed
        self._toggle_btn.setText("▶" if collapsed else "▼")
        self._body.setVisible(not collapsed)
        self.collapse_changed.emit(self.cell_id, collapsed)

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_toggle(self):
        self.toggle()

    def _on_eye_toggled(self, checked: bool) -> None:
        self._folder_visible = checked
        self.folder_visibility_changed.emit(self.cell_id, checked)

    def _on_edit_clicked(self):
        self._name_label.setVisible(False)
        self._name_edit.setVisible(True)
        self._name_edit.setText(self._name)
        self._name_edit.selectAll()
        self._name_edit.setFocus()

    def _commit_rename(self):
        if self._committing:
            return
        self._committing = True
        new_name = self._name_edit.text().strip() or self._name
        self._name = new_name
        self._name_label.setText(new_name)
        self._name_label.setVisible(True)
        self._name_edit.setVisible(False)
        self.content_changed.emit(self.cell_id)
        self._committing = False
