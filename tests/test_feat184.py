"""
FEAT-184 — Bottom border on the last visible cell in the panel.

_update_last_cell() sets property("last", True) on the last visible cell and
False on all others. This is used by QSS to render a border-bottom only on
that cell.

Edge cases:
- add/remove changes which cell is last
- folder collapse changes last visible cell (folder header may become last)
- session load after Pass 2 (collapse) sets the correct last cell
- moving cells updates the last marker
"""

import sys
import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def clist(qapp):
    from pringle.cell_list import CellListWidget
    w = CellListWidget(on_cell_result=lambda *a: None)
    return w


class TestUpdateLastCell:
    def test_single_cell_is_last(self, clist):
        cell = clist.add_cell("x + 1")
        assert cell.property("last") is True

    def test_last_cell_only_marked(self, clist):
        a = clist.add_cell("a = 1")
        b = clist.add_cell("b = 2", after_id=a.cell_id)
        c = clist.add_cell("c = 3", after_id=b.cell_id)
        assert a.property("last") is False
        assert b.property("last") is False
        assert c.property("last") is True

    def test_remove_last_updates_marker(self, clist):
        a = clist.add_cell("a = 1")
        b = clist.add_cell("b = 2", after_id=a.cell_id)
        assert b.property("last") is True
        clist.remove_cell(b.cell_id)
        assert a.property("last") is True

    def test_remove_middle_does_not_change_last(self, clist):
        a = clist.add_cell("a = 1")
        b = clist.add_cell("b = 2", after_id=a.cell_id)
        c = clist.add_cell("c = 3", after_id=b.cell_id)
        clist.remove_cell(b.cell_id)
        assert a.property("last") is False
        assert c.property("last") is True

    def test_comment_cell_can_be_last(self, clist):
        eq = clist.add_cell("x = 1")
        cm = clist.add_comment_cell("# note", after_id=eq.cell_id)
        assert eq.property("last") is False
        assert cm.property("last") is True

    def test_folder_cell_can_be_last(self, clist):
        eq = clist.add_cell("x = 1")
        folder = clist.add_folder("Group", after_id=eq.cell_id)
        assert eq.property("last") is False
        assert folder.property("last") is True

    def test_folder_collapse_updates_last(self, clist):
        """Collapsing a folder hides its members; the folder header becomes last."""
        folder = clist.add_folder("Group")
        member = clist.add_cell("m = 1", after_id=folder.cell_id)
        clist._assign_folder(member, folder.cell_id)
        assert member.property("last") is True
        # Simulate collapse
        clist._on_folder_collapse_changed(folder.cell_id, collapsed=True)
        assert not member.isVisible()
        assert folder.property("last") is True
        assert member.property("last") is False

    def test_folder_expand_restores_last(self, clist):
        """Expanding a folder re-shows members; the last member becomes last again."""
        folder = clist.add_folder("Group")
        member = clist.add_cell("m = 1", after_id=folder.cell_id)
        clist._assign_folder(member, folder.cell_id)
        clist._on_folder_collapse_changed(folder.cell_id, collapsed=True)
        clist._on_folder_collapse_changed(folder.cell_id, collapsed=False)
        assert not member.isHidden()
        assert member.property("last") is True
        assert folder.property("last") is False

    def test_move_cell_up_updates_last(self, clist):
        a = clist.add_cell("a = 1")
        b = clist.add_cell("b = 2", after_id=a.cell_id)
        assert b.property("last") is True
        clist.move_cell_up(b.cell_id)
        # b moved above a; a is now last
        assert a.property("last") is True
        assert b.property("last") is False

    def test_move_cell_down_updates_last(self, clist):
        a = clist.add_cell("a = 1")
        b = clist.add_cell("b = 2", after_id=a.cell_id)
        assert b.property("last") is True
        clist.move_cell_down(a.cell_id)
        # a moved below b; a is now last
        assert a.property("last") is True
        assert b.property("last") is False
