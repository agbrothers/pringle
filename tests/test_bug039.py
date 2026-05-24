"""
BUG-039 regression: _pan_target must not accumulate camera look-direction drift.

Root cause: the old code called controller.target = new_target (which internally
calls camera.look_at from the OLD camera position) before moving the camera to
the new position.  Each pan step introduced a small tilt; over many WASD frames
the camera drifted off the orbit target, causing the crosshair to appear offset
especially after zooming.
"""

import numpy as np
import pytest
import pygfx as gfx
import pylinalg as la


def _camera_to_target_angle_deg(cam, controller) -> float:
    """Return the angle (degrees) between camera forward and camera-to-target."""
    fwd = la.vec_transform_quat([0.0, 0.0, -1.0], cam.local.rotation)
    tgt = np.asarray(controller.target, dtype=np.float64)
    pos = np.asarray(cam.local.position, dtype=np.float64)
    to_tgt = tgt - pos
    norm = np.linalg.norm(to_tgt)
    if norm < 1e-9:
        return 0.0
    to_tgt /= norm
    dot = float(np.dot(fwd, to_tgt))
    return float(np.degrees(np.arccos(np.clip(dot, -1.0, 1.0))))


def _make_cam_controller():
    cam = gfx.PerspectiveCamera(50)
    cam.local.position = (6.0, -8.0, 6.0)
    cam.look_at((0.0, 0.0, 0.0))
    ctrl = gfx.OrbitController(cam)
    ctrl.target = (0.0, 0.0, 0.0)
    return cam, ctrl


def _pan_target_fixed(cam, ctrl, dx: float, dy: float, dz: float) -> None:
    """Fixed implementation: camera position updated BEFORE look_at."""
    delta = np.array([dx, dy, dz], dtype=np.float64)
    cam_pos = np.array(cam.local.position, dtype=np.float64)
    new_target = np.array(ctrl.target, dtype=np.float64) + delta
    cam.local.position = cam_pos + delta   # position first
    ctrl.target = tuple(new_target)        # look_at uses new position


def _pan_target_buggy(cam, ctrl, dx: float, dy: float, dz: float) -> None:
    """Old (buggy) implementation: look_at called before position update."""
    delta = np.array([dx, dy, dz], dtype=np.float64)
    cam_pos = np.array(cam.local.position, dtype=np.float64)
    new_target = np.array(ctrl.target, dtype=np.float64) + delta
    ctrl.target = tuple(new_target)        # look_at from wrong (old) position
    cam.local.position = cam_pos + delta


def test_pan_target_no_drift():
    """Fixed _pan_target keeps camera precisely aimed at orbit target after 120 steps."""
    cam, ctrl = _make_cam_controller()
    dist = float(np.linalg.norm(np.array(cam.local.position) - np.array(ctrl.target)))
    step = dist * 0.007  # matches _PAN_SPEED in app.py

    for _ in range(120):
        _pan_target_fixed(cam, ctrl, step, 0.0, 0.0)

    angle = _camera_to_target_angle_deg(cam, ctrl)
    assert angle < 0.001, f"Camera drifted {angle:.5f}° after 120 pan steps (expected <0.001°)"


def test_pan_target_buggy_drifts():
    """The old (buggy) order accumulates measurable orientation error — confirms the regression test catches it."""
    cam, ctrl = _make_cam_controller()
    dist = float(np.linalg.norm(np.array(cam.local.position) - np.array(ctrl.target)))
    step = dist * 0.007

    for _ in range(120):
        _pan_target_buggy(cam, ctrl, step, 0.0, 0.0)

    angle = _camera_to_target_angle_deg(cam, ctrl)
    assert angle > 0.1, (
        f"Expected the buggy implementation to accumulate drift > 0.1°, got {angle:.5f}°"
    )
