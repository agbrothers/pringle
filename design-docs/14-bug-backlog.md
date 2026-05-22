# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.  
See [16-closed-bugs.md](16-closed-bugs.md) for resolved bugs.

---

### BUG-026 — `error messaging the mach port for IMKCFRunLoopWakeUpReliable` printed on startup
**Status:** Open  
**Logged:** 2026-05-20  
**Severity:** Low — stderr noise only; no functional impact, no data loss

**Description:**  
On macOS, running the app prints the following to stderr/terminal shortly after launch:

```
2026-05-20 22:30:05.423 python3[70697:7248220] error messaging the mach port for IMKCFRunLoopWakeUpReliable
```

The message appears once per session (occasionally multiple times if input focus changes rapidly at startup) and does not affect app behavior. It cannot be suppressed via Python logging configuration since it is emitted by a macOS system framework at the C level.

**Root cause — macOS Input Method Kit (IMK) and Qt's event loop:**  
`IMKCFRunLoopWakeUpReliable` is an Apple Input Method Kit (IMK) internal: it attempts to wake the main thread's `CFRunLoop` when the system input method daemon (e.g., the Chinese/Japanese input method server, or the universal text input layer) wants to notify the focused text widget. The message fires when the IMK framework cannot deliver this notification — because the `CFRunLoop` is either not yet running, has already stopped, or is being driven by a foreign event loop (Qt's own event loop, not Cocoa's `NSRunLoop`).

PyQt6 uses Qt's native event loop integration (`QEventDispatcherMac`) which does pump `CFRunLoop` but with subtly different timing from a pure Cocoa app. The mismatch window during early startup — between the point where the first `QLineEdit` or `QPlainTextEdit` gains focus and the point where the Qt–Cocoa event loop integration is fully established — is when the IMK message fires.

The message is generated inside `IMKInputSession` (a private Apple framework) and there is no public API to suppress or disable it. It is seen across many PyQt5/PyQt6 and PySide6 applications on macOS and is widely regarded as a non-actionable Apple framework bug.

**Why it is not `BUG-021` (the font warning):**  
BUG-021 is a Qt font alias scan triggered by `font-family: monospace` in stylesheets (174ms, fixed by using explicit font families). This message is unrelated — it comes from the macOS system input method layer, not from Qt's font subsystem.

**Possible mitigations:**

- **Defer first focus** (may reduce frequency): In `app.py closeEvent` or the end of `__init__`, avoid giving any text widget focus during initial layout construction — call `self.setFocus()` or `clearFocus()` on the main window before the event loop starts. This may reduce the window during which IMK tries to ping a not-yet-ready `CFRunLoop`. Not guaranteed to eliminate the message.

- **Redirect stderr at process level** (suppresses all such messages): Wrap the process entry point to redirect file descriptor 2 before Qt initializes:
  ```python
  import os, sys
  if sys.platform == "darwin":
      devnull = os.open(os.devnull, os.O_WRONLY)
      os.dup2(devnull, 2)   # redirect stderr → /dev/null for C-level messages
      os.close(devnull)
  ```
  This silences the IMK message but also suppresses any other C-level stderr output (including genuine errors from wgpu-native or the GPU driver). Not recommended without a mechanism to re-enable stderr for debugging.

- **Accept as known noise** (recommended for now): The message is cosmetically annoying but carries no information about app correctness. Document it here as a known macOS PyQt6 quirk and leave it unfixed until it is confirmed to affect real users or until Apple or Qt resolves the underlying IMK–CFRunLoop timing issue upstream.

**Platform:** macOS only. Not reproducible on Linux or Windows.

---

---


---


### BUG-014 — `RuntimeError: CallerHelper has been deleted` on app close
**Status:** Open  
**Logged:** 2026-05-18  
**Severity:** Low — app has already exited cleanly; error is printed to stderr only, no data loss

