"""
Phase 4+5 tests: cell widget UI and cell list management.

Tests validate:
- CellWidget structure (text edit, buttons, signals)
- CellListWidget add / remove / reorder
- Shared namespace accumulation across cells
- Viewport callback receives correct render results
- Error/warning display
- Visibility toggle suppresses render callback
"""

import sys
import pytest
import numpy as np
from typing import List, Tuple

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from pringle.cell_widget import CellWidget
from pringle.cell_list import CellListWidget
from pringle.style import CellStyle, palette_color
from pringle.evaluator import CellResult
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=32))


# ---------------------------------------------------------------------------
# CellWidget
# ---------------------------------------------------------------------------

class TestCellWidget:
    def test_creates(self, qapp):
        cell = CellWidget()
        assert cell.cell_id != ""
        assert cell.source() == ""

    def test_set_source(self, qapp):
        cell = CellWidget()
        cell.set_source("z = sin(x)")
        assert cell.source() == "z = sin(x)"

    def test_error_display(self, qapp):
        cell = CellWidget()
        cell.set_error("NameError: q is not defined")
        assert not cell._error_label.isHidden()   # isHidden() checks own state only
        cell.set_error(None)
        assert cell._error_label.isHidden()

    def test_warning_display(self, qapp):
        cell = CellWidget()
        cell.set_warning("z shape mismatch")
        assert not cell._warning_label.isHidden()
        cell.clear_diagnostics()
        assert cell._warning_label.isHidden()

    def test_style_color(self, qapp):
        style = CellStyle(color=(1.0, 0.0, 0.0, 1.0))
        cell = CellWidget(style=style)
        dot_ss = cell._color_dot.styleSheet()
        assert "255,0,0" in dot_ss or "ff0000" in dot_ss.lower()

    def test_unique_ids(self, qapp):
        a = CellWidget()
        b = CellWidget()
        assert a.cell_id != b.cell_id

    def test_content_changed_signal(self, qapp):
        cell = CellWidget()
        received: list[str] = []
        cell.content_changed.connect(received.append)
        # Simulate debounced fire by calling directly
        cell._emit_changed()
        assert cell.cell_id in received


# ---------------------------------------------------------------------------
# CellListWidget
# ---------------------------------------------------------------------------

