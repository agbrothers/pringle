"""
FEAT-158 tests: deferred (focus-out) evaluation for def-function cells.

Tests validate:
- A cell whose source starts with "def " enters def_mode.
- In def_mode, the debounce is NOT started on text change.
- A focus-out event fires _emit_changed (deferred eval) in def_mode.
- Removing the "def " prefix on an existing def_mode cell exits def_mode.
- lambda cells stay on the eager debounce path (intentional asymmetry).
- set_def_mode idempotency: calling it twice with the same flag is a no-op.
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.cell_widget import CellWidget
from pringle.grid import GridConfig, make_grid


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=8))


@pytest.fixture
def cell(qapp):
    return CellWidget()


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

def test_def_cell_enters_def_mode(cell):
    cell._text_edit.setPlainText("def f(x):\n    return x")
    assert cell.is_def_mode()


def test_non_def_cell_not_in_def_mode(cell):
    cell._text_edit.setPlainText("z = x + y")
    assert not cell.is_def_mode()


def test_lambda_cell_not_in_def_mode(cell):
    cell._text_edit.setPlainText("f = lambda x: x**2")
    assert not cell.is_def_mode()


def test_indented_def_cell_enters_def_mode(cell):
    # lstrip() check — leading whitespace should not prevent detection
    cell._text_edit.setPlainText("  def f(x):\n    return x")
    assert cell.is_def_mode()


# ---------------------------------------------------------------------------
# Debounce behaviour
# ---------------------------------------------------------------------------

def test_def_mode_does_not_start_debounce(cell):
    cell._text_edit.setPlainText("def f(x):\n    return x")
    assert cell.is_def_mode()
    assert not cell._debounce.isActive()


def test_eager_mode_starts_debounce_on_text_change(cell):
    cell._text_edit.setPlainText("z = x")
    assert not cell.is_def_mode()
    assert cell._debounce.isActive()
    cell._debounce.stop()


# ---------------------------------------------------------------------------
# Focus-out triggers deferred eval
# ---------------------------------------------------------------------------

def test_focus_out_emits_content_changed_in_def_mode(qapp, cell):
    cell._text_edit.setPlainText("def f(x):\n    return x * 2")
    assert cell.is_def_mode()

    fired = []
    cell.content_changed.connect(lambda cid: fired.append(cid))

    # Simulate focus-out from the text edit
    cell._text_edit.focus_lost.emit()

    assert fired == [cell.cell_id]


def test_focus_out_does_not_double_fire_in_eager_mode(qapp, cell):
    cell._text_edit.setPlainText("z = x")
    assert not cell.is_def_mode()

    fired = []
    cell.content_changed.connect(lambda cid: fired.append(cid))

    # Debounce fires content_changed via timeout; focus_lost should NOT also
    # connect _emit_changed in eager mode.  Emit focus_lost directly.
    cell._text_edit.focus_lost.emit()

    # focus_lost in eager mode only emits commit_requested, not content_changed
    assert fired == []


# ---------------------------------------------------------------------------
# Mode transition: def → non-def
# ---------------------------------------------------------------------------

def test_removing_def_prefix_exits_def_mode(cell):
    cell._text_edit.setPlainText("def f(x):\n    return x")
    assert cell.is_def_mode()

    # Replace with a non-def expression
    cell._text_edit.setPlainText("z = x")
    assert not cell.is_def_mode()


def test_def_mode_debounce_cancelled_on_enter(cell):
    """Any in-flight debounce is cancelled when def_mode is entered."""
    cell._text_edit.setPlainText("z = x")
    assert cell._debounce.isActive()

    cell._text_edit.setPlainText("def f(x):\n    return x")
    assert cell.is_def_mode()
    assert not cell._debounce.isActive()


# ---------------------------------------------------------------------------
# set_def_mode idempotency
# ---------------------------------------------------------------------------

def test_set_def_mode_idempotent_true(cell):
    cell.set_def_mode(True)
    cell.set_def_mode(True)  # should not raise or double-connect
    assert cell.is_def_mode()
    # Verify focus_lost fires _emit_changed exactly once
    fired = []
    cell.content_changed.connect(lambda cid: fired.append(cid))
    cell._text_edit.focus_lost.emit()
    assert len(fired) == 1
    cell.set_def_mode(False)


def test_set_def_mode_idempotent_false(cell):
    cell.set_def_mode(False)  # already False by default
    assert not cell.is_def_mode()
