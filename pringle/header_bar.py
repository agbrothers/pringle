"""
PringleHeaderBar — full-width window header bar.

Layout (left to right):
  [logo] [PRINGLE] [New] [Open] [Save] [📷]  ... stretch ...  [⚙ wrench]

The header spans the full window width above the left/right splitter.
File buttons trigger signals that PringleWindow connects to its session handlers.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont

_LOGO_PATH = Path(__file__).parent / "assets" / "icon-alpha.png"


class PringleHeaderBar(QWidget):
    """Full-width header containing logo, file buttons, and settings toggle."""

    new_requested        = pyqtSignal()
    open_requested       = pyqtSignal()
    save_requested       = pyqtSignal()
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
            pix = pix.scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pix)
        logo_label.setFixedSize(32, 32)
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
        self._new_btn  = QPushButton("New")
        self._open_btn = QPushButton("Open")
        self._save_btn = QPushButton("Save")
        for btn in (self._new_btn, self._open_btn, self._save_btn):
            btn.setObjectName("header_file_btn")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(btn)
            row.addSpacing(4)

        self._new_btn.clicked.connect(self.new_requested)
        self._open_btn.clicked.connect(self.open_requested)
        self._save_btn.clicked.connect(self.save_requested)

        # Screenshot button
        self._screenshot_btn = QPushButton("📷")
        self._screenshot_btn.setObjectName("header_screenshot_btn")
        self._screenshot_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._screenshot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._screenshot_btn.setToolTip("Save canvas image (PNG)")
        self._screenshot_btn.clicked.connect(self.screenshot_requested)
        self._screenshot_btn.clicked.connect(self._flash_screenshot)
        row.addWidget(self._screenshot_btn)
        row.addSpacing(4)

        row.addStretch(1)

        # Wrench / settings button
        self._wrench_btn = QPushButton("⚙")
        self._wrench_btn.setObjectName("header_wrench_btn")
        self._wrench_btn.setFixedSize(44, 44)
        self._wrench_btn.setFlat(True)
        self._wrench_btn.setCheckable(True)
        self._wrench_btn.setToolTip("Axis & view settings")
        self._wrench_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wrench_btn.clicked.connect(self.settings_toggled)
        row.addWidget(self._wrench_btn)

    def _flash_screenshot(self) -> None:
        self._screenshot_btn.setStyleSheet(
            "QPushButton#header_screenshot_btn { border-color: #E9A15F; }"
        )
        QTimer.singleShot(250, lambda: self._screenshot_btn.setStyleSheet(""))

    def set_wrench_checked(self, checked: bool) -> None:
        self._wrench_btn.blockSignals(True)
        self._wrench_btn.setChecked(checked)
        self._wrench_btn.blockSignals(False)

    def set_modified(self, modified: bool) -> None:
        """Update the Save button appearance to reflect unsaved-changes state."""
        self._save_btn.setProperty("modified", modified)
        self._save_btn.style().unpolish(self._save_btn)
        self._save_btn.style().polish(self._save_btn)