class TestCellListWidget:
    def _make_list(self, qapp, grid):
        """Build a CellListWidget with a capture callback."""
        results: list[tuple[str, CellResult, CellStyle]] = []

        def capture(cid, res, sty):
            results.append((cid, res, sty))

        clist = CellListWidget(on_cell_result=capture, grid=grid)
        return clist, results

    def test_starts_empty(self, qapp, grid):
        clist, _ = self._make_list(qapp, grid)
        assert len(clist._cells) == 0

    def test_add_cell_appends(self, qapp, grid):
        clist, _ = self._make_list(qapp, grid)
        cell = clist.add_cell("z = sin(x)")
        assert len(clist._cells) == 1
        assert clist._cells[0] is cell

    def test_add_cell_after_inserts_correctly(self, qapp, grid):
        clist, _ = self._make_list(qapp, grid)
        c1 = clist.add_cell("z = sin(x)")
        c2 = clist.add_cell("z = cos(x)")
        c_between = clist.add_cell("a = 1.0", after_id=c1.cell_id)
        # Order should be c1, c_between, c2
        assert clist._cells.index(c1) == 0
        assert clist._cells.index(c_between) == 1
        assert clist._cells.index(c2) == 2

    def test_remove_cell(self, qapp, grid):
        clist, _ = self._make_list(qapp, grid)
        cell = clist.add_cell("z = sin(x)")
        cid = cell.cell_id
        clist.remove_cell(cid)
        assert all(c.cell_id != cid for c in clist._cells)

    def test_namespace_accumulation(self, qapp, grid):
        """Slider cell exports to namespace; downstream surface cell uses it."""
        captured: list[tuple[str, CellResult, CellStyle]] = []
        clist = CellListWidget(on_cell_result=lambda cid, r, s: captured.append((cid, r, s)), grid=grid)

        clist.add_cell("a = 2.0")   # slider → exports a=2.0
        clist.add_cell("z = a * sin(x) * cos(y)")  # uses a

        # Both cells trigger rebuild — find the surface result
        surface_results = [(cid, r) for cid, r, _ in captured if r.render_type == "surface"]
        assert len(surface_results) > 0, "Expected a surface result in callback"
        _, surf = surface_results[-1]
        assert surf.data is not None

    def test_eval_error_shown_on_cell(self, qapp, grid):
        captured = []
        clist = CellListWidget(on_cell_result=lambda cid, r, s: captured.append((cid, r, s)), grid=grid)
        cell = clist.add_cell("z = q * sin(x)")  # q undefined → NameError
        # Error label should be set immediately (rebuild is synchronous when source given)
        assert not cell._error_label.isHidden(), "Error label should be visible after failed eval"

    def test_palette_cycles(self, qapp, grid):
        clist, _ = self._make_list(qapp, grid)
        colors = []
        for i in range(10):
            cell = clist.add_cell()
            colors.append(cell.style.color)
        # Colors should cycle — not all the same
        assert len(set(colors)) > 1

    def test_visibility_toggle_suppresses_render(self, qapp, grid):
        """When a cell is hidden, the callback receives a result with no render_type."""
        rendered_types: list = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: rendered_types.append(r.render_type),
            grid=grid,
        )
        cell = clist.add_cell("z = sin(x) * cos(y)")
        qapp.processEvents()

        rendered_types.clear()
        # Toggle visibility off
        cell._eye_btn.setChecked(False)
        cell._on_visibility_toggled(False)
        qapp.processEvents()

        # The callback should have been called with a no-render result
        assert any(t is None for t in rendered_types)

    def test_two_surfaces_independent(self, qapp, grid):
        """Two z= cells produce two independent render callback invocations."""
        surface_ids: list[str] = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: surface_ids.append(cid) if r.render_type == "surface" else None,
            grid=grid,
        )
        c1 = clist.add_cell("z = sin(x) * cos(y)")
        c2 = clist.add_cell("z = x**2 - y**2")
        qapp.processEvents()

        # Both cell IDs should have appeared in surface callbacks
        assert c1.cell_id in surface_ids
        assert c2.cell_id in surface_ids
        # They're different cells
        assert c1.cell_id != c2.cell_id


# ---------------------------------------------------------------------------
# PringleWindow integration
# ---------------------------------------------------------------------------

