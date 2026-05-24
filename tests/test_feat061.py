"""
FEAT-061 — Auto-scroll expression panel to reveal newly added cell.

ensureWidgetVisible is deferred via QTimer.singleShot(0, ...) so it runs
after Qt processes the layout change and the new cell has valid geometry.

Tests cover:
- ensureWidgetVisible is NOT called synchronously during add_cell
- ensureWidgetVisible IS called after processEvents() (timer fires)
- Same deferral applies to add_comment_cell
- Session restore (skip_rebuild) does not trigger the deferred scroll
"""

import sys
import pytest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication

from pringle.cell_list import CellListWidget
from pringle.grid import make_grid, GridConfig


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def clist(qapp):
    return CellListWidget(
        on_cell_result=lambda cid, r, s: None,
        grid=make_grid(GridConfig(n=32)),
    )


class TestDeferredScroll:
    def test_add_cell_does_not_call_ensure_synchronously(self, qapp, clist):
        """ensureWidgetVisible must not fire during add_cell — only after event loop."""
        calls: list = []
        original = clist._scroll.ensureWidgetVisible
        clist._scroll.ensureWidgetVisible = lambda w, *a, **kw: calls.append(w)
        try:
            clist.add_cell()
            assert calls == [], "ensureWidgetVisible should be deferred, not synchronous"
        finally:
            clist._scroll.ensureWidgetVisible = original

    def test_add_cell_calls_ensure_after_process_events(self, qapp, clist):
        """After processEvents(), the deferred ensureWidgetVisible has fired."""
        calls: list = []
        original = clist._scroll.ensureWidgetVisible
        clist._scroll.ensureWidgetVisible = lambda w, *a, **kw: calls.append(w)
        try:
            cell = clist.add_cell()
            assert calls == []
            qapp.processEvents()
            assert len(calls) == 1
            assert calls[0] is cell
        finally:
            clist._scroll.ensureWidgetVisible = original

    def test_add_cell_after_id_defers_scroll(self, qapp, clist):
        """Inserting after a specific cell also defers ensureWidgetVisible."""
        anchor = clist.add_cell()
        qapp.processEvents()  # drain pending timer from anchor add

        calls: list = []
        original = clist._scroll.ensureWidgetVisible
        clist._scroll.ensureWidgetVisible = lambda w, *a, **kw: calls.append(w)
        try:
            new_cell = clist.add_cell(after_id=anchor.cell_id)
            assert calls == [], "must be deferred even for after_id inserts"
            qapp.processEvents()
            assert len(calls) == 1
            assert calls[0] is new_cell
        finally:
            clist._scroll.ensureWidgetVisible = original

    def test_add_comment_cell_defers_scroll(self, qapp, clist):
        """add_comment_cell uses the same deferred scroll."""
        calls: list = []
        original = clist._scroll.ensureWidgetVisible
        clist._scroll.ensureWidgetVisible = lambda w, *a, **kw: calls.append(w)
        try:
            cell = clist.add_comment_cell("# hello")
            assert calls == []
            qapp.processEvents()
            assert len(calls) == 1
            assert calls[0] is cell
        finally:
            clist._scroll.ensureWidgetVisible = original


class TestSessionRestoreNotScrolled:
    def test_skip_rebuild_suppresses_deferred_scroll(self, qapp):
        """Session restore (skip_rebuild=True) must not trigger the deferred scroll."""
        cl = CellListWidget(
            on_cell_result=lambda cid, r, s: None,
            grid=make_grid(GridConfig(n=32)),
        )
        calls: list = []
        original = cl._scroll.ensureWidgetVisible
        cl._scroll.ensureWidgetVisible = lambda w, *a, **kw: calls.append(w)
        try:
            cl._skip_rebuild = True
            cl.add_cell("z = x")
            cl.add_cell("z = y")
            cl._skip_rebuild = False
            qapp.processEvents()
            assert calls == [], "session restore must not trigger auto-scroll"
        finally:
            cl._scroll.ensureWidgetVisible = original
