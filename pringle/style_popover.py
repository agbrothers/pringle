"""
StylePopoverWidget — floating style editor for equation cells.

Shows as a popup anchored to the color dot button. Lets the user
edit hex color, opacity, and line width without opening a separate dialog.
"""

from __future__ import annotations

from dataclasses import replace
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QLineEdit, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

from pringle.style import CellStyle


class StylePopoverWidget(QFrame):
    """
    Lightweight style editor shown as a popup over the color dot.

    Emits `style_changed` every time any field is edited; the parent
    CellWidget updates its style and re-renders.
    """

    style_changed = pyqtSignal(object)  # CellStyle

    def __init__(self, style: CellStyle, parent=None):
        super().__init__(parent)
        self._style = replace(style)  # work on a copy
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self.setStyleSheet(
            "StylePopoverWidget { background: #fff; border: 1px solid #ccc; border-radius: 4px; }"
        )
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        # --- Color row ---
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))

        self._hex_edit = QLineEdit(self._style.color_hex())
        self._hex_edit.setMaxLength(7)
        self._hex_edit.setFixedWidth(72)
        self._hex_edit.setPlaceholderText("#rrggbb")
        self._hex_edit.textEdited.connect(self._on_hex_edited)
        color_row.addWidget(self._hex_edit)

        self._swatch = QPushButton()
        self._swatch.setFixedSize(20, 20)
        self._swatch.setEnabled(False)
        self._swatch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh_swatch()
        color_row.addWidget(self._swatch)
        color_row.addStretch()
        layout.addLayout(color_row)

        # --- Opacity row ---
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Opacity:"))
        self._opacity_spin = QDoubleSpinBox()
        self._opacity_spin.setRange(0.05, 1.0)
        self._opacity_spin.setSingleStep(0.05)
        self._opacity_spin.setDecimals(2)
        self._opacity_spin.setValue(self._style.opacity)
        self._opacity_spin.setFixedWidth(72)
        self._opacity_spin.valueChanged.connect(self._on_opacity_changed)
        op_row.addWidget(self._opacity_spin)
        op_row.addStretch()
        layout.addLayout(op_row)

        # --- Line width row ---
        lw_row = QHBoxLayout()
        lw_row.addWidget(QLabel("Line width:"))
        self._lw_spin = QDoubleSpinBox()
        self._lw_spin.setRange(0.5, 10.0)
        self._lw_spin.setSingleStep(0.5)
        self._lw_spin.setDecimals(1)
        self._lw_spin.setValue(self._style.line_width)
        self._lw_spin.setFixedWidth(72)
        self._lw_spin.valueChanged.connect(self._on_lw_changed)
        lw_row.addWidget(self._lw_spin)
        lw_row.addStretch()
        layout.addLayout(lw_row)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_swatch(self):
        r, g, b, _ = self._style.color
        hex_str = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))
        self._swatch.setStyleSheet(
            f"background-color: {hex_str}; border: 1px solid #aaa; border-radius: 3px;"
        )

    def _on_hex_edited(self, text: str):
        if len(text) == 7 and text.startswith("#"):
            try:
                r = int(text[1:3], 16) / 255
                g = int(text[3:5], 16) / 255
                b = int(text[5:7], 16) / 255
                self._style = replace(self._style, color=(r, g, b, self._style.color[3]))
                self._refresh_swatch()
                self.style_changed.emit(self._style)
            except ValueError:
                pass

    def _on_opacity_changed(self, v: float):
        self._style = replace(self._style, opacity=v)
        self.style_changed.emit(self._style)

    def _on_lw_changed(self, v: float):
        self._style = replace(self._style, line_width=v)
        self.style_changed.emit(self._style)

    def current_style(self) -> CellStyle:
        return self._style
