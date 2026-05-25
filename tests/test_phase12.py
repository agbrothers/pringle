"""
Phase 12 tests: polish and QoL features.

Tests validate:
- StylePopoverWidget: emits style_changed with correct hex/opacity/linewidth
- Empty state placeholder: visible when no cells, hidden when cells present
- FolderCellWidget: toggle collapses/expands, rename, CellWidget interface
- Undo: add cell then undo removes it; remove cell then undo restores it
- Redo: undo then redo re-adds the cell
- Copy/paste: paste_cell adds a new cell from clipboard
- Timing: last_eval_ms is set after _rebuild_namespace
- Session round-trip: folder cell serialized and restored
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.grid import GridConfig, make_grid


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(n=16))


def _noop_result(cid, result, style):
    pass


@pytest.fixture
def cell_list(qapp, grid):
    from pringle.cell_list import CellListWidget
    return CellListWidget(on_cell_result=_noop_result, grid=grid)


# ---------------------------------------------------------------------------
# StylePopoverWidget
# ---------------------------------------------------------------------------

class TestStylePopoverWidget:
    def test_creates_with_style(self, qapp):
        from pringle.style import CellStyle
        from pringle.style_popover import StylePopoverWidget
        style = CellStyle(color=(0.2, 0.4, 0.8, 1.0), opacity=0.8, line_width=1.0)
        w = StylePopoverWidget(style)
        assert w._hex_edit.text() == "#3366cc"
        assert w._opacity_spin.value() == pytest.approx(0.8)
        assert w._lw_spin.value() == pytest.approx(1.0)

    def test_hex_edit_emits_style_changed(self, qapp):
        from pringle.style import CellStyle
        from pringle.style_popover import StylePopoverWidget
        style = CellStyle(color=(0.0, 0.0, 0.0, 1.0))
        w = StylePopoverWidget(style)
        received = []
        w.style_changed.connect(received.append)
        w._hex_edit.setText("#ff0000")
        w._on_hex_edited("#ff0000")
        assert len(received) > 0
        assert received[-1].color[0] == pytest.approx(1.0, abs=0.01)
        assert received[-1].color[1] == pytest.approx(0.0, abs=0.01)

    def test_opacity_spin_emits_style_changed(self, qapp):
        from pringle.style import CellStyle
        from pringle.style_popover import StylePopoverWidget
        style = CellStyle()
        w = StylePopoverWidget(style)
        received = []
        w.style_changed.connect(received.append)
        w._opacity_spin.setValue(0.5)
        assert any(s.opacity == pytest.approx(0.5) for s in received)

    def test_line_width_emits_style_changed(self, qapp):
        from pringle.style import CellStyle
        from pringle.style_popover import StylePopoverWidget
        style = CellStyle()
        w = StylePopoverWidget(style)
        received = []
        w.style_changed.connect(received.append)
        w._lw_spin.setValue(0.5)
        assert any(s.line_width == pytest.approx(0.5) for s in received)

    def test_invalid_hex_ignored(self, qapp):
        from pringle.style import CellStyle
        from pringle.style_popover import StylePopoverWidget
        style = CellStyle(color=(1.0, 0.0, 0.0, 1.0))
        w = StylePopoverWidget(style)
        received = []
        w.style_changed.connect(received.append)
        w._on_hex_edited("#xyz")
        assert len(received) == 0  # bad hex → no emit

    def test_current_style_reflects_edits(self, qapp):
        from pringle.style import CellStyle
        from pringle.style_popover import StylePopoverWidget
        style = CellStyle()
        w = StylePopoverWidget(style)
        w._opacity_spin.setValue(0.3)
        assert w.current_style().opacity == pytest.approx(0.3)

    def test_does_not_mutate_original_style(self, qapp):
        from pringle.style import CellStyle
        from pringle.style_popover import StylePopoverWidget
        style = CellStyle(opacity=1.0)
        w = StylePopoverWidget(style)
        w._opacity_spin.setValue(0.2)
        assert style.opacity == pytest.approx(1.0)  # original unchanged


# ---------------------------------------------------------------------------
# Empty state placeholder
# ---------------------------------------------------------------------------

class TestEmptyStatePlaceholder:
    def test_placeholder_visible_when_empty(self, qapp, cell_list):
        assert not cell_list._placeholder.isHidden()

    def test_placeholder_hidden_when_cell_added(self, qapp, cell_list):
        cell_list.add_cell("z = x")
        assert cell_list._placeholder.isHidden()

    def test_placeholder_reappears_after_remove(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cell = cl.add_cell("z = y")
        assert cl._placeholder.isHidden()
        cl.remove_cell(cell.cell_id)
        assert not cl._placeholder.isHidden()


# ---------------------------------------------------------------------------
# FolderCellWidget
# ---------------------------------------------------------------------------

class TestFolderCellWidget:
    def test_creates_with_name(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget(name="Section A")
        assert f.name == "Section A"

    def test_not_collapsed_by_default(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget()
        assert not f.is_collapsed

    def test_toggle_collapses(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget()
        f.toggle()
        assert f.is_collapsed

    def test_toggle_twice_expands(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget()
        f.toggle()
        f.toggle()
        assert not f.is_collapsed

    def test_set_collapsed_hides_body(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget()
        f.set_collapsed(True)
        assert f._body.isHidden()

    def test_set_collapsed_false_shows_body(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget()
        f.set_collapsed(True)
        f.set_collapsed(False)
        assert not f._body.isHidden()

    def test_toggle_btn_text_changes(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget()
        assert f._toggle_btn.text() == "▼"
        f.toggle()
        assert f._toggle_btn.text() == "▶"

    def test_cell_widget_interface(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget()
        assert f.source() == ""
        assert f.is_visible_cell() is False
        f.set_error("x")    # should not raise
        f.set_warning("y")  # should not raise
        f.clear_diagnostics()
        f.focus()

    def test_has_cell_id(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget()
        assert len(f.cell_id) > 0

    def test_delete_signal(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget()
        received = []
        f.delete_requested.connect(received.append)
        f.delete_requested.emit(f.cell_id)
        assert f.cell_id in received

    def test_rename_via_commit(self, qapp):
        from pringle.folder_cell_widget import FolderCellWidget
        f = FolderCellWidget(name="Old")
        f._name_edit.setText("New")
        f._commit_rename()
        assert f.name == "New"
        assert f._name_label.text() == "NEW"


# ---------------------------------------------------------------------------
# Folder in CellListWidget
# ---------------------------------------------------------------------------

class TestCellListFolder:
    def test_add_folder(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        from pringle.folder_cell_widget import FolderCellWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        f = cl.add_folder("My Group")
        assert isinstance(f, FolderCellWidget)
        assert f in cl._cells

    def test_folder_not_evaluated(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        from pringle.folder_cell_widget import FolderCellWidget
        results = []
        cl = CellListWidget(
            on_cell_result=lambda cid, r, s: results.append(cid),
            grid=grid,
        )
        f = cl.add_folder("Group")
        # Folder should not produce a result
        assert f.cell_id not in results

    def test_folder_placeholder_hidden(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_folder("Group")
        assert cl._placeholder.isHidden()  # folder counts as a cell → placeholder hidden


# ---------------------------------------------------------------------------
# Undo / redo
# ---------------------------------------------------------------------------

class TestUndoRedo:
    def test_undo_removes_added_cell(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_cell("z = x")
        assert len(cl._cells) == 1
        cl.undo()
        assert len(cl._cells) == 0

    def test_undo_restores_removed_cell(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_cell("z = y")
        cell_id = cl._cells[0].cell_id
        cl.remove_cell(cell_id)
        assert len(cl._cells) == 0
        cl.undo()
        assert len(cl._cells) == 1

    def test_redo_after_undo(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_cell("z = 0")
        cl.undo()
        assert len(cl._cells) == 0
        cl.redo()
        assert len(cl._cells) == 1

    def test_redo_stack_cleared_on_new_action(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_cell("z = 1")
        cl.undo()
        cl.add_cell("z = 2")   # new action should clear redo
        assert len(cl._redo_history) == 0

    def test_undo_empty_stack_is_noop(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.undo()  # should not raise
        assert len(cl._cells) == 0

    def test_redo_empty_stack_is_noop(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.redo()  # should not raise

    def test_undo_preserves_source(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_cell("z = sin(x)")
        cl.undo()
        cl.redo()
        assert cl._cells[0].source() == "z = sin(x)"


# ---------------------------------------------------------------------------
# Copy / paste
# ---------------------------------------------------------------------------

class TestCopyPaste:
    def test_paste_adds_cell(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        QApplication.clipboard().setText("z = x * y")
        cl.paste_cell()
        assert len(cl._cells) == 1
        assert cl._cells[0].source() == "z = x * y"

    def test_paste_empty_clipboard_no_op(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        QApplication.clipboard().setText("")
        cl.paste_cell()
        assert len(cl._cells) == 0

    def test_paste_whitespace_clipboard_no_op(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        QApplication.clipboard().setText("   ")
        cl.paste_cell()
        assert len(cl._cells) == 0


# ---------------------------------------------------------------------------
# Evaluation timing
# ---------------------------------------------------------------------------

class TestEvalTiming:
    def test_last_eval_ms_set_after_rebuild(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_cell("z = sin(x) * cos(y)")
        assert cl.last_eval_ms >= 0.0

    def test_last_eval_ms_is_float(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl._rebuild_namespace()
        assert isinstance(cl.last_eval_ms, float)


# ---------------------------------------------------------------------------
# Session round-trip with folder
# ---------------------------------------------------------------------------

class TestFolderSessionRoundTrip:
    def test_folder_serializes(self, qapp, grid):
        from pringle.cell_list import CellListWidget
        from pringle.session import cell_to_dict
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        f = cl.add_folder("Test Group")
        d = cell_to_dict(f)
        assert d["type"] == "folder"
        assert d["name"] == "Test Group"
        assert "collapsed" in d

    def test_folder_round_trip(self, qapp, grid):
        import tempfile, os
        from pringle.cell_list import CellListWidget
        from pringle.session import save_session, load_session, restore_cell_list
        from pringle.folder_cell_widget import FolderCellWidget

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.add_folder("Section 1")
        cl.add_cell("z = x")

        with tempfile.NamedTemporaryFile(suffix=".pringle", delete=False) as f:
            path = f.name
        try:
            save_session(path, cl, grid.config)
            data = load_session(path)
            cl2 = CellListWidget(on_cell_result=_noop_result, grid=grid)
            restore_cell_list(cl2, data["cells"])
            folder_cells = [c for c in cl2._cells if isinstance(c, FolderCellWidget)]
            eq_cells = [c for c in cl2._cells if not isinstance(c, FolderCellWidget)]
            assert len(folder_cells) == 1
            assert folder_cells[0].name == "Section 1"
            assert len(eq_cells) == 1
            assert eq_cells[0].source() == "z = x"
        finally:
            os.unlink(path)

    def test_legacy_data_type_yaml_loads_as_equation_cell(self, qapp, grid):
        """Old YAML sessions with type: data are transparently migrated to equation cells."""
        import tempfile, os, yaml
        from pringle.cell_list import CellListWidget
        from pringle.cell_widget import CellWidget
        from pringle.session import load_session, restore_cell_list

        # Build a minimal YAML that uses the old type: data format
        session_dict = {
            "version": 1,
            "grid": {"x_min": -5.0, "x_max": 5.0, "y_min": -5.0, "y_max": 5.0,
                     "z_min": -5.0, "z_max": 5.0, "n": 16},
            "cells": [{
                "id": "legacy-data-001",
                "type": "data",
                "source": "path = zeros((10, 2))",
                "visible": True,
                "style": {"color": [0.22, 0.4, 0.88, 1.0], "opacity": 1.0,
                          "line_width": 0.05, "point_size": 0.1,
                          "scatter_render_mode": "circles",
                          "colormap": None, "colormap_reversed": False},
                "sub_cells": [
                    {"type": "initial_condition", "source": "path[0] = array([1.0, 0.0])"},
                    {"type": "recursion", "source": "path[n] = path[n-1] * 0.9"},
                ],
            }],
        }
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", delete=False, mode="w"
        ) as f:
            yaml.dump(session_dict, f)
            path = f.name
        try:
            cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
            restore_cell_list(cl, load_session(path)["cells"])
            assert len(cl._cells) == 1
            cell = cl._cells[0]
            assert isinstance(cell, CellWidget)
            assert cell.source() == "path = zeros((10, 2))"
            recursion_subs = [s for s in cell._sub_cells if s.sub_type() == "recursion"]
            ic_subs = [s for s in cell._sub_cells if s.sub_type() == "initial_condition"]
            assert len(recursion_subs) == 1
            assert recursion_subs[0].source() == "path[n] = path[n-1] * 0.9"
            assert len(ic_subs) == 1
        finally:
            os.unlink(path)

    def test_collapsed_folder_round_trip(self, qapp, grid):
        import tempfile, os
        from pringle.cell_list import CellListWidget
        from pringle.session import save_session, load_session, restore_cell_list
        from pringle.folder_cell_widget import FolderCellWidget

        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        f = cl.add_folder("Collapsed")
        f.set_collapsed(True)

        with tempfile.NamedTemporaryFile(suffix=".pringle", delete=False) as f_:
            path = f_.name
        try:
            save_session(path, cl, grid.config)
            data = load_session(path)
            cl2 = CellListWidget(on_cell_result=_noop_result, grid=grid)
            restore_cell_list(cl2, data["cells"])
            folder_cells = [c for c in cl2._cells if isinstance(c, FolderCellWidget)]
            assert folder_cells[0].is_collapsed
        finally:
            os.unlink(path)
