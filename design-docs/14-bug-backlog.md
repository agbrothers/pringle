# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.  
See [16-closed-bugs.md](16-closed-bugs.md) for resolved bugs.

---

### BUG-013 — Camera locks and crosshair drifts when panning and rotating simultaneously

**Status:** Open  
**Logged:** 2026-05-17

**Description:**  
Holding a WASD pan key while dragging the mouse to orbit causes two visible problems: (1) the camera view freezes in place — WASD movement appears to have no effect — and (2) the crosshair continues drifting across the scene independently of the camera. When the mouse button is released and a pan key is pressed again, the camera jumps to an unexpected position.

**Root cause:**  
Two update paths write `camera.local.position` without coordination:

- **WASD pan** (`_pan_target` in `renderer.py:305`): each `_tick` call reads `controller.target` and `camera.local.position`, adds a delta to both, and writes them back. This keeps the camera-to-target offset constant.

- **Mouse orbit** (`gfx.OrbitController`, registered via `register_events`): while a mouse button is held and the user drags, the controller receives mouse-move events and recomputes `camera.local.position` from its internally cached spherical coordinates (elevation, azimuth, distance from target) that were captured at drag start. Every mouse-move event overwrites `camera.local.position` with a value derived from that internal state.

When both are active simultaneously:
1. `_pan_target` shifts `controller.target` successfully (the controller does not cache the target internally during drag — it reads it fresh).
2. `_pan_target` also writes `camera.local.position`, but the next mouse-move event from the `OrbitController` immediately overwrites it using the stale spherical-coordinate cache. The camera appears frozen.
3. Because `controller.target` is being shifted by `_pan_target` each tick, the crosshair (drawn at `controller.target` every frame in `render()`) moves — but the camera does not follow, causing visual decoupling.
4. When the drag ends, the controller stops overwriting `camera.local.position`. The next keypress then applies movement relative to a `controller.target` that has already drifted by the accumulated WASD delta — producing a jump.

**Can rotate and pan simultaneously be achieved?**  
Not without modifying or replacing the `OrbitController`. Its spherical-coordinate cache is internal and inaccessible, so there is no way to inject a "shift the orbit origin mid-drag" operation without the controller immediately undoing it on the next mouse-move event. True simultaneous orbit+pan would require either subclassing `OrbitController` to expose its internal state or replacing it with a custom controller (larger refactor).

**Possible fixes, in order of complexity:**

- **Suppress WASD movement during mouse drag** (recommended short-term fix): Track mouse-button-held state by overriding `mousePressEvent` / `mouseReleaseEvent` on `PringleViewport` (the Qt canvas widget). In `_tick`, skip `_apply_movement` when a mouse button is held. This prevents both the camera lock (no conflicting writes) and the crosshair drift (target is not shifted during drag). WASD and orbit still work individually. The downside is no simultaneous pan+rotate, but the controls are at least predictable.

  ```python
  # PringleViewport
  def mousePressEvent(self, event):
      self._mouse_held = True
      super().mousePressEvent(event)

  def mouseReleaseEvent(self, event):
      self._mouse_held = False
      super().mouseReleaseEvent(event)

  def _tick(self):
      if self._held_keys and not self._mouse_held:
          self._apply_movement()
      self.request_draw()
  ```

- **Freeze crosshair only, don't fix drift** (cosmetic only): Skip the crosshair position update in `render()` when `_mouse_held` is True. The underlying target drift still occurs and the jump-on-release remains, but the visual decoupling is hidden. Not recommended on its own.

- **Full simultaneous pan+rotate** (larger refactor): Replace `gfx.OrbitController` with a custom controller that handles both mouse orbit and keyboard pan in a single unified update loop with no internal caching. This is the video-game-style approach and gives the best UX, but is a significant change to the navigation architecture.

---

### BUG-037 — Renderer test suite crashes with SIGABRT under Python 3.13 incremental GC

**Status:** Open  
**Logged:** 2026-05-22  
**Severity:** HIGH — all tests that instantiate `PringleRenderer` / wgpu are non-runnable in CI

**Affected test files:**
- `tests/test_phase1.py`
- `tests/test_phase2.py`
- `tests/test_phase3.py`
- `tests/test_phase4_5.py`
- `tests/test_phase10.py`
- `tests/test_phase11.py`

**Symptom:**  
Tests abort mid-run with `Fatal Python error: Aborted`. The crash occurs in the wgpu-native poller thread while the Python main thread is in a GC cycle:

```
Thread 0x... (most recent call first):
  ... wgpu/backends/wgpu_native/_poller.py line 101 in run  ← poller thread

Current thread 0x... (most recent call first):
  Garbage-collecting
  ... renderstate.py in __init__   ← main thread inside wgpu/pygfx
```

**Root cause:**  
Python 3.13 introduced incremental garbage collection. GC can fire at any instruction boundary, including inside `cffi`/wgpu C-extension calls. The wgpu-native poller thread holds resources that are also accessed by the main thread's GC cycle. The combination causes an internal abort in the native wgpu library (`wgpu_native`).

Confirmed pre-existing: `git stash` of all current changes → same crash on all 6 test files. The crash is in `wgpu` / `pygfx`, not in Pringle code.

**Workaround:**  
Run tests excluding renderer test files:
```
python -m pytest tests/ --ignore=tests/test_rendering.py \
  --ignore=tests/test_phase1.py --ignore=tests/test_phase2.py \
  --ignore=tests/test_phase3.py --ignore=tests/test_phase4_5.py \
  --ignore=tests/test_phase10.py --ignore=tests/test_phase11.py
```
157 tests pass cleanly.

**Fix directions:**
- Disable Python 3.13 incremental GC in tests via `gc.set_threshold(0)` or `gc.disable()` in a pytest plugin/conftest — may mask the crash but doesn't fix it
- Upgrade wgpu-py / pygfx — the issue may be fixed in a newer wgpu-native release
- Use Python 3.12 (no incremental GC) for CI until wgpu is fixed
- File upstream bug with wgpu-py

---
