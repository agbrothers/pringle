"""
StylePopoverWidget — floating style editor for equation cells.

Shows as a popup anchored to the color dot button. Lets the user
edit hex color, opacity, and line width without opening a separate dialog.
"""

from __future__ import annotations

import numpy as np
from dataclasses import replace
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QLineEdit, QPushButton, QButtonGroup, QRadioButton, QCheckBox,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QIcon

from pringle.style import CellStyle, COLORMAPS


def _fmt(value: float) -> str:
    """Format a float without trailing zeros: 1.0 → '1', 0.5 → '0.5'."""
    return f"{value:g}"


class _CompactDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that strips trailing zeros from the displayed value."""
    def textFromValue(self, value: float) -> str:
        return _fmt(value)


def _make_cmap_pixmap(cmap_name: str, width: int = 48, height: int = 28, reverse: bool = False) -> QPixmap:
    """Render a colormap as a horizontal gradient QPixmap."""
    import matplotlib
    cmap = matplotlib.colormaps[cmap_name]
    if reverse:
        cmap = cmap.reversed()
    x = np.linspace(0.0, 1.0, width, dtype=np.float64)
    rgba = cmap(x)                              # (width, 4) float64
    rgba_u8 = (rgba * 255).clip(0, 255).astype(np.uint8)
    img_array = np.tile(rgba_u8[np.newaxis], (height, 1, 1))  # (height, width, 4)
    buf = bytes(img_array.tobytes())
    img = QImage(buf, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(img)


class StylePopoverWidget(QFrame):
    """
    Lightweight style editor shown as a popup over the color dot.

    Emits `style_changed` every time any field is edited; the parent
    CellWidget updates its style and re-renders.
    """

    style_changed = pyqtSignal(object)      # CellStyle
    color_picker_requested = pyqtSignal()   # swatch clicked — parent opens QColorDialog
    visible_toggled = pyqtSignal(bool)      # emitted when Visible checkbox changes

    def __init__(self, style: CellStyle, parent=None, show_render_mode: bool = False,
                 show_normalize: bool = False, visible: bool = True):
        super().__init__(parent)
        self._style = replace(style)  # work on a copy
        self._show_render_mode = show_render_mode
        self._show_normalize = show_normalize
        self._visible = visible
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(1)
        self._build_ui()

    _RENDER_MODES = ["circles", "line", "spheres", "arrows"]

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        # --- Visible checkbox ---
        vis_cb = QCheckBox("Visible")
        vis_cb.setObjectName("visible_cb")
        vis_cb.setChecked(self._visible)
        vis_cb.toggled.connect(self.visible_toggled)
        layout.addWidget(vis_cb)

        if self._show_render_mode:
            # Two-column top section: spinboxes left, radio buttons right
            top_row = QHBoxLayout()
            top_row.setSpacing(12)
            left_col = QVBoxLayout()
            left_col.setSpacing(6)
        else:
            layout_target = layout
            left_col = None

        def _add_to(row):
            if self._show_render_mode:
                left_col.addLayout(row)
            else:
                layout.addLayout(row)

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
        self._swatch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swatch.setToolTip("Open color picker…")
        self._swatch.clicked.connect(self.color_picker_requested.emit)
        self._refresh_swatch()
        color_row.addWidget(self._swatch)
        color_row.addStretch()
        _add_to(color_row)

        # --- Opacity row ---
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Opacity:"))
        self._opacity_spin = _CompactDoubleSpinBox()
        self._opacity_spin.setRange(0.05, 1.0)
        self._opacity_spin.setSingleStep(0.05)
        self._opacity_spin.setDecimals(2)
        self._opacity_spin.setValue(self._style.opacity)
        self._opacity_spin.setFixedWidth(72)
        self._opacity_spin.valueChanged.connect(self._on_opacity_changed)
        op_row.addWidget(self._opacity_spin)
        op_row.addStretch()
        _add_to(op_row)

        # --- Size row (controls both line width and scatter dot size) ---
        lw_row = QHBoxLayout()
        lw_row.addWidget(QLabel("Size:"))
        self._lw_spin = _CompactDoubleSpinBox()
        self._lw_spin.setRange(0.005, 2.0)
        self._lw_spin.setSingleStep(0.005)
        self._lw_spin.setDecimals(3)
        self._lw_spin.setValue(self._style.line_width)
        self._lw_spin.setFixedWidth(72)
        self._lw_spin.valueChanged.connect(self._on_lw_changed)
        lw_row.addWidget(self._lw_spin)
        lw_row.addStretch()
        _add_to(lw_row)

        # --- Render mode radio buttons — only for data-array cells ---
        if self._show_render_mode:
            right_col = QVBoxLayout()
            right_col.setSpacing(4)
            right_col.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self._render_group = QButtonGroup(self)
            for i, (label, mode) in enumerate([
                ("Circles", "circles"), ("Line", "line"), ("Spheres", "spheres"), ("Arrows", "arrows")
            ]):
                btn = QRadioButton(label)
                btn.setObjectName("render_mode")
                btn.setChecked(self._style.scatter_render_mode == mode)
                self._render_group.addButton(btn, i)
                right_col.addWidget(btn)
            self._render_group.idToggled.connect(self._on_render_mode_changed)

            top_row.addLayout(left_col)
            top_row.addLayout(right_col)
            layout.addLayout(top_row)

            # Normalize checkbox — shown only when Arrows mode is active
            self._norm_cb = QCheckBox("Normalize lengths")
            self._norm_cb.setObjectName("normalize_cb")
            self._norm_cb.setChecked(self._style.normalize_arrows)
            self._norm_cb.toggled.connect(self._on_normalize_changed)
            self._norm_row = self._norm_cb
            layout.addWidget(self._norm_cb)
            self._norm_cb.setVisible(self._style.scatter_render_mode == "arrows")

        elif self._show_normalize:
            # Standalone normalize row for vector-type cells (always arrows, no mode choice)
            self._norm_cb = QCheckBox("Normalize lengths")
            self._norm_cb.setObjectName("normalize_cb")
            self._norm_cb.setChecked(self._style.normalize_arrows)
            self._norm_cb.toggled.connect(self._on_normalize_changed)
            layout.addWidget(self._norm_cb)

        # --- Colormap section ---
        cmap_label_row = QHBoxLayout()
        cmap_label_row.addWidget(QLabel("Colormap:"))
        cmap_label_row.addStretch()
        layout.addLayout(cmap_label_row)

        cmap_row = QHBoxLayout()
        cmap_row.setSpacing(3)

        _SWATCH_W, _SWATCH_H = 48, 28
        self._cmap_btns: dict[str, QPushButton] = {}
        for cmap_name in COLORMAPS:
            pix = _make_cmap_pixmap(cmap_name, _SWATCH_W, _SWATCH_H)
            btn = QPushButton()
            btn.setObjectName("cmap_swatch")
            btn.setFixedSize(_SWATCH_W + 4, _SWATCH_H + 4)
            btn.setIcon(QIcon(pix))
            btn.setIconSize(QSize(_SWATCH_W, _SWATCH_H))
            btn.setCheckable(True)
            btn.setChecked(self._style.colormap == cmap_name)
            btn.setToolTip(cmap_name)
            btn.clicked.connect(lambda _checked, n=cmap_name: self._on_cmap_selected(n))
            cmap_row.addWidget(btn)
            self._cmap_btns[cmap_name] = btn

        self._rev_btn = QPushButton("⇄")
        self._rev_btn.setObjectName("rev_btn")
        self._rev_btn.setFixedSize(28, _SWATCH_H + 4)
        self._rev_btn.setCheckable(True)
        self._rev_btn.setChecked(self._style.colormap_reversed)
        self._rev_btn.setToolTip("Reverse colormap")
        self._rev_btn.toggled.connect(self._on_cmap_reversed)
        cmap_row.addWidget(self._rev_btn)
        cmap_row.addStretch()
        layout.addLayout(cmap_row)

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
        self._style = replace(self._style, line_width=v, point_size=v)
        self.style_changed.emit(self._style)

    def _on_render_mode_changed(self, btn_id: int, checked: bool) -> None:
        if checked:
            self._style = replace(self._style, scatter_render_mode=self._RENDER_MODES[btn_id])
            if hasattr(self, "_norm_cb"):
                self._norm_cb.setVisible(self._style.scatter_render_mode == "arrows")
                self.adjustSize()
            self.style_changed.emit(self._style)

    def _on_normalize_changed(self, checked: bool) -> None:
        self._style = replace(self._style, normalize_arrows=checked)
        self.style_changed.emit(self._style)

    def _on_cmap_selected(self, name: str):
        new_cmap = None if self._style.colormap == name else name
        self._style = replace(self._style, colormap=new_cmap)
        self._update_cmap_btn_states()
        self.style_changed.emit(self._style)

    def _update_cmap_btn_states(self):
        for name, btn in self._cmap_btns.items():
            btn.setChecked(self._style.colormap == name)

    def _on_cmap_reversed(self, checked: bool):
        self._style = replace(self._style, colormap_reversed=checked)
        self.style_changed.emit(self._style)

    def current_style(self) -> CellStyle:
        return self._style