**Description:**  
Closing the application after a normal session (save → close) sometimes prints a `RuntimeError` traceback to stderr:

```
Exception ignored from cffi callback <function GPUBuffer.map_async.<locals>.buffer_map_callback ...>
...
RuntimeError: wrapped C/C++ object of type CallerHelper has been deleted
```

The error appears to be reproducible after toggling visibility controls (axes, crosshair) before closing, though the toggle operations themselves are likely incidental — any close after a rendered frame can trigger it (see root cause below).

**Full trace:**
```
Exception ignored from cffi callback GPUBuffer.map_async.<locals>.buffer_map_callback:
  wgpu/backends/wgpu_native/_api.py — buffer_map_callback
    promise._wgpu_set_input(status)
  wgpu/_async.py — _wgpu_set_input / _set_input / _set_pending_resolved
    self._call_soon_threadsafe(self._resolve_callback)
  rendercanvas/core/loop.py — call_soon_threadsafe
    self._rc_call_soon_threadsafe(wrapper)
  rendercanvas/qt.py — _rc_call_soon_threadsafe
    self._caller.call.emit(callback)
RuntimeError: wrapped C/C++ object of type CallerHelper has been deleted
```

**Root cause — shutdown ordering race between Qt object teardown and a pending GPU async callback:**

rendercanvas uses a small Qt helper object (`CallerHelper`, `rendercanvas/qt.py:192`) to safely marshal callbacks from the GPU driver thread back to the Qt main thread. It works by emitting a Qt signal: `self._caller.call.emit(callback)`.

The render pipeline initiates an async GPU buffer read (`map_async("READ_NOSYNC")`) every frame as part of texture presentation (`rendercanvas/contexts/wgpucontext.py:389`). This operation is asynchronous — the GPU driver calls back when it's done, from a background thread.

When the app closes:
1. Qt's `aboutToQuit` fires → rendercanvas `QtLoop.stop(force=True)` is called, stopping the event loop.
2. Qt proceeds to destroy all `QObject`s, including `CallerHelper`.
3. The pending `map_async` GPU callback from the last rendered frame fires from the wgpu-native background thread.
4. The callback chain reaches `self._caller.call.emit(callback)` — but `_caller` (a `CallerHelper` `QObject`) has already been deleted by Qt.
5. Shiboken (PyQt6's C++ binding layer) raises `RuntimeError: wrapped C/C++ object of type CallerHelper has been deleted`.

The toggle operations before closing are **not the cause** — they just happen to be what the user did before closing. Any close sequence following a render will have this pending callback in flight.

**Why it's "Exception ignored":** The error originates in a cffi callback registered with the wgpu-native C library. Python can't propagate exceptions out of cffi callbacks, so it prints the traceback and continues — hence "Exception ignored." The app has already exited cleanly by this point.

**Possible fixes:**

- **Flush pending GPU work in `closeEvent`** (simplest workaround, `app.py`): Override `closeEvent` on `PringleWindow` to call `QApplication.processEvents()` before the default close, giving any queued callbacks a chance to fire while `CallerHelper` is still alive:
  ```python
  def closeEvent(self, event: QCloseEvent) -> None:
      QApplication.processEvents()   # drain pending GPU callbacks
      super().closeEvent(event)
  ```
  This is a best-effort workaround and may not be reliable under all timing conditions.

- **Upstream fix in rendercanvas**: The correct fix is for rendercanvas's `QtLoop` to either (a) cancel/discard the pending `map_async` awaitable when `stop(force=True)` is called, or (b) keep `CallerHelper` alive (via `QApplication.instance()` ownership) until all pending async callbacks have resolved. This warrants filing a bug report upstream against [rendercanvas](https://github.com/pygfx/rendercanvas).

- **Suppress the noise**: Wrap the cffi callback path with a `try/except RuntimeError` inside rendercanvas. Since the error is already "ignored," this would simply silence the stderr output. Again an upstream fix, not something we can do from application code.

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

