"""
FEAT-065 — Cmd+[ / Cmd+] and Option+Up/Down to move cells in/out of folders and reorder.

indent_cell(cell_id)    — Cmd+]: move cell into folder directly above it.
outdent_cell(cell_id)   — Cmd+[: move cell out of its current folder.
move_cell_up(cell_id)   — Opt+Up:   move cell one position up in panel order.
move_cell_down(cell_id) — Opt+Down: move cell one position down in panel order.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.cell_list import CellListWidget
from pringle.cell_widget import CellWidget
from pringle.slider_widget import SliderWidget
from pringle.comment_cell_widget import CommentCellWidget
from pringle.folder_cell_widget import FolderCellWidget
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


# ---------------------------------------------------------------------------
# outdent_cell — no-ops
# ---------------------------------------------------------------------------

def test_outdent_noop_cell_not_in_folder(qapp, clist):
    """outdent_cell on a top-level cell is a no-op."""
    cell = clist.add_cell(source="z = x")
    cell_id = cell.cell_id
    order_before = [c.cell_id for c in clist._cells]
    clist.outdent_cell(cell_id)
    assert [c.cell_id for c in clist._cells] == order_before
    assert clist._cell_folder.get(cell_id) is None


def test_outdent_noop_on_folder_cell(qapp):
    """outdent_cell on a FolderCellWidget is a no-op."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    order_before = [c.cell_id for c in cl._cells]
    cl.outdent_cell(folder.cell_id)
    assert [c.cell_id for c in cl._cells] == order_before


# ---------------------------------------------------------------------------
# indent_cell — no-ops
# ---------------------------------------------------------------------------

def test_indent_noop_no_folder_above(qapp):
    """indent_cell when no folder is directly above is a no-op."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    c1 = cl.add_cell(source="a = 1")
    c2 = cl.add_cell(source="b = 2")
    order_before = [c.cell_id for c in cl._cells]
    cl.indent_cell(c2.cell_id)
    assert [c.cell_id for c in cl._cells] == order_before
    assert cl._cell_folder.get(c2.cell_id) is None


def test_indent_noop_on_folder_cell(qapp):
    """indent_cell on a FolderCellWidget is a no-op."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    order_before = [c.cell_id for c in cl._cells]
    cl.indent_cell(folder.cell_id)
    assert [c.cell_id for c in cl._cells] == order_before


def test_indent_noop_first_cell(qapp):
    """indent_cell on the first cell (idx==0) is a no-op."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    cell = cl.add_cell(source="z = x")
    order_before = [c.cell_id for c in cl._cells]
    cl.indent_cell(cell.cell_id)
    assert [c.cell_id for c in cl._cells] == order_before


# ---------------------------------------------------------------------------
# indent_cell — folder header directly above
# ---------------------------------------------------------------------------

def test_indent_into_folder_header_directly_above(qapp):
    """Cmd+] when folder header is at idx-1: cell is assigned to that folder."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    cell = cl.add_cell(source="z = x")
    cell_id = cell.cell_id
    folder_id = folder.cell_id

    cl.indent_cell(cell_id)

    assert cl._cell_folder.get(cell_id) == folder_id
    assert cell.contentsMargins().left() == 16


def test_indent_into_folder_header_empty_folder_position(qapp):
    """After indent into empty folder, cell appears right after the folder header."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    cell = cl.add_cell(source="z = x")
    folder_id = folder.cell_id
    cell_id = cell.cell_id

    cl.indent_cell(cell_id)

    ids = [c.cell_id for c in cl._cells]
    assert ids.index(folder_id) < ids.index(cell_id)


# ---------------------------------------------------------------------------
# indent_cell — folder member directly above
# ---------------------------------------------------------------------------

def test_indent_when_above_is_folder_member(qapp):
    """Cmd+] when the cell above is a folder member: join that folder."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    folder_id = folder.cell_id
    member = cl.add_cell(source="a = 1")
    cl._assign_folder(member, folder_id)
    new_cell = cl.add_cell(source="b = 2")
    new_cell_id = new_cell.cell_id

    cl.indent_cell(new_cell_id)

    assert cl._cell_folder.get(new_cell_id) == folder_id


# ---------------------------------------------------------------------------
# outdent_cell — only member
# ---------------------------------------------------------------------------

