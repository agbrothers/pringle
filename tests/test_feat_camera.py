"""
FEAT-159 tests: camera position/target object in the expression namespace.

Tests validate:
- camera.x = 5 causes camera_override to emit with correct values
- Writing all 6 camera fields round-trips correctly
- Read-only use of camera does NOT emit camera_override
- CameraState is initialised from the live camera position (via _camera_provider), not zeros
- get_camera_writes correctly identifies written fields and ignores reads
- get_camera_writes returns empty set without crashing on dunder access patterns
- 'camera' does not trigger an 'Undefined' warning when used in a cell
"""

import sys
import pytest

from PyQt6.QtWidgets import QApplication

from pringle.grid import GridConfig, make_grid
from pringle.ast_utils import get_camera_writes


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def grid():
    return make_grid(GridConfig(x_min=-3.0, x_max=3.0, y_min=-3.0, y_max=3.0,
                                z_min=-3.0, z_max=3.0, n=8))


def _noop_result(cid, result, style):
    pass


@pytest.fixture
def cell_list(qapp, grid):
    from pringle.cell_list import CellListWidget
    return CellListWidget(on_cell_result=_noop_result, grid=grid)


# ---------------------------------------------------------------------------
# get_camera_writes unit tests
# ---------------------------------------------------------------------------

class TestGetCameraWrites:
    def test_single_write(self):
        assert get_camera_writes("camera.x = 5.0") == {"x"}

    def test_multiple_writes(self):
        src = "camera.x = 1.0\ncamera.target_z = 2.0"
        assert get_camera_writes(src) == {"x", "target_z"}

    def test_all_six_fields(self):
        src = "\n".join([
            "camera.x = 1",
            "camera.y = 2",
            "camera.z = 3",
            "camera.target_x = 4",
            "camera.target_y = 5",
            "camera.target_z = 6",
        ])
        assert get_camera_writes(src) == {"x", "y", "z", "target_x", "target_y", "target_z"}

    def test_read_only_returns_empty(self):
        assert get_camera_writes("v = camera.x + 1") == set()

    def test_plain_camera_reference_returns_empty(self):
        assert get_camera_writes("v = camera.target_z") == set()

    def test_invalid_syntax_returns_empty(self):
        assert get_camera_writes("camera.x =") == set()

    def test_augmented_assign_not_included(self):
        # camera.x += 1 is AugAssign, not Assign — out of scope
        assert get_camera_writes("camera.x += 1") == set()


# ---------------------------------------------------------------------------
# camera_override signal — emission tests
# ---------------------------------------------------------------------------

class TestCameraOverrideSignal:
    def test_camera_write_emits_override(self, qapp, grid):
        """camera.x = 5 causes camera_override to fire with correct x."""
        from pringle.cell_list import CellListWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.camera_override.connect(lambda *a: emitted.append(a))

        cl.add_cell("camera.x = 5.0")

        assert len(emitted) == 1
        assert emitted[0][0] == pytest.approx(5.0)   # x
        # y, z, tx, ty, tz default to 0 (no provider set); roll defaults to 0
        assert emitted[0][1] == pytest.approx(0.0)
        assert emitted[0][2] == pytest.approx(0.0)
        assert emitted[0][6] == pytest.approx(0.0)   # roll

    def test_write_all_six_fields(self, qapp, grid):
        """A cell writing all six positional camera attributes emits them correctly (roll=0)."""
        from pringle.cell_list import CellListWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.camera_override.connect(lambda *a: emitted.append(a))

        src = "\n".join([
            "camera.x = 1.0",
            "camera.y = 2.0",
            "camera.z = 3.0",
            "camera.target_x = 4.0",
            "camera.target_y = 5.0",
            "camera.target_z = 6.0",
        ])
        cl.add_cell(src)

        assert len(emitted) == 1
        # Signal carries 7 values: x, y, z, tx, ty, tz, roll
        assert emitted[0][:6] == pytest.approx((1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
        assert emitted[0][6] == pytest.approx(0.0)   # roll

    def test_write_roll(self, qapp, grid):
        """camera.roll = 45 emits camera_override with roll=45."""
        from pringle.cell_list import CellListWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.camera_override.connect(lambda *a: emitted.append(a))

        cl.add_cell("camera.roll = 45.0")

        assert len(emitted) == 1
        assert emitted[0][6] == pytest.approx(45.0)

    def test_write_all_seven_fields(self, qapp, grid):
        """A cell writing all seven camera fields round-trips correctly."""
        from pringle.cell_list import CellListWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.camera_override.connect(lambda *a: emitted.append(a))

        src = "\n".join([
            "camera.x = 1.0",
            "camera.y = 2.0",
            "camera.z = 3.0",
            "camera.target_x = 4.0",
            "camera.target_y = 5.0",
            "camera.target_z = 6.0",
            "camera.roll = 30.0",
        ])
        cl.add_cell(src)

        assert len(emitted) == 1
        assert emitted[0] == pytest.approx((1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 30.0))

    def test_no_emission_when_camera_not_written(self, qapp, grid):
        """Read-only camera use must not emit camera_override."""
        from pringle.cell_list import CellListWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.camera_override.connect(lambda *a: emitted.append(a))

        cl.add_cell("v = camera.x + 1")

        assert emitted == []

    def test_no_undefined_warning_for_camera_read(self, qapp, grid):
        """A cell reading camera.x should not produce an 'Undefined' warning."""
        from pringle.cell_list import CellListWidget
        warnings_seen = []

        def capture(cid, result, style):
            if result.warning:
                warnings_seen.append(result.warning)

        cl = CellListWidget(on_cell_result=capture, grid=grid)
        cl.add_cell("v = camera.x + 1")

        assert not any("Undefined" in w for w in warnings_seen)

    def test_camera_initialized_from_provider(self, qapp, grid):
        """CameraState is initialised from _camera_provider, not hardcoded zeros."""
        from pringle.cell_list import CellListWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid)
        cl.camera_override.connect(lambda *a: emitted.append(a))

        # Simulate a live camera at a known position
        cl._camera_provider = lambda: (10.0, -5.0, 3.0, 1.0, 2.0, 0.0)

        # A cell that reads camera.z (no write) — provider values should be in namespace
        cl.add_cell("cam_z_val = camera.z")
        assert cl._shared_ns.get("cam_z_val") == pytest.approx(3.0)
        # No write → no emission
        assert emitted == []

    def test_slider_driven_camera_write(self, qapp, grid):
        """Slider 'r' connected via camera.x = r fires camera_override on value change."""
        from pringle.cell_list import CellListWidget
        from pringle.slider_widget import SliderWidget
        emitted = []
        cl = CellListWidget(on_cell_result=_noop_result, grid=grid, eval_threaded=False)
        cl.camera_override.connect(lambda *a: emitted.append(a))

        cl.add_cell("r = 1.0")       # becomes slider
        cl.add_cell("camera.x = r")

        assert len(emitted) >= 1
        assert emitted[-1][0] == pytest.approx(1.0)

        emitted.clear()
        slider = next(c for c in cl._cells if isinstance(c, SliderWidget) and c.name == "r")
        slider.set_value(8.0)

        assert len(emitted) >= 1
        assert emitted[-1][0] == pytest.approx(8.0)
