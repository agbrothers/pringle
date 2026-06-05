"""
BUG-068: Arrow keys jump cells from non-boundary visual lines in wrapped cells.

In a single-block cell whose text wraps across multiple visual rows, the old
blockNumber() == 0 / blockCount()-1 checks fired from any visual line.

Fix: replaced with QTextLayout.lineForTextPosition() checks that require both
the logical-block boundary AND the visual-line boundary to be at the edge
before emitting navigate_up/down_requested.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QTextCursor

from pringle.cell_widget import CellTextEdit


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _press(widget, key):
    event = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    widget.keyPressEvent(event)


def _make_wrapped_editor(qapp) -> CellTextEdit:
    """Return a CellTextEdit narrow enough to visually wrap the test text."""
    e = CellTextEdit(allow_newline=False)
    # Force a width that is narrow enough to wrap a ~60-char expression at any
    # typical monospace font size.
    e.resize(120, 300)
    e.show()
    # Long single-block text with no newlines — should wrap onto ≥2 visual lines.
    e.setPlainText("aaaaaaaaa_long_name_x = bbbbbbbb_long_name_y + cccccccc_long_name_z")
    qapp.processEvents()
    return e


class TestVisualLineWrappingNavigation:
    def test_wrapping_actually_occurred(self, qapp):
        """Precondition: the test text really does wrap at the chosen widget width."""
        e = _make_wrapped_editor(qapp)
        layout = e.document().firstBlock().layout()
        assert layout.lineCount() > 1, (
            "Test precondition failed: text did not wrap — "
            "increase text length or decrease widget width"
        )

    def test_down_from_first_visual_line_does_not_escape(self, qapp):
        """Down on visual line 0 of a wrapped single-block cell must not emit navigate_down."""
        e = _make_wrapped_editor(qapp)
        emitted = []
        e.navigate_down_requested.connect(lambda: emitted.append(True))

        # Place cursor at the very start (visual line 0).
        cursor = e.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        e.setTextCursor(cursor)

        _press(e, Qt.Key.Key_Down)
        assert not emitted, "navigate_down_requested should not fire from a non-last visual line"

    def test_up_from_last_visual_line_does_not_escape(self, qapp):
        """Up on a non-first visual line of the only block must not emit navigate_up."""
        e = _make_wrapped_editor(qapp)
        emitted = []
        e.navigate_up_requested.connect(lambda: emitted.append(True))

        # Place cursor at the end (last visual line of the only block).
        cursor = e.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        e.setTextCursor(cursor)

        # Verify cursor is NOT on visual line 0 (it's on the last visual line).
        layout = e.document().firstBlock().layout()
        pos_in_block = cursor.positionInBlock()
        line_num = layout.lineForTextPosition(pos_in_block).lineNumber()
        assert line_num > 0, "Cursor should be on a non-first visual line for this test"

        _press(e, Qt.Key.Key_Up)
        assert not emitted, "navigate_up_requested should not fire from a non-first visual line"

    def test_up_from_first_visual_line_does_escape(self, qapp):
        """Up on visual line 0 of the first block must emit navigate_up (normal case)."""
        e = _make_wrapped_editor(qapp)
        emitted = []
        e.navigate_up_requested.connect(lambda: emitted.append(True))

        cursor = e.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        e.setTextCursor(cursor)

        _press(e, Qt.Key.Key_Up)
        assert emitted, "navigate_up_requested should fire from the first visual line"

    def test_down_from_last_visual_line_does_escape(self, qapp):
        """Down on the last visual line of the only block must emit navigate_down (normal case)."""
        e = _make_wrapped_editor(qapp)
        emitted = []
        e.navigate_down_requested.connect(lambda: emitted.append(True))

        cursor = e.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        e.setTextCursor(cursor)

        _press(e, Qt.Key.Key_Down)
        assert emitted, "navigate_down_requested should fire from the last visual line"
