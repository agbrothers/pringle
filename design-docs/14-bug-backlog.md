# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.  
See [16-closed-bugs.md](16-closed-bugs.md) for resolved bugs.

---

### BUG-043 — Camera/orbit target drifts off-screen during fast circular mouse dragging

**Status:** Open  
**Logged:** 2026-05-23  
**Severity:** MEDIUM — reproducible with deliberate input; recovers via double-click reset

**Symptoms:**  
When the user drags the mouse in fast clockwise + counterclockwise orbits (or circles), the scene gradually drifts away from the origin. After several cycles the scene moves off-screen. The orbit target crosshair visibly separates from the scene center. Double-clicking the viewport (recenter) recovers.

**Reproduction steps:**
1. Open any session with a visible surface.
2. Left-click-drag clockwise for ~2 full rotations (fast).
3. Left-click-drag counterclockwise for ~2 full rotations (fast).
4. Repeat 3–4 times.
5. Observe: the scene drifts progressively off-center.

**Root cause analysis:**

The `_IncrementalOrbitHandler` (`renderer.py:699`) calls `self._controller.rotate((dx * 0.005, dy * 0.005), rect)` with per-frame pixel deltas. This routes into `OrbitController._update_rotate()` (pygfx), which computes the new camera position using two sequential quaternion operations:

```python
# Step 1: rotate camera-to-target vector by azimuth
pos1_to_target_rotated = la.vec_transform_quat(pos1_to_target, r_azimuth)

# Step 2: rotate result by elevation, around the camera's pre-azimuth right vector
right = la.vec_transform_quat((1, 0, 0), rot1)          # ← uses original rotation
r_elevation_world = la.quat_from_axis_angle(right, -delta_elevation)
pos1_to_target_final = la.vec_transform_quat(pos1_to_target_rotated, r_elevation_world)

pos2 = target_pos - pos1_to_target_final  # new camera position
```

Two drift mechanisms compound here:

1. **Axis mismatch in combined az+el moves.** The elevation rotation uses `right` derived from `rot1` (the camera's rotation *before* the azimuth step is applied). When both `dx` and `dy` are non-zero in the same call (diagonal mouse movement), the azimuth step rotates `pos1_to_target` but the elevation rotation axis is still the pre-azimuth right vector — a slightly wrong axis. For any single small step the error is negligible, but rapid circular dragging applies many such steps per second, and the resulting rotation is not exactly the inverse of the preceding one. A full CW circle does not compose back to the identity, leaving a small residual shift in camera position each time.

2. **Quaternion normalization drift.** Repeated `quat_mul` calls in `_update_rotate` accumulate floating-point error in `rot2`. A quaternion representing a rotation must be unit-length; accumulated error causes its length to drift. When `rot2` is used as `rot1` in the next call, the `right = vec_transform_quat((1, 0, 0), rot1)` vector is no longer unit-length, which means `quat_from_axis_angle(right, angle)` receives a non-unit axis. This corrupts the elevation rotation subtly but persistently. Over hundreds of fast-drag events, the camera's distance from the target grows or shrinks, and `pos2 = target_pos - pos1_to_target_final` places the camera at the wrong radius.

The combined effect of (1) and (2) is a net camera position error per circular orbit that accumulates without bound.

**Why the standard handler doesn't show this:**  
`OrbitController.register_events()` (pygfx's stock handler) snapshots the camera state at `pointer_down` and recomputes the full rotation from that snapshot on each `pointer_move`. It never accumulates incremental quaternion operations — each move recalculates from a known-good starting quaternion. Pringle's incremental handler was introduced to allow simultaneous WASD+mouse (BUG-013), but sacrifices this reset-each-frame property.

**Fix directions:**

**Option A — Re-normalize the camera quaternion periodically (low effort):**  
After each `rotate()` call in `_handle`, read back `camera.local.rotation`, normalize the quaternion, and write it back. This corrects drift (2) and does not touch the azimuth/elevation axis-mismatch problem, but the axis-mismatch error per call is so small (~1e-6 rad) that it is unlikely to produce visible drift on its own.

```python
# in _IncrementalOrbitHandler._handle, after controller.rotate(...):
cam = self._controller._cameras[0] if self._controller._cameras else None
if cam is not None:
    q = cam.local.rotation
    length = (q[0]**2 + q[1]**2 + q[2]**2 + q[3]**2) ** 0.5
    if abs(length - 1.0) > 1e-6:
        cam.local.rotation = (q[0]/length, q[1]/length, q[2]/length, q[3]/length)
```

**Option B — Periodically re-anchor camera state from spherical coordinates (more robust):**  
Track `(azimuth, elevation, distance)` in `_IncrementalOrbitHandler` directly. On each drag event, accumulate `azimuth += dx * sensitivity` and `elevation += dy * sensitivity`. Every N frames (or every `pointer_up`), recompute the camera's exact position from `(azimuth, elevation, distance, target)` in closed form, replacing the accumulated quaternion state with a freshly computed quaternion. This is immune to both drift mechanisms. Cost: requires knowing or replicating the controller's spherical-to-Cartesian formula, or calling a `look_at` rebuild.

**Option C — Upstream fix:**  
File a bug with pygfx: `OrbitController._update_rotate` should normalize the quaternion after each update and use the post-azimuth `right` vector for the elevation step. This would fix both drift mechanisms at the source, with no Pringle-side workaround needed. Option A is a reasonable local mitigation to apply while waiting for an upstream fix.

**Recommended path:** Apply Option A immediately (low risk, one-liner), then file upstream. If drift persists after Option A, implement Option B.

**Tests to add:**
- After 100 consecutive `rotate((0.1, 0.1), rect)` calls, camera-to-target distance is within 0.01% of its initial value.
- After 360 × `rotate((dx, 0), rect)` calls summing to a full azimuth circle, camera position is within 1e-4 of the starting position.
- Camera rotation quaternion length remains within 1e-5 of 1.0 after 1000 rapid rotate calls.

---
