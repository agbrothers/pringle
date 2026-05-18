"""
DataCellWidget — a run-on-demand expression cell for the data panel.

Layout:
  [CellTextEdit  ↑expand↑] [● status] [▷ Run] [↺ sub] [✕]

Below the text edit:
  [ConstraintSubCell ...] — initial_condition and recursion sub-cells

Unlike CellWidget (which auto-evaluates after a debounce), DataCellWidget
only evaluates when the ▶ Run button is clicked.  Editing the source marks
the cell as "stale" (orange dot) until the next run.
"""

from __future__ import annotations

import uuid
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QMenu, QFrame,
)
from PyQt6.QtCore import pyqtSignal, Qt

from pringle.cell_widget import CellTextEdit, ConstraintSubCell, DragHandle
from pringle.style import CellStyle


class DataCellWidget(QWidget):
    """A single data panel cell."""

    run_requested = pyqtSignal(str)              # cell_id
    delete_requested = pyqtSignal(str)           # cell_id
    visibility_toggled = pyqtSignal(str, bool)   # cell_id, is_visible
    render_mode_changed = pyqtSignal(str)        # cell_id — scatter_as_line toggled
    drag_started = pyqtSignal(str)               # cell_id
    drag_moved = pyqtSignal(str, int)            # cell_id, global_y
    drag_ended = pyqtSignal(str)                 # cell_id

    _STATUS_STYLES = {
        "idle":  "color: #bbb;",
        "ok":    "color: #2a8a2a; font-weight: bold;",
        "error": "color: #cc2222; font-weight: bold;",
        "stale": "color: #cc7700;",
    }

    def __init__(
        self,
        cell_id: str | None = None,
        style: CellStyle | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.cell_id: str = cell_id or str(uuid.uuid4())
        self.style: CellStyle = style or CellStyle()
        self._sub_cells: list[ConstraintSubCell] = []
        self._visible: bool = True
        self._last_result = None  # cached for visibility toggle
        self._build_ui()

    def _build_ui(self):
        # Outer: drag handle strip (left) + content area (right)
        outer_h = QHBoxLayout(self)
        outer_h.setContentsMargins(0, 2, 0, 2)
        outer_h.setSpacing(0)

        self._drag_handle = DragHandle(self)
        self._drag_handle.drag_started.connect(lambda: self.drag_started.emit(self.cell_id))
        self._drag_handle.drag_moved.connect(lambda y: self.drag_moved.emit(self.cell_id, y))
        self._drag_handle.drag_ended.connect(lambda: self.drag_ended.emit(self.cell_id))
        outer_h.addWidget(self._drag_handle)

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        outer_h.addWidget(content, 1)

        # Main row: [●] [text] [👁] [+] [✕]
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 6, 0)
        row.setSpacing(4)

        self._color_dot = QPushButton()
        self._color_dot.setFixedSize(18, 18)
        self._color_dot.setFlat(True)
        self._color_dot.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_color_dot()
        self._color_dot.clicked.connect(self._on_color_dot_clicked)
        row.addWidget(self._color_dot)

        self._text_edit = CellTextEdit(self)
        self._text_edit.textChanged.connect(self._on_text_changed)
        row.addWidget(self._text_edit, 1)

        self._eye_btn = QPushButton("👁")
        self._eye_btn.setFixedSize(24, 24)
        self._eye_btn.setFlat(True)
        self._eye_btn.setCheckable(True)
        self._eye_btn.setChecked(True)
        self._eye_btn.setToolTip("Toggle visibility")
        self._eye_btn.clicked.connect(self._on_visibility_toggled)
        row.addWidget(self._eye_btn)

        self._add_sub_btn = QPushButton("+")
        self._add_sub_btn.setFixedSize(24, 24)
        self._add_sub_btn.setFlat(True)
        self._add_sub_btn.setToolTip("Add sub-cell")
        self._add_sub_btn.clicked.connect(self._on_add_sub_clicked)
        row.addWidget(self._add_sub_btn)

        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFixedSize(24, 24)
        self._delete_btn.setFlat(True)
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.cell_id))
        row.addWidget(self._delete_btn)

        outer.addLayout(row)

        # Data row: [→ run] [● status] [stretch]
        data_row = QHBoxLayout()
        data_row.setContentsMargins(4, 0, 6, 2)
        data_row.setSpacing(4)

        self._run_btn = QPushButton("→")
        self._run_btn.setFixedSize(28, 22)
        self._run_btn.setToolTip("Run cell")
        self._run_btn.clicked.connect(lambda: self.run_requested.emit(self.cell_id))
        data_row.addWidget(self._run_btn)

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(self._STATUS_STYLES["idle"])
        self._status_dot.setToolTip("Cell status")
        data_row.addWidget(self._status_dot)
        data_row.addStretch(1)

        outer.addLayout(data_row)

        self._sub_container = QWidget()
        self._sub_layout = QVBoxLayout(self._sub_container)
        self._sub_layout.setContentsMargins(0, 0, 0, 0)
        self._sub_layout.setSpacing(1)
        outer.addWidget(self._sub_container)

        self._msg_label = QLabel()
        self._msg_label.setWordWrap(True)
        self._msg_label.setVisible(False)
        outer.addWidget(self._msg_label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #2a2a2a;")
        outer.addWidget(line)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def source(self) -> str:
        return self._text_edit.toPlainText()

    def set_source(self, text: str) -> None:
        self._text_edit.setPlainText(text)

    def initial_condition_exprs(self) -> list[str]:
        return [
            s.source() for s in self._sub_cells
            if s.sub_type() == "initial_condition" and s.source().strip()
        ]

    def recurrence_expr(self) -> str | None:
        for s in self._sub_cells:
            if s.sub_type() == "recursion" and s.source().strip():
                return s.source().strip()
        return None

    def add_sub_cell(self, sub_type: str = "initial_condition") -> ConstraintSubCell:
        sub = ConstraintSubCell(sub_type=sub_type, parent=self)
        sub.content_changed.connect(self._mark_stale)
        sub.delete_requested.connect(lambda: self._remove_sub_cell(sub))
        self._sub_cells.append(sub)
        self._sub_layout.addWidget(sub)
        self._mark_stale()
        return sub

    def _remove_sub_cell(self, sub: ConstraintSubCell) -> None:
        if sub in self._sub_cells:
            self._sub_cells.remove(sub)
        self._sub_layout.removeWidget(sub)
        sub.deleteLater()
        self._mark_stale()

    def set_status(self, status: str, message: str = "") -> None:
        self._status_dot.setStyleSheet(self._STATUS_STYLES.get(status, ""))
        if message:
            color = "#cc2222" if status == "error" else "#cc7700"
            self._msg_label.setText(message)
            self._msg_label.setStyleSheet(f"color: {color}; font-size: 11px; padding: 2px 8px;")
            self._msg_label.setVisible(True)
        else:
            self._msg_label.setVisible(False)

    def is_visible_cell(self) -> bool:
        return self._visible

    def focus(self) -> None:
        self._text_edit.setFocus()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_color_dot(self) -> None:
        if not self._visible:
            bg = "#333333"
        elif self.style.colormap:
            import matplotlib
            cmap = matplotlib.colormaps[self.style.colormap]
            if self.style.colormap_reversed:
                cmap = cmap.reversed()
            stops = ", ".join(
                f"stop:{i/5:.2f} #{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
                for i, (r, g, b, _) in ((i, cmap(i / 5)) for i in range(6))
            )
            bg = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, {stops})"
        else:
            r, g, b, _ = self.style.color
            bg = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))
        self._color_dot.setStyleSheet(
            f"QPushButton {{ background: {bg}; "
            f"border-radius: 9px; border: 1px solid rgba(0,0,0,0.15); }}"
            f"QPushButton:hover {{ border: 1px solid rgba(0,0,0,0.35); }}"
        )

    def _on_color_dot_clicked(self) -> None:
        from pringle.style_popover import StylePopoverWidget
        popover = StylePopoverWidget(self.style, parent=self, show_render_mode=True)
        popover.style_changed.connect(self._on_style_changed)
        pos = self._color_dot.mapToGlobal(self._color_dot.rect().bottomLeft())
        popover.move(pos)
        popover.show()

    def _on_style_changed(self, new_style) -> None:
        from dataclasses import replace
        old_scatter_as_line = self.style.scatter_as_line
        self.style = replace(new_style)
        self._update_color_dot()
        if new_style.scatter_as_line != old_scatter_as_line and self._last_result is not None:
            self.render_mode_changed.emit(self.cell_id)

    def _on_visibility_toggled(self, checked: bool) -> None:
        self._visible = checked
        self._update_color_dot()
        self.visibility_toggled.emit(self.cell_id, checked)

    def _mark_stale(self) -> None:
        self._status_dot.setStyleSheet(self._STATUS_STYLES["stale"])

    def _on_text_changed(self) -> None:
        self._mark_stale()

    def _on_add_sub_clicked(self) -> None:
        menu = QMenu(self)
        menu.addAction("Add Initial Condition", lambda: self.add_sub_cell("initial_condition"))
        menu.addAction("Add Recursion Rule", lambda: self.add_sub_cell("recursion"))
        menu.exec(self._add_sub_btn.mapToGlobal(
            self._add_sub_btn.rect().bottomLeft()
        ))