class TestPringleWindowIntegration:
    def test_add_cell_renders(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        win.cell_list.add_cell("z = sin(x) * cos(y)")
        qapp.processEvents()
        # Object should appear in the viewport's scene
        assert len(win.viewport.renderer._objects) > 0
        win.close()

    def test_delete_cell_removes_from_scene(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        cell = win.cell_list.add_cell("z = sin(x) * cos(y)")
        qapp.processEvents()
        cid = cell.cell_id
        win.cell_list.remove_cell(cid)
        qapp.processEvents()
        assert cid not in win.viewport.renderer._objects
        win.close()

    def test_slider_then_surface(self, qapp, grid):
        from pringle.app import PringleWindow
        win = PringleWindow(grid=grid)
        win.cell_list.add_cell("a = 2.0")
        win.cell_list.add_cell("z = a * sin(x) * cos(y)")
        qapp.processEvents()
        # At least one object should be in the scene (the surface)
        assert len(win.viewport.renderer._objects) >= 1
        win.close()


# ---------------------------------------------------------------------------
# BUG-039: comment cell edits must not trigger namespace rebuild
# ---------------------------------------------------------------------------

class TestCommentCellNoRebuild:
    def _make_list(self, qapp, grid):
        results = []
        clist = CellListWidget(
            on_cell_result=lambda cid, r, s: results.append((cid, r, s)),
            grid=grid,
        )
        return clist, results

    def test_comment_edit_does_not_rebuild(self, qapp, grid):
        from pringle.comment_cell_widget import CommentCellWidget
        clist, _ = self._make_list(qapp, grid)
        clist.add_cell("z = sin(x) * cos(y)")
        comment = clist.add_comment_cell("# hello")
        assert isinstance(comment, CommentCellWidget)

        rebuild_count = 0
        original_rebuild = clist._rebuild_namespace
        def counting_rebuild():
            nonlocal rebuild_count
            rebuild_count += 1
            original_rebuild()
        clist._rebuild_namespace = counting_rebuild

        rebuild_count = 0
        comment._edit.setPlainText("# edited text")
        assert rebuild_count == 0

    def test_morphed_comment_does_not_rebuild(self, qapp, grid):
        """A cell that morphs to CommentCellWidget via # prefix should also skip rebuild."""
        from pringle.comment_cell_widget import CommentCellWidget
        clist, _ = self._make_list(qapp, grid)
        cell = clist.add_cell()
        cell.set_source("# start as comment")
        # Force the morph to happen
        clist._on_cell_changed(cell.cell_id)
        idx = clist._index_of(cell.cell_id)
        comment = clist._cells[idx]
        assert isinstance(comment, CommentCellWidget)

        rebuild_count = 0
        original_rebuild = clist._rebuild_namespace
        def counting_rebuild():
            nonlocal rebuild_count
            rebuild_count += 1
            original_rebuild()
        clist._rebuild_namespace = counting_rebuild

        rebuild_count = 0
        comment._edit.setPlainText("edited body")
        assert rebuild_count == 0

    def test_equation_cell_still_rebuilds(self, qapp, grid):
        """Non-comment cells must still trigger a rebuild on content change."""
        clist, _ = self._make_list(qapp, grid)
        cell = clist.add_cell("z = sin(x)")

        rebuild_count = 0
        original_rebuild = clist._rebuild_namespace
        def counting_rebuild():
            nonlocal rebuild_count
            rebuild_count += 1
            original_rebuild()
        clist._rebuild_namespace = counting_rebuild

        rebuild_count = 0
        clist._on_cell_changed(cell.cell_id)
        assert rebuild_count >= 1


# ---------------------------------------------------------------------------
# CellTextEdit editing improvements (FEAT-044)
# ---------------------------------------------------------------------------

class TestCellTextEdit:
    def test_tab_inserts_four_spaces(self, qapp):
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtCore import QEvent
        from pringle.cell_widget import CellTextEdit
        edit = CellTextEdit()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
        edit.keyPressEvent(event)
        assert edit.toPlainText() == "    "

    def test_tab_stop_distance_is_four_chars(self, qapp):
        from PyQt6.QtGui import QFontMetricsF
        from pringle.cell_widget import CellTextEdit
        edit = CellTextEdit()
        expected = QFontMetricsF(edit.font()).horizontalAdvance(' ') * 4
        assert abs(edit.tabStopDistance() - expected) < 0.5

    def test_wheel_event_ignored(self, qapp):
        from PyQt6.QtGui import QWheelEvent
        from PyQt6.QtCore import QPointF, QPoint
        from pringle.cell_widget import CellTextEdit
        edit = CellTextEdit()
        event = QWheelEvent(
            QPointF(0, 0), QPointF(0, 0),
            QPoint(0, 0), QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        edit.wheelEvent(event)
        assert not event.isAccepted()

    def test_bracket_wraps_selection(self, qapp):
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtCore import QEvent
        from pringle.cell_widget import CellTextEdit
        edit = CellTextEdit()
        edit.setPlainText("abc")
        cursor = edit.textCursor()
        cursor.select(cursor.SelectionType.Document)
        edit.setTextCursor(cursor)
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_ParenLeft, Qt.KeyboardModifier.NoModifier, "(")
        edit.keyPressEvent(event)
        assert edit.toPlainText() == "(abc)"

    def test_bracket_no_selection_falls_through(self, qapp):
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtCore import QEvent
        from pringle.cell_widget import CellTextEdit
        edit = CellTextEdit()
        # No selection — bracket should be inserted literally by Qt's default handler
        assert not edit.textCursor().hasSelection()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_ParenLeft, Qt.KeyboardModifier.NoModifier, "(")
        edit.keyPressEvent(event)
        assert edit.toPlainText() == "("

    def test_square_bracket_wraps_selection(self, qapp):
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtCore import QEvent
        from pringle.cell_widget import CellTextEdit
        edit = CellTextEdit()
        edit.setPlainText("xyz")
        cursor = edit.textCursor()
        cursor.select(cursor.SelectionType.Document)
        edit.setTextCursor(cursor)
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_BracketLeft, Qt.KeyboardModifier.NoModifier, "[")
        edit.keyPressEvent(event)
        assert edit.toPlainText() == "[xyz]"