def test_outdent_only_member(qapp):
    """outdent_cell on the only member: folder becomes empty, cell exits."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    folder_id = folder.cell_id
    cell = cl.add_cell(source="z = x")
    cell_id = cell.cell_id
    cl._assign_folder(cell, folder_id)

    cl.outdent_cell(cell_id)

    assert cl._cell_folder.get(cell_id) is None
    assert cl._folder_members(folder_id) == []
    # Cell appears after folder header
    ids = [c.cell_id for c in cl._cells]
    assert ids.index(folder_id) < ids.index(cell_id)
    assert cell.contentsMargins().left() == 0


# ---------------------------------------------------------------------------
# outdent_cell — last of N members
# ---------------------------------------------------------------------------

def test_outdent_last_of_n_members(qapp):
    """outdent_cell on the last of multiple members: cell exits, others remain."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    folder_id = folder.cell_id
    m1 = cl.add_cell(source="a = 1")
    m2 = cl.add_cell(source="b = 2")
    last = cl.add_cell(source="c = 3")
    cl._assign_folder(m1, folder_id)
    cl._assign_folder(m2, folder_id)
    cl._assign_folder(last, folder_id)
    last_id = last.cell_id

    cl.outdent_cell(last_id)

    assert cl._cell_folder.get(last_id) is None
    assert cl._cell_folder.get(m1.cell_id) == folder_id
    assert cl._cell_folder.get(m2.cell_id) == folder_id
    ids = [c.cell_id for c in cl._cells]
    assert ids.index(m2.cell_id) < ids.index(last_id)


# ---------------------------------------------------------------------------
# outdent_cell — non-last member
# ---------------------------------------------------------------------------

def test_outdent_non_last_member_moves_to_after_last(qapp):
    """outdent_cell on a non-last member: cell moves to after the last member."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    folder_id = folder.cell_id
    first = cl.add_cell(source="a = 1")
    second = cl.add_cell(source="b = 2")
    third = cl.add_cell(source="c = 3")
    cl._assign_folder(first, folder_id)
    cl._assign_folder(second, folder_id)
    cl._assign_folder(third, folder_id)
    first_id = first.cell_id

    cl.outdent_cell(first_id)

    assert cl._cell_folder.get(first_id) is None
    assert cl._cell_folder.get(second.cell_id) == folder_id
    assert cl._cell_folder.get(third.cell_id) == folder_id
    ids = [c.cell_id for c in cl._cells]
    assert ids.index(third.cell_id) < ids.index(first_id)


# ---------------------------------------------------------------------------
# Collapsed folder behaviour
# ---------------------------------------------------------------------------

def test_indent_into_collapsed_folder_hides_cell(qapp):
    """Cmd+] into a collapsed folder: cell is added and hidden."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    folder_id = folder.cell_id
    # Collapse the folder
    cl._on_folder_collapse_changed(folder_id, True)
    cell = cl.add_cell(source="z = x")
    cell.setVisible(True)  # explicitly ensure it starts visible
    cell_id = cell.cell_id

    cl.indent_cell(cell_id)

    assert cl._cell_folder.get(cell_id) == folder_id
    assert not cell.isVisible()


def test_outdent_from_collapsed_folder_makes_cell_visible(qapp):
    """Cmd+[ from a collapsed folder: cell becomes visible again."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    folder_id = folder.cell_id
    cell = cl.add_cell(source="z = x")
    cell_id = cell.cell_id
    cl._assign_folder(cell, folder_id)
    # Collapse so cell is hidden
    cl._on_folder_collapse_changed(folder_id, True)
    assert not cell.isVisible()

    cl.outdent_cell(cell_id)

    assert cl._cell_folder.get(cell_id) is None
    # setVisible(True) was called; isHidden() reflects the widget's own flag
    # (isVisible() additionally requires all ancestors to be shown)
    assert not cell.isHidden()


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

def test_undo_after_indent(qapp):
    """Undo after indent_cell restores order and folder assignment."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    folder_id = folder.cell_id
    cell = cl.add_cell(source="z = x")
    cell_id = cell.cell_id
    order_before = [c.cell_id for c in cl._cells]
    folder_before = cl._cell_folder.get(cell_id)

    cl.indent_cell(cell_id)
    cl.undo()

    cur = cl._cells[cl._index_of(cell_id)]
    assert cl._cell_folder.get(cell_id) == folder_before
    assert [c.cell_id for c in cl._cells] == order_before


def test_undo_after_outdent(qapp):
    """Undo after outdent_cell restores folder assignment."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    folder_id = folder.cell_id
    cell = cl.add_cell(source="z = x")
    cell_id = cell.cell_id
    cl._assign_folder(cell, folder_id)
    order_before = [c.cell_id for c in cl._cells]

    cl.outdent_cell(cell_id)
    cl.undo()

    assert cl._cell_folder.get(cell_id) == folder_id
    assert [c.cell_id for c in cl._cells] == order_before


# ---------------------------------------------------------------------------
# Signal wiring — indent_at / outdent_at emitted from CellTextEdit
# ---------------------------------------------------------------------------

def test_cell_text_edit_emits_indent_signal(qapp):
    """CellTextEdit.indent_at signal is connected to CellWidget.indent_requested."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent

    cell = CellWidget()
    received = []
    cell.indent_requested.connect(lambda cid: received.append(cid))

    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_BracketRight,
        Qt.KeyboardModifier.ControlModifier,
    )
    cell._text_edit.keyPressEvent(event)
    assert received == [cell.cell_id]


