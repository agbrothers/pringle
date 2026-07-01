"""
PringleHeaderBar — full-width window header bar.

Layout (left to right):
  [logo] [PRINGLE] [New] [Open] [Save] [Export]  ... stretch ...  [camera] [globe]

The header spans the full window width above the left/right splitter.
File buttons trigger signals that PringleWindow connects to its session handlers.
"""

from __future__ import annotations

from pathlib import Path
from importlib.resources import files

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QByteArray, QEvent
from PyQt6.QtGui import QPixmap, QFont, QIcon, QPainter

_LOGO_PATH = Path(__file__).parent / "assets" / "icon-alpha.png"


def _svg_icon(filename: str, color: str, size: QSize = QSize(16, 16)) -> QIcon:
    from PyQt6.QtSvg import QSvgRenderer
    svg = files("pringle").joinpath(f"assets/{filename}").read_bytes()
    svg = svg.replace(b"currentColor", color.encode())
    renderer = QSvgRenderer(QByteArray(svg))
    icon = QIcon()
    for scale in (1, 2):
        physical = QSize(size.width() * scale, size.height() * scale)
        px = QPixmap(physical)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        renderer.render(p)
        p.end()
        px.setDevicePixelRatio(scale)  # set AFTER painting — avoids clipping the render
        icon.addPixmap(px)
    return icon


class PringleHeaderBar(QWidget):
    """Full-width header containing logo, file buttons, and settings toggle."""

    new_requested        = pyqtSignal()
    open_requested       = pyqtSignal()
    save_requested       = pyqtSignal()
    export_requested     = pyqtSignal()
    screenshot_requested = pyqtSignal()
    settings_toggled     = pyqtSignal(bool)   # checked state

    _HEIGHT = 48

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self._HEIGHT)
        self.setObjectName("header_bar")
        self._build_ui()

    def _build_ui(self):
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(0)

        # Logo
        logo_label = QLabel()
        logo_label.setObjectName("header_logo")
        pix = QPixmap(str(_LOGO_PATH))
        if not pix.isNull():
            pix = pix.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            pix.setDevicePixelRatio(2)  # display at 40×40 logical, 80×80 physical
            logo_label.setPixmap(pix)
        logo_label.setFixedSize(40, 40)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(logo_label)

        # "PRINGLE" wordmark
        wordmark = QLabel("PRINGLE")
        wordmark.setObjectName("header_wordmark")
        font = QFont("Menlo")
        font.setBold(True)
        font.setItalic(True)
        font.setPointSize(15)
        wordmark.setFont(font)
        row.addWidget(wordmark)

        row.addSpacing(16)

        # File buttons
        self._new_btn    = QPushButton("New")
        self._open_btn   = QPushButton("Open")
        self._save_btn   = QPushButton("Save")
        self._export_btn = QPushButton("Export")
        for btn in (self._new_btn, self._open_btn, self._save_btn, self._export_btn):
            btn.setObjectName("header_file_btn")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(btn)
            row.addSpacing(4)

        self._export_btn.setToolTip("Export session as standalone Python script (Ctrl+Shift+E)")

        self._new_btn.clicked.connect(self.new_requested)
        self._open_btn.clicked.connect(self.open_requested)
        self._save_btn.clicked.connect(self.save_requested)
        self._export_btn.clicked.connect(self.export_requested)

        row.addStretch(1)

        # Screenshot button
        self._icon_camera_normal = _svg_icon("camera-fill.svg", "#888", QSize(26, 26))
        self._icon_camera_hover  = _svg_icon("camera-fill.svg", "#eee", QSize(26, 26))
        self._screenshot_btn = QPushButton()
        self._screenshot_btn.setObjectName("header_screenshot_btn")
        self._screenshot_btn.setIcon(self._icon_camera_normal)
        self._screenshot_btn.setIconSize(QSize(26, 26))
        self._screenshot_btn.setFixedSize(44, 44)
        self._screenshot_btn.setFlat(True)
        self._screenshot_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._screenshot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._screenshot_btn.setToolTip("Save canvas image (PNG)")
        self._screenshot_btn.clicked.connect(self.screenshot_requested)
        self._screenshot_btn.clicked.connect(self._flash_screenshot)
        self._screenshot_btn.installEventFilter(self)
        row.addWidget(self._screenshot_btn)

        # Globe / settings button
        self._icon_globe_normal  = _svg_icon("globe.svg", "#555", QSize(20, 20))
        self._icon_globe_hover   = _svg_icon("globe.svg", "#ccc", QSize(20, 20))
        self._icon_globe_checked = _svg_icon("globe.svg", "#4a9eff", QSize(20, 20))
        self._wrench_btn = QPushButton()
        self._wrench_btn.setObjectName("header_wrench_btn")
        self._wrench_btn.setIcon(self._icon_globe_normal)
        self._wrench_btn.setIconSize(QSize(20, 20))
        self._wrench_btn.setFixedSize(44, 44)
        self._wrench_btn.setFlat(True)
        self._wrench_btn.setCheckable(True)
        self._wrench_btn.setToolTip("Axis & view settings")
        self._wrench_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wrench_btn.clicked.connect(self.settings_toggled)
        self._wrench_btn.toggled.connect(self._on_globe_toggled)
        self._wrench_btn.installEventFilter(self)
        row.addWidget(self._wrench_btn)

    def eventFilter(self, obj, event):
        if obj is self._screenshot_btn:
            if event.type() == QEvent.Type.Enter:
                self._screenshot_btn.setIcon(self._icon_camera_hover)
            elif event.type() == QEvent.Type.Leave:
                self._screenshot_btn.setIcon(self._icon_camera_normal)
        elif obj is self._wrench_btn:
            if event.type() == QEvent.Type.Enter:
                self._wrench_btn.setIcon(self._icon_globe_hover)
            elif event.type() == QEvent.Type.Leave:
                icon = self._icon_globe_checked if self._wrench_btn.isChecked() else self._icon_globe_normal
                self._wrench_btn.setIcon(icon)
        return super().eventFilter(obj, event)

    def _on_globe_toggled(self, checked: bool) -> None:
        icon = self._icon_globe_checked if checked else self._icon_globe_normal
        self._wrench_btn.setIcon(icon)

    def _flash_screenshot(self) -> None:
        self._screenshot_btn.setStyleSheet(
            "QPushButton#header_screenshot_btn { border-color: #E9A15F; }"
        )
        QTimer.singleShot(250, lambda: self._screenshot_btn.setStyleSheet(""))

    def set_wrench_checked(self, checked: bool) -> None:
        self._wrench_btn.blockSignals(True)
        self._wrench_btn.setChecked(checked)
        self._wrench_btn.blockSignals(False)
        self._on_globe_toggled(checked)

    def set_modified(self, modified: bool) -> None:
        """Update the Save button appearance to reflect unsaved-changes state."""
        self._save_btn.setProperty("modified", modified)
        self._save_btn.style().unpolish(self._save_btn)
        self._save_btn.style().polish(self._save_btn)