def test_cell_text_edit_emits_outdent_signal(qapp):
    """CellTextEdit.outdent_at signal is connected to CellWidget.outdent_requested."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent

    cell = CellWidget()
    received = []
    cell.outdent_requested.connect(lambda cid: received.append(cid))

    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_BracketLeft,
        Qt.KeyboardModifier.ControlModifier,
    )
    cell._text_edit.keyPressEvent(event)
    assert received == [cell.cell_id]


# ---------------------------------------------------------------------------
# move_cell_up / move_cell_down — no-ops
# ---------------------------------------------------------------------------

def test_move_up_noop_first_cell(qapp):
    """move_cell_up on the first cell is a no-op."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    cell = cl.add_cell(source="z = x")
    order_before = [c.cell_id for c in cl._cells]
    cl.move_cell_up(cell.cell_id)
    assert [c.cell_id for c in cl._cells] == order_before


def test_move_down_noop_last_cell(qapp):
    """move_cell_down on the last cell is a no-op."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    cl.add_cell(source="a = 1")
    cell = cl.add_cell(source="z = x")
    order_before = [c.cell_id for c in cl._cells]
    cl.move_cell_down(cell.cell_id)
    assert [c.cell_id for c in cl._cells] == order_before


def test_move_up_noop_on_folder_cell(qapp):
    """move_cell_up on a FolderCellWidget is a no-op."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    cl.add_cell(source="z = x")
    folder = cl.add_folder(name="F")
    order_before = [c.cell_id for c in cl._cells]
    cl.move_cell_up(folder.cell_id)
    assert [c.cell_id for c in cl._cells] == order_before


# ---------------------------------------------------------------------------
# move_cell_up / move_cell_down — basic reordering
# ---------------------------------------------------------------------------

def test_move_cell_up_swaps_with_above(qapp):
    """move_cell_up swaps the cell with the one directly above."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    c1 = cl.add_cell(source="a = 1")
    c2 = cl.add_cell(source="b = 2")
    c3 = cl.add_cell(source="c = 3")

    cl.move_cell_up(c3.cell_id)

    ids = [c.cell_id for c in cl._cells]
    assert ids == [c1.cell_id, c3.cell_id, c2.cell_id]


def test_move_cell_down_swaps_with_below(qapp):
    """move_cell_down swaps the cell with the one directly below."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    c1 = cl.add_cell(source="a = 1")
    c2 = cl.add_cell(source="b = 2")
    c3 = cl.add_cell(source="c = 3")

    cl.move_cell_down(c1.cell_id)

    ids = [c.cell_id for c in cl._cells]
    assert ids == [c2.cell_id, c1.cell_id, c3.cell_id]


# ---------------------------------------------------------------------------
# move_cell_up — folder boundary: first member exits folder when moved up
# ---------------------------------------------------------------------------

def test_move_up_first_member_exits_folder(qapp):
    """move_cell_up on the first folder member moves it above the folder header."""
    cl = CellListWidget(on_cell_result=lambda *a: None, grid=make_grid(GridConfig(n=32)))
    folder = cl.add_folder(name="F")
    folder_id = folder.cell_id
    member = cl.add_cell(source="z = x")
    member_id = member.cell_id
    cl._assign_folder(member, folder_id)

    cl.move_cell_up(member_id)

    ids = [c.cell_id for c in cl._cells]
    assert ids.index(member_id) < ids.index(folder_id)
    assert cl._cell_folder.get(member_id) is None


# ---------------------------------------------------------------------------
# Cmd+Up / Cmd+Down key events fire move_up_requested / move_down_requested
# ---------------------------------------------------------------------------

def test_cell_text_edit_emits_move_up_signal(qapp):
    from PyQt6.QtCore import Qt, QEvent
    from PyQt6.QtGui import QKeyEvent

    cell = CellWidget()
    received = []
    cell.move_up_requested.connect(lambda cid: received.append(cid))

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    cell._text_edit.keyPressEvent(event)
    assert received == [cell.cell_id]


def test_cell_text_edit_emits_move_down_signal(qapp):
    from PyQt6.QtCore import Qt, QEvent
    from PyQt6.QtGui import QKeyEvent

    cell = CellWidget()
    received = []
    cell.move_down_requested.connect(lambda cid: received.append(cid))

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    cell._text_edit.keyPressEvent(event)
    assert received == [cell.cell_id]


