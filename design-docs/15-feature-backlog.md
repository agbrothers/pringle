# Pringle — Feature Backlog

Desired features and enhancements are logged here as they are identified. Each entry includes a description, motivation, and implementation notes or open questions where known.

See [14-bug-backlog.md](14-bug-backlog.md) for the bug backlog.  
See [17-closed-features.md](17-closed-features.md) for implemented features.

---

### FEAT-040 — Camera-relative WASD panning
**Status:** Closed (implemented 2026-05-21)  
**Logged:** 2026-05-20

**Description:**  
Currently WASD pan keys move the orbit target in fixed world-space axes: W always shifts in +Y, D always in +X, regardless of where the camera is pointing. This means the apparent "forward" direction depends on the current camera azimuth — unintuitive when the camera is rotated 90° or more from its default orientation.

Change WASD to move the target in the camera's horizontal reference frame: W forward (toward the target's ground projection), S backward, A left, D right. Space and Shift continue to move in world +Z and −Z respectively — they are not rotated. This keeps planar panning strictly in-plane.

**User's intuition — confirmed correct:**  
The transform is: compute the normalized horizontal component of the camera-to-target vector, use it as the "forward" basis, derive "right" by rotating forward 90° clockwise in XY, then express each WASD direction in that basis. Space/Shift have zero XY component in `_PAN_KEYS` so they are unaffected automatically.

**Implementation — `_apply_movement` (`app.py:105`):**

The existing `_PAN_KEYS` dict stays unchanged — its values are now interpreted as directions in a "key-space" frame, not world space:

```python
_PAN_KEYS: dict[int, tuple[float, float, float]] = {
    Qt.Key.Key_W:     ( 0,  1,  0),   # key-space forward
    Qt.Key.Key_S:     ( 0, -1,  0),   # key-space backward
    Qt.Key.Key_A:     (-1,  0,  0),   # key-space left
    Qt.Key.Key_D:     ( 1,  0,  0),   # key-space right
    Qt.Key.Key_Space: ( 0,  0,  1),   # world +Z (unchanged)
    Qt.Key.Key_Shift: ( 0,  0, -1),   # world -Z (unchanged)
}
```

Replace `_apply_movement` with:

```python
def _apply_movement(self) -> None:
    import numpy as np
    cam = np.array(self._pr._camera.local.position, dtype=np.float64)
    tgt = np.array(self._pr._controller.target,     dtype=np.float64)
    dist = float(np.linalg.norm(cam - tgt))
    step = max(dist * _PAN_SPEED, 0.005)

    # Horizontal forward = camera-to-target projected onto XY, normalized.
    fwd_xy = tgt[:2] - cam[:2]
    mag = float(np.linalg.norm(fwd_xy))
    if mag > 1e-6:
        fx, fy = fwd_xy / mag
    else:
        fx, fy = 0.0, 1.0   # camera directly above target: fall back to world +Y

    for key in self._held_keys:
        if key not in _PAN_KEYS:
            continue
        dx_k, dy_k, dz = _PAN_KEYS[key]
        # Rotate key-space XY into world XY using the camera's horizontal basis.
        # Basis: forward = (fx, fy), right = rotate(fwd, -90°) = (fy, -fx).
        # (dx_k, dy_k) in key-space → (dx_k*fy + dy_k*fx,  -dx_k*fx + dy_k*fy) in world.
        # Verification:
        #   W (0,1) → (fx, fy)       ✓ forward
        #   S (0,-1) → (-fx, -fy)    ✓ backward
        #   D (1,0)  → (fy, -fx)     ✓ right (90° CW from fwd)
        #   A (-1,0) → (-fy, fx)     ✓ left
        #   Space/Shift: dx_k=dy_k=0 → (0,0), dz unchanged  ✓
        dx = dx_k * fy + dy_k * fx
        dy = -dx_k * fx + dy_k * fy
        self._pr._pan_target(dx * step, dy * step, dz * step)
```

The key-space-to-world rotation matrix is:
```
[  fy   fx ] [ dx_k ]   →  dx_world
[ -fx   fy ] [ dy_k ]   →  dy_world
```
This is a standard 2D rotation by azimuth angle θ where `(fx, fy) = (sin θ, cos θ)` (angle of the forward vector measured from +Y).

**No changes to `renderer.py` or `_pan_target`** — the interface is identical. `_pan_target` already receives world-space deltas.

**Degenerate case — looking straight down:**  
When the camera is directly above the target (orbit elevation ≈ 90°), `tgt[:2] - cam[:2]` has magnitude near zero. The fallback `(fx, fy) = (0.0, 1.0)` (world +Y as forward) is applied. The transition from near-degenerate to degenerate is continuous: as the camera approaches overhead, the XY component shrinks continuously to zero, so the fallback kicks in smoothly. No special UI is needed.

**Interaction with BUG-013 (WASD + mouse orbit conflict):**  
BUG-013 documents that simultaneous WASD + mouse drag causes the camera to lock. The recommended short-term fix for BUG-013 suppresses WASD during mouse drag (`_mouse_held` flag). This feature is orthogonal — it only changes the direction of the WASD pan, not when it fires. Both changes can be applied independently.

---

### FEAT-039 — Widen the expression panel by 50% by default
**Status:** Closed (implemented 2026-05-21)  
**Logged:** 2026-05-20

**Description:**  
The default width of the left expression panel is 320 px. Increase it to 480 px — 50% wider — so that typical expression strings, constraint sub-cells, and colormap controls are not clipped or wrapped at an awkward point. The panel is already draggable via a `QSplitter`, so users can resize further; this change only affects the initial layout when the app starts.

**Why:**  
At 320 px, moderately complex expressions (e.g. `z = sin(x) * cos(y) + a * exp(-x**2)`) approach the right edge of the text area after the color dot and action buttons consume ~70 px. Long constraint expressions in sub-cells (e.g. `x**2 + y**2 + z**2 <= 1 and z >= 0`) are truncated. The wider default reduces scrolling and wrapping noise for common use cases.

**Implementation — `app.py:262`:**  
Change the class-level constant from `320` to `480`:
```python
LEFT_PANEL_WIDTH = 480   # was 320
```
The splitter initialization at line 332 reads this constant directly:
```python
splitter.setSizes([self.LEFT_PANEL_WIDTH, self.DEFAULT_SIZE[0] - self.LEFT_PANEL_WIDTH])
```
At `DEFAULT_SIZE = (1400, 900)`, the viewport gets `1400 - 480 = 920 px` — still a comfortable 3D canvas at typical monitor sizes.

**Session persistence:** panel widths are not currently persisted to YAML, so existing saved sessions are unaffected. If session persistence for the splitter is added later (FEAT-025 area), `LEFT_PANEL_WIDTH` should become the default-only fallback, not the persisted value.

---

### FEAT-038 — Auto-expanding text input for constraint and recursion sub-cells
**Status:** Open  
**Logged:** 2026-05-20

**Description:**  
`ConstraintSubCell` (the sub-cell widget added with the "+sub" button on equation cells, used for constraint expressions, recursion rules, and initial conditions) uses a `QLineEdit` — a fixed-height, single-line widget. Long expressions in these cells (e.g. `x**2 + y**2 + z**2 <= 1 and z >= 0`, or `path[n] = path[n-1] + dt * v(path[n-1])`) are clipped at the right edge with no visual wrapping.

The goal is to replace the `QLineEdit` with a widget that wraps text and grows vertically as the content overflows a single line — matching the behavior of equation cells (`CellTextEdit`) and comment cells (`_CommentEdit`).

**Scope — what already works:**  
- Equation cells (`CellWidget`) already use `CellTextEdit`, a `QPlainTextEdit` subclass with line-wrap and auto-height (`_adjust_height` via `contentsChanged`). No change needed.
- Data cells (`DataCellWidget`) also use `CellTextEdit`. No change needed.
- Comment cells (`CommentCellWidget`) use `_CommentEdit`, a similar auto-expanding `QPlainTextEdit`. No change needed.
- Slider cells have no free-text expression field. Not applicable.
- Folder cell rename uses `QLineEdit` but is briefly visible only during rename (single short name). Low priority for this feature.

**Only `ConstraintSubCell` needs the change** (`cell_widget.py:116–153`).

**Implementation — `ConstraintSubCell._build_ui`:**  

Replace the `QLineEdit` with a `CellTextEdit` (which already exists in the same file):
```python
# Before:
self._edit = QLineEdit()
self._edit.setPlaceholderText(...)
self._edit.setStyleSheet(
    "QLineEdit { border: 1px dashed #666; border-radius: 3px; "
    "padding: 1px 4px; font-size: 12px; "
    "font-family: 'Menlo', 'Consolas', 'Courier New'; color: #ddd; }"
)
self._edit.textChanged.connect(self.content_changed)

# After:
self._edit = CellTextEdit(self)
self._edit.setPlaceholderText(...)
self._edit.setStyleSheet(
    "QPlainTextEdit { border: 1px dashed #666; border-radius: 3px; "
    "padding: 1px 4px; font-size: 12px; color: #ddd; background: transparent; }"
)
self._edit.textChanged.connect(self.content_changed)
```

`CellTextEdit` already sets up `Menlo/Consolas/Courier New` via `QFont`, so the font-family style rule is not needed.

**`source()` method update:**  
```python
# Before:
def source(self) -> str:
    return self._edit.text()   # QLineEdit API

# After:
def source(self) -> str:
    return self._edit.toPlainText()   # QPlainTextEdit API
```

**`CellTextEdit` Enter key behavior — sub-cell conflict:**  
`CellTextEdit.keyPressEvent` intercepts `Enter` at end-of-text and emits `enter_at_end` (used by equation cells to advance to the next cell). In sub-cells, `Enter` should insert a newline (or be a no-op) rather than firing this signal, since sub-cells have no concept of "move to the next cell." Two options:

1. **Add an `allow_newline` flag to `CellTextEdit`:** When `True`, suppress the `enter_at_end` emit and let the base class handle `Enter` normally (inserting a newline). `ConstraintSubCell` passes `allow_newline=True`.
2. **Subclass `CellTextEdit` for sub-cells:** A `ConstraintTextEdit(CellTextEdit)` that overrides `keyPressEvent` to call `super().super()` for `Enter` (bypassing the `enter_at_end` logic). More surgical but adds a subclass.

Option 1 is simpler:
```python
class CellTextEdit(QPlainTextEdit):
    def __init__(self, parent=None, allow_newline: bool = False):
        super().__init__(parent)
        self._allow_newline = allow_newline
        ...

    def keyPressEvent(self, event):
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self._allow_newline and mod == Qt.KeyboardModifier.NoModifier:
                ...   # existing enter_at_end logic
            else:
                super().keyPressEvent(event)   # allow newline in sub-cells
            return
        ...
```
`ConstraintSubCell` then constructs `CellTextEdit(self, allow_newline=True)`.

**Backward compatibility — `backspace_on_empty`:**  
`CellTextEdit` also emits `backspace_on_empty` when Backspace is pressed in an empty field; this is connected in `CellWidget` to delete the cell. Sub-cells should not be deleted this way (they have their own `✕` button). The `backspace_on_empty` signal would be emitted but nothing is connected to it in `ConstraintSubCell`, so it silently no-ops. No action needed.

**Layout height:**  
`ConstraintSubCell` uses `QHBoxLayout` with `contentsMargins(28, 1, 6, 1)` — a 2 px total vertical margin. With `CellTextEdit`, height adjusts as text wraps. The containing `CellWidget` layout propagates this height change upward through the standard Qt geometry system. No explicit resize hook is needed.

---

### FEAT-037 — GPU-accelerated expression evaluation (design decision log)
**Status:** Open — decision pending  
**Logged:** 2026-05-20  
**Related:** PERF-002, PERF-003, PERF-004 in [18-performance-backlog.md](18-performance-backlog.md)

**Background:**  
The expression evaluation pipeline (numpy CPU → numpy arrays → wgpu GPU upload) has three distinct cost layers: the expression computation itself, the Python-loop geometry construction, and the GPU buffer upload. PERF-003/004 address the geometry loops. This entry documents the options for accelerating the computation layer and reducing the GPU upload cost, and records why each option was or was not selected.

**The core constraint: GPU-to-GPU transfer is not free.**  
Moving expression evaluation to a GPU-accelerated library (JAX, PyTorch, CuPy) does not automatically enable sharing data with wgpu. Each library exposes tensors backed by GPU memory (CUDA or Metal), but wgpu's buffer API accepts numpy arrays or raw bytes — not foreign GPU tensors. The practical path for all of these libraries is still `tensor.cpu().numpy()` → `gfx.Geometry` → wgpu upload. At n=128 the CPU roundtrip costs ~0.5ms; this is a real overhead but small compared to the compute savings.

True zero-copy GPU-to-GPU transfer would require either DLPack interop (not currently implemented in pygfx/wgpu-py) or writing compute shaders inside wgpu itself (see option G below).

---

**Option A — JAX**  
`jax.numpy` is nearly API-compatible with numpy. Supports JIT compilation, GPU via XLA (CUDA or Metal via `jax-metal`), and full autodiff via `jax.grad`.

*Advantages:* Near-identical API; autograd opens new mathematical capabilities (parameter-space gradients, implicit surface finding); JIT compilation can speed expression evaluation by 5–50×.

*Blockers for Pringle:*  
- **Immutability.** JAX arrays are immutable; in-place operations (`arr[n] = f(arr[n-1])`) silently fail or raise. The recurrence relation engine (`recurrence.py`) is built around mutable numpy arrays — rewriting it for `jax.lax.scan` would be a major redesign.  
- **Cross-platform uncertainty.** `jax-metal` (macOS) is an experimental backend with inconsistent coverage of JAX ops. Linux/Windows CUDA installs require matching driver versions.  
- **Dependency weight.** JAX adds ~500MB of compiled XLA binaries. Current pringle install is trivially lightweight.

*Verdict: Not recommended as primary backend. Immutability blocks recurrence.*

---

**Option B — PyTorch**  
Widely used GPU tensor library with MPS (Metal) and CUDA backends.

*Advantages:* Mature, widely supported, large ecosystem.

*Blockers for Pringle:*  
- **Immutability.** PyTorch tensors support in-place ops syntactically (`a[i] = x`) but these don't compose with autograd. Same recurrence problem as JAX.  
- **API divergence.** `torch.sum(x, dim=0)` vs `np.sum(x, axis=0)` — argument names differ; the namespace whitelist would need significant reworking.  
- **CUDA version fragmentation.** PyTorch ships different wheels per CUDA version; users must match their driver. This complexity is incompatible with `pip install pringle`.  
- **Size.** PyTorch CPU-only is ~250MB; GPU variant is ~1.5GB.

*Verdict: Not recommended. Worse than JAX on every relevant dimension for this use case.*

---

**Option C — CuPy**  
A near-exact numpy drop-in (`import cupy as np`) for CUDA GPUs. Minimal API changes — most expressions would work unmodified.

*Advantages:* Essentially zero expression-layer refactor; no immutability issue; recurrence engine works as-is; mutable arrays; identical numpy semantics.

*Blockers for Pringle:*  
- **CUDA-only.** CuPy has no Metal or CPU fallback. macOS users (the current development platform) get nothing. A numpy fallback could be made automatic, but this creates a two-code-path maintenance burden.  
- **CUDA dependency.** Same driver-matching problem as PyTorch.

*Verdict: The cleanest API story, but platform exclusion is a hard blocker for now. Worth revisiting if cross-platform GPU compute becomes a requirement and WGSL shaders are not yet ready.*

---

**Option D — Numba**  
JIT compiler for Python + numpy code. Can target CPU (LLVM) or CUDA GPU. Does **not** require changing the expression namespace at all — applies to the renderer's Python-loop bottlenecks rather than user expressions.

*Advantages:*  
- `@numba.njit` on `_clip_mesh_to_mask` (PERF-004, 170ms at n=128) would likely reduce it to ~1ms with zero changes to the public API or user-facing expression semantics.  
- No immutability issue — numba compiles standard Python with mutable numpy arrays.  
- Lightweight dependency; CPU-mode requires no GPU driver.  
- Could accelerate expression evaluation via `@numba.njit` on lambdas, though eval'd lambdas from `exec()` don't compose directly with numba's AOT compilation model.

*Verdict: **Best near-term option for geometry acceleration.** Does not address expression computation on GPU, but PERF-004 is the dominant bottleneck before expression compute matters. Investigate as part of PERF-004 fix.*

---

**Option E — MLX (Apple)**  
Apple's open-source ML framework. Metal-native, numpy-like API, runs on Apple Silicon GPU. Has autograd.

*Advantages:* Native Metal GPU; numpy-like; would achieve zero-copy with wgpu on macOS (both use Metal) if DLPack support were added to pygfx.

*Blockers:*  
- macOS/Apple Silicon only — not usable on Linux or Windows.  
- DLPack interop with wgpu not currently implemented.

*Verdict: Interesting for macOS-only optimization, but platform exclusion makes it unsuitable as a primary backend.*

---

**Option F — Taichi**  
A Python-embedded DSL that compiles to Metal, CUDA, Vulkan, OpenGL, or CPU. Designed for physics simulation and visualization.

*Advantages:* Truly cross-platform GPU (covers macOS, Linux, Windows); could in principle share Metal/Vulkan buffers with wgpu since both target the same backends; data-oriented programming model suits grid computations.

*Blockers:*  
- Not numpy-compatible — users write Taichi kernels, not numpy expressions. The expression namespace would need a complete redesign.  
- Large dependency; less mature than numpy/scipy ecosystem.

*Verdict: Interesting for the geometry layer (compute shaders for `_clip_mesh_to_mask`), less so for user-facing expressions.*

---

**Option G — WGSL compute shaders (native wgpu) — Recommended long-term path**  
Write the surface evaluation and geometry construction as compute shaders executing directly inside wgpu. Results live in `GPUBuffer` objects that feed the vertex shader with zero CPU involvement. This is the "v2 GLSL compile" path referenced in the architecture design docs.

*Advantages:*  
- True zero-copy: compute result → vertex buffer, no CPU roundtrip at all.  
- Cross-platform: wgpu targets Metal, Vulkan, DX12 — all major platforms.  
- No new dependencies: wgpu is already a dependency.  
- Eliminates both PERF-002 (GPU upload) and the expression compute cost in one architecture.

*Cost:*  
- Requires an expression → WGSL transpiler. The current `exec()`-based eval model cannot be used; a compilable subset of expressions must be defined.  
- User expressions would be restricted to what can be represented in WGSL (no arbitrary Python, no scipy calls).  
- Significant implementation effort — effectively a v2 eval engine.  
- Data cells and recurrence relations would remain on CPU/numpy regardless.

*Verdict: The correct long-term architecture. Should be designed as an optional fast path alongside the existing numpy eval engine rather than a replacement — so that arbitrary Python expressions remain supported for correctness and scipy/recurrence use cases, while simple grid expressions opt into the WGSL path for animation performance.*

---

**Summary table:**

| Option | Platform | API change | Recurrence | Dependency | Zero-copy GPU | Recommendation |
|--------|----------|-----------|------------|------------|--------------|----------------|
| JAX | CUDA + Metal (exp.) | Low | ✗ breaks | Heavy | No | Blocked by recurrence |
| PyTorch | CUDA + MPS | Medium | ✗ breaks | Very heavy | No | Not recommended |
| CuPy | CUDA only | Near-zero | ✓ works | Medium | No | Blocked by platform |
| **Numba** | **All (CPU+CUDA)** | **None** | **✓ works** | **Light** | **No** | **Best near-term** |
| MLX | macOS only | Low | ✓ works | Medium | Possible | Platform blocker |
| Taichi | All | High | ✓ works | Medium | Possible | Complex |
| **WGSL shaders** | **All** | **N/A (opt-in)** | **✓ unchanged** | **None** | **✓ Yes** | **Best long-term** |

**Recommended path:**  
1. **Now:** Fix PERF-004 (`_clip_mesh_to_mask`) with Numba `@njit` as a targeted optimization — no architecture change, no new user-facing API.  
2. **Later:** Design the WGSL compute shader path as an opt-in fast path for simple grid expressions, keeping numpy eval as the fallback for arbitrary Python and scipy/recurrence cells.

---

### FEAT-036 — Critical point markers on surfaces (toggle for animation performance)
**Status:** Open  
**Logged:** 2026-05-20

**Description:**  
Overlay small markers on a surface at every point where `∂z/∂x = 0` and `∂z/∂y = 0` simultaneously — the critical points (local minima, maxima, and saddle points). Markers are all the same neutral color; classification by type is intentionally omitted since the surface geometry makes type self-evident and extra colors increase visual clutter. The feature is **off by default** and must be explicitly toggled on because it requires sharing the normal computation path with the renderer.

**Motivation:**  
Visually locating fixed points of a parameterized surface (e.g. identifying how extrema move as a slider sweeps through values) is difficult by eye. Static markers make this immediate. The primary use case is parameter sweeps — watching markers migrate across the surface as `a` changes — which makes the toggle critical: users running animated sweeps should be able to disable the overlay to recover framerate.

**UI:**  
A checkbox in the style popover labeled "Critical points", stored as `CellStyle.show_critical_points: bool = False`. Visible for all surface-type cells. Checking it triggers an immediate re-render; unchecking removes the marker overlay with no recomputation.

**Gradient sharing — zero marginal cost for the `np.gradient` call:**

`_grid_normals` in `renderer.py` already computes `dz_dx` and `dz_dy` via `np.gradient` (lines 35–36) in order to build the Phong shading normals. These values are used internally and then discarded. Critical point detection needs exactly the same two arrays on the same grid.

A critical point (∂z/∂x = 0, ∂z/∂y = 0) corresponds to the surface normal pointing straight up — `n = (0, 0, 1)` — since the unnormalized normal is `(-∂z/∂x, -∂z/∂y, 1)`. The gradient information is therefore already encoded in the normal vectors: `dz_dx = -nx/nz`, `dz_dy = -ny/nz`. However, recovering it from the normalized float32 normals amplifies precision error for near-vertical faces, so the cleaner approach is to share the raw gradients directly.

**Required refactor of `_grid_normals`:** Extract gradient computation into a standalone helper, then pass the result to both the normal builder and critical point detection:

```python
def _grid_gradients(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (dz_dx, dz_dy) via central finite differences. Used by both
    _grid_normals and critical point detection — compute once, share."""
    return np.gradient(z, x[0, :], axis=1), np.gradient(z, y[:, 0], axis=0)

def _grid_normals(dz_dx: np.ndarray, dz_dy: np.ndarray) -> np.ndarray:
    """Accept pre-computed gradients; signature change from (x, y, z)."""
    nx = -dz_dx;  ny = -dz_dy;  nz = np.ones_like(dz_dx)
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    ...
```

`make_surface_mesh` calls `_grid_gradients` once, passes the result to both. When `show_critical_points=False`, the gradients are only used for normals — no extra work. When `True`, the same arrays are also passed to `_find_critical_points`. The `np.gradient` call is paid exactly once regardless.

**Important:** use the pre-clip gradients (before `_clip_mesh_to_mask` runs), since the clipped normals array grows with boundary midpoint vertices and can no longer be reshaped to `(rows, cols)`. The seam is between lines 194 and 198 of the current `make_surface_mesh`.

**Algorithm — detection:**

`dz_dx` and `dz_dy` are already available from `_grid_gradients` — no additional `np.gradient` call needed. Scan for cells where both gradient components have a sign change. For each 2×2 block `(i,j)`:

```python
# sign change in gx across the cell (either row)
sx = (gx[i, j] * gx[i, j+1] < 0) | (gx[i+1, j] * gx[i+1, j+1] < 0)
# sign change in gy across the cell (either column)
sy = (gy[i, j] * gy[i+1, j] < 0) | (gy[i, j+1] * gy[i+1, j+1] < 0)
candidates = np.where(sx & sy)   # fully vectorized; no Python loop
```

For a 128×128 grid this is ~16K boolean comparisons — sub-millisecond.

**Algorithm — refinement (no extra z evaluations):**

Refinement uses only already-computed gradient values at the four corners of each candidate cell. One Newton step with the local Hessian assembled from finite differences of `gx`/`gy`:

```python
for i, j in zip(*candidates):
    # gradient at cell center (bilinear interpolation of corners)
    g0 = np.array([
        (gx[i, j] + gx[i+1, j] + gx[i, j+1] + gx[i+1, j+1]) / 4,
        (gy[i, j] + gy[i+1, j] + gy[i, j+1] + gy[i+1, j+1]) / 4,
    ])
    # local Hessian from finite differences of the gradient arrays
    J = np.array([
        [(gx[i, j+1] - gx[i, j]) / dx,  (gx[i+1, j] - gx[i, j]) / dy],
        [(gy[i, j+1] - gy[i, j]) / dx,  (gy[i+1, j] - gy[i, j]) / dy],
    ])
    if abs(np.linalg.det(J)) > 1e-10:
        delta = np.linalg.solve(J, -g0)
        delta = np.clip(delta, -0.5, 0.5)   # stay within cell
        x_crit = x1d[j] + delta[0] * dx
        y_crit = y1d[i] + delta[1] * dy
    else:
        x_crit, y_crit = x1d[j] + dx/2, y1d[i] + dy/2   # fallback to midpoint
    z_crit = float(z_raw[i, j])   # nearest grid value (or bilinear interp)
    critical_pts.append((x_crit, y_crit, z_crit))
```

The Newton step uses only values already in `gx` and `gy` — zero additional `z` evaluations. The cost is one 2×2 linear solve per candidate. With K critical points (typically K ≪ N²), this adds negligible time.

**No classification:** The Hessian determinant and sign check (for min/max/saddle distinction) are intentionally skipped. All markers are rendered identically.

**Rendering:**  
Critical points are collected into an `(K, 3)` float32 array and passed to `make_scatter_mesh` with a fixed neutral style (light gray, small size). The scatter object is keyed as `cell_id + ":crits"` in `_objects`, so `remove_object(cell_id)` must also remove `cell_id + ":crits"`. When `show_critical_points=False`, the entry is absent entirely (not hidden — removed) so it imposes no render cost.

**Performance profile:**

| Component | Cost | Notes |
|---|---|---|
| `_grid_gradients` (`np.gradient`) | **0 ms marginal** | Already computed for Phong normals; shared via refactor |
| Vectorized sign-change scan | < 0.1 ms | Pure NumPy boolean ops |
| Newton refinement (K steps) | < 0.1 ms | Typically K < 20; 2×2 solve per candidate |
| Total marginal overhead | **< 0.2 ms at 128×128** | Essentially free on top of normal surface render |

The gradient computation was originally listed as ~0.5 ms, but this is eliminated by sharing `dz_dx`/`dz_dy` from `_grid_normals` (which already pays this cost unconditionally for Phong shading). The true marginal cost of enabling critical point detection is just the sign-change scan and refinement.

With `show_critical_points=False`, the gradient arrays are still computed (they are needed for Phong normals regardless), but the sign-change scan is skipped entirely.

**Integration in `_on_cell_result` (`app.py`):**  
After `make_surface_mesh` produces the surface mesh, and only when `style.show_critical_points` is True:

```python
crits = _find_critical_points(result.data, result.x, result.y,
                               z_raw=result.data_unmasked)
if len(crits) > 0:
    crit_mesh = make_scatter_mesh(crits, color=(0.85, 0.85, 0.85, 1.0),
                                  size=0.04)
    vp.add_object(cell_id + ":crits", crit_mesh)
else:
    vp.remove_object(cell_id + ":crits")
```

`_find_critical_points` is a standalone function in `renderer.py` taking `(z, x_grid, y_grid)` and returning an `(K, 3)` array. Keeping it separate makes it testable and lets the toggle short-circuit before calling it.

**Constraint interaction:**  
Use `z` (the NaN-masked data) for gradient computation so that masked regions (constraint sub-cells) produce NaN gradients. Cells adjacent to a NaN value will have unreliable gradient estimates via `np.gradient`'s edge handling — in practice this means a few spurious candidates near the constraint boundary. These are filtered out by checking that `z_crit` is not NaN.

---

### FEAT-035 — User-supplied variable as colormap data source ("colormap by")
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
Allow the user to specify any same-shaped array from the expression namespace as the data source that drives a colormap, instead of the built-in default (z-values for surfaces, parametric index for curves). The primary use case is gradient-magnitude coloring: define `grad_norm` in a cell, then pin the colormap of a surface to `grad_norm` to visually locate fixed points and track how they move as parameters change.

**UI:**  
Add an optional text-input row below the colormap swatch row in `StylePopoverWidget`, visible only when a colormap is selected:
```
Colormap:  [▒▒▒▒▒][▓▓▓▓▓][░░░░░][▒▒▒▒▒][▓▓▓▓▓] [⇄]
by: [_________________________]
```
The field has placeholder text `variable name…`. Typing a name and pressing Enter (or leaving the field) updates the style. Clearing the field reverts to default coloring. Selecting a colormap swatch while the field is empty keeps the default source; the field is independent of swatch selection so a user can switch colormaps while keeping the same data source.

**Implementation — `CellStyle` (`style.py`):**  
Add one field:
```python
colormap_expr: str | None = None   # variable name to drive colormap; None = default
```
Persisted to YAML as `colormap_expr`. Read back in `restore_cell_list` with fallback `None`.

**Implementation — `style_popover.py`:**  
After the `cmap_row` block, add a conditional row:
```python
self._cmap_expr_edit = QLineEdit()
self._cmap_expr_edit.setPlaceholderText("variable name…")
self._cmap_expr_edit.setText(self._style.colormap_expr or "")
self._cmap_expr_edit.setFixedWidth(130)
self._cmap_expr_edit.editingFinished.connect(self._on_cmap_expr_changed)
expr_row = QHBoxLayout()
expr_row.addWidget(QLabel("by:"))
expr_row.addWidget(self._cmap_expr_edit)
expr_row.addStretch()
layout.addLayout(expr_row)
```
The row is always present but could be hidden when no colormap is selected (style cleanup concern, not functional). `_on_cmap_expr_changed` updates `self._style.colormap_expr` to the stripped text (or `None` if empty) and emits `style_changed`.

**Implementation — `app.py` (`_on_cell_result`):**  
Resolve the variable name to an array from the shared namespace immediately before calling mesh builders:
```python
cmap_data: np.ndarray | None = None
if style.colormap and style.colormap_expr:
    raw = self._cell_list._shared_ns.get(style.colormap_expr.strip())
    if isinstance(raw, np.ndarray):
        cmap_data = raw.astype(np.float32)
    # if lookup fails or wrong type: cmap_data stays None → fallback to default
```
Pass `cmap_data` to each mesh builder as a new `colormap_data: np.ndarray | None = None` parameter.

**Implementation — `renderer.py` (mesh builders):**  
Add `colormap_data` parameter to `make_surface_mesh`, `make_line_mesh`, `make_scatter_mesh`. When present and shape-valid, use it as the scalar array for `_apply_colormap` instead of the built-in default:

*Surface:*
```python
if colormap is not None:
    if colormap_data is not None and colormap_data.size == z.size:
        color_vals = colormap_data.ravel()
    elif colormap_data is not None:
        # Shape mismatch: fall back, mark warning
        color_vals = positions[:, 2]
    else:
        color_vals = positions[:, 2]   # default: z-value
    colors = _apply_colormap(color_vals, colormap, colormap_reversed)
```
The shape check `colormap_data.size == z.size` ensures the array matches the N×M surface grid. After clipping, `positions` may have more vertices (boundary midpoints), so `colormap_data.ravel()` is indexed before clipping and matched to the original grid. The cleanest approach is: compute colors for all N×M grid positions using the custom data, then let the clip pass rearrange them in sync with vertices.  
This requires threading `colormap_data`-derived colors through the clip as a per-vertex attribute alongside positions/normals — a moderate refactor. An alternative is to map the custom data onto the clipped vertices by nearest-grid-index, which is simpler but approximate at boundaries.

*Curve / scatter:*
```python
if colormap is not None:
    if colormap_data is not None and len(colormap_data.ravel()) == len(pts):
        color_vals = colormap_data.ravel()
    else:
        color_vals = np.linspace(0.0, 1.0, len(pts), dtype=np.float32)
    colors = _apply_colormap(color_vals, colormap, colormap_reversed)
```

**Shape-mismatch handling:**  
When `colormap_data` is provided but has the wrong shape, fall back to default coloring silently. Optionally surface a warning via the cell's `set_warning` mechanism: since the warning must be set before the mesh builder is called (the builder has no access to the cell widget), the check and warning should happen in `_on_cell_result` before the builder call.

**Dependency tracking limitation:**  
If the surface cell's source does not reference `colormap_expr` (e.g., the cell is `z = f(x, y)` and `grad_norm` is defined in a separate cell), a change to `grad_norm`'s cell will trigger `_rebuild_namespace` and re-evaluate `grad_norm` — but the surface cell `z = f(x, y)` has no syntactic dependency on `grad_norm` and will not re-evaluate. The surface will therefore keep its old coloring until some other change forces a rebuild.

In the typical use case (gradient arrays derived from the same slider parameters that drive the surface), this is not a problem: changing `a` re-evaluates both `z = f(x, y, a)` and `grad_norm = g(x, y, a)`, and the surface rebuilds picking up the new `grad_norm`. The edge case only arises if `grad_norm` depends on variables the surface doesn't share.

**Session persistence (`session.py`):**  
`cell_to_dict` writes `colormap_expr` from `style.colormap_expr`. `restore_cell_list` reads it with `style_data.get("colormap_expr", None)`.

---

### FEAT-031 — Halve the crosshair arm length
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
The orbit-target crosshair arms are visually prominent and obscure nearby geometry. Reduce each arm to half its current length.

**Implementation:** `renderer.py:445` — change the multiplier from `0.025` to `0.0125`:
```python
arm = max(xx - xn, yx - yn, zx - zn) * 0.0125
```

---

### FEAT-030 — Camera inertia: orbit continues spinning after mouse release
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
When the user releases the mouse after rotating the viewport, the scene should continue spinning at the release velocity and gradually decelerate to a stop — matching the behavior in Desmos 3D. Slow deliberate releases produce a gentle glide; fast flicks produce a prolonged spin. Any new mouse-down immediately cancels the coast.

**Desmos reference:** see `01-desmos-3d-overview.md` — Camera Inertia section, updated 2026-05-18.

**Why pygfx's built-in `damping` is not sufficient:**  
`gfx.OrbitController` is constructed with `damping=4` (default). This parameter smooths the camera response *during* active drag (so fast pointer jerks don't cause instantaneous jumps). It does not produce any rotation after `pointerup` — once the mouse is released and the drag action ends, the controller stops updating the camera entirely. Post-release inertia requires a separate "coast" state that must be driven by the application's own render loop.

**Implementation approach:**

The coast state needs to live outside `OrbitController` since there is no hook for it inside pygfx. The natural place is `PringleViewport._tick()` (or the equivalent per-frame callback), which already drives WASD movement.

1. **Intercept pointer events from wgpu canvas.** The wgpu canvas (`rendercanvas`) delivers `pointer_up` and `pointer_move` events to registered handlers. Register a secondary handler (alongside the controller's handler) that:
   - On each `pointer_move` while the primary mouse button is held: records `(Δazimuth, Δelevation, timestamp)` into a fixed-length deque (e.g. capacity 10 samples, ~100 ms window). Δazimuth and Δelevation are computed the same way the `OrbitController` does: `dx / viewport_width * π` and `dy / viewport_height * π` (approximate; exact formula in `_orbit.py`).
   - On `pointer_up`: reads the deque, computes time-weighted average velocity `(ω_az, ω_el)` in rad/s, stores it as `_coast_velocity`. If the deque is empty or the release was stationary, sets velocity to zero (no coast).

2. **Coast loop in `_tick()`.** Each frame while `|_coast_velocity| > threshold`:
   ```python
   DECAY = 0.88          # fraction of velocity retained per second
   STOP_RAD_S = 0.005    # stop threshold

   dt = elapsed_since_last_tick()
   if _coast_velocity and magnitude(_coast_velocity) > STOP_RAD_S:
       daz, del_ = _coast_velocity[0] * dt, _coast_velocity[1] * dt
       controller.rotate(daz, del_)     # pygfx public API
       _coast_velocity = (
           _coast_velocity[0] * DECAY ** dt,
           _coast_velocity[1] * DECAY ** dt,
       )
   else:
       _coast_velocity = None
   ```
   `controller.rotate()` is the same method the OrbitController uses internally and is part of the public API.

3. **Cancel coast on new drag.** The `pointer_down` handler sets `_coast_velocity = None` before the OrbitController's handler takes over. This ensures the user always gets direct control immediately.

4. **Interaction with WASD pan (BUG-013 context).** The coast loop and the WASD loop both write to the camera via the controller. The existing BUG-013 notes that simultaneous WASD + mouse drag causes conflicts; coasting after release does not conflict with WASD (no mouse button is held), so this is a safe combination.

**Tuning parameters to expose:**  
- `DECAY` (0.0 = instant stop, 1.0 = never stops) — reasonable default ~0.88 per second  
- `STOP_RAD_S` threshold — default 0.005 rad/s  
- These can be hardcoded initially; a UI slider in the axis settings panel could expose them later if users want control.

---


### FEAT-026 — Drop shadow projected onto bottom plane of bounding box
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
Render a semi-transparent shadow of each plotted object projected straight down onto the `z_min` floor plane of the wireframe bounding box. The shadow would be a flat, dark silhouette that helps orient the user in 3D space and gives a sense of height above the floor.

**Performance cost: essentially zero.** A straight-down orthographic shadow is just geometry — copy each object's vertex positions, clamp all Z coordinates to `z_min`, and render with a semi-transparent dark material. This adds geometry to the normal render pass but requires no extra GPU passes, no depth textures, and no shadow maps.

**Why not use pygfx's built-in shadow maps?**  
pygfx does support `cast_shadow` / `receive_shadow` on world objects and `DirectionalLight`, and the shadow pipeline covers Mesh, Line, and Points. However, shadow maps add a full extra render pass per frame per casting light — overhead that is unwarranted here since a straight-down projection is mathematically exact with the simpler technique.

**Implementation:**  
For each cell object in `_objects`, maintain a corresponding "shadow" object: a copy of the geometry with all Z values flattened to `z_min + ε` (tiny offset to avoid Z-fighting with the wireframe floor edge), rendered with a `MeshBasicMaterial` / `LineMaterial` / `PointsMaterial` in near-black at ~30–40% opacity:

```python
def _make_shadow(obj: gfx.WorldObject, z_floor: float) -> gfx.WorldObject | None:
    geom = obj.geometry
    if geom is None or geom.positions is None:
        return None
    pos = np.array(geom.positions.data, dtype=np.float32).copy()
    pos[:, 2] = z_floor + 1e-3          # flatten + tiny Z offset
    shadow_geom = gfx.Geometry(positions=pos, indices=geom.indices)
    if isinstance(obj, gfx.Mesh):
        mat = gfx.MeshBasicMaterial(color=(0, 0, 0, 0.35), side="both")
        return gfx.Mesh(shadow_geom, mat)
    elif isinstance(obj, gfx.Line):
        mat = gfx.LineMaterial(color=(0, 0, 0, 0.35), thickness=obj.material.thickness)
        return gfx.Line(shadow_geom, mat)
    elif isinstance(obj, gfx.Points):
        mat = gfx.PointsMaterial(color=(0, 0, 0, 0.35), size=obj.material.size)
        return gfx.Points(shadow_geom, mat)
    return None
```

Shadow objects are tracked in a parallel `_shadow_objects: dict[str, gfx.WorldObject]` dict in `PringleRenderer`, added/removed alongside their source objects in `add_object` and `remove_object`. They are also hidden when the source object is hidden (`set_visible`).

**The `z_min` value needs to be kept in sync with the axis bounds.** When the user changes the Z min spinbox, all shadow objects should have their floor Z updated. This means either rebuilding shadow geometry on bounds change, or storing the floor plane as a uniform and doing the projection in a custom shader (more complex but avoids CPU geometry copies on every bounds change).

**Excluded from bounding box calculations:** Shadow objects must be excluded from `get_data_bounding_box` (FEAT-019) and `fit_camera` so they don't inflate the scene bounds or affect camera fitting.

**Toggle and opacity:** Add a "Shadow" checkbox to the axis/view settings panel alongside the existing Axes, Wireframe, and Crosshair toggles, with a companion opacity spinbox or slider (range 0.0–1.0, default ~0.35). The checkbox wires the same way as the other overlays — a `shadow_visibility_changed` signal on `ViewSettingsWidget` connected to a `set_shadow_visible` method on `PringleRenderer` that shows/hides all entries in `_shadow_objects`. The opacity control calls a `set_shadow_opacity` method that updates the alpha on each shadow material. Default visibility TBD (off by default seems reasonable given it adds visual noise for simple plots). Both values persist in the `view` YAML block introduced by FEAT-023.

**Style consideration:** Shadow color should adapt for light vs. dark backgrounds (FEAT-024) — near-black on white, near-white on dark.

---

### FEAT-025 — Save button and unsaved-changes indicator
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
Add a visible save button and/or an unsaved-changes indicator to the UI. The app already tracks `_modified` and keyboard shortcuts (`Cmd+S` / `Ctrl+S`) work, but there is no on-screen affordance communicating save state or providing a click target for users who don't know the shortcut.

**What's already in place (`app.py:324–335`):**  
- `_modified: bool` is set on every cell/slider change and cleared on save.
- `_update_title()` prepends `"* "` to the window title when modified — e.g. `"* pringle — rossler.yml"`.
- `Cmd+S` / `Ctrl+S` (save) and `Cmd+Shift+S` / `Ctrl+Shift+S` (save-as) shortcuts are registered.

**What's missing:**

1. **Native macOS close-button dot:** Qt provides `QMainWindow.setWindowModified(bool)` and a `[*]` placeholder in `setWindowTitle`. When used together, Qt automatically shows the native dot inside the red traffic-light close button on macOS (and an asterisk in the title on other platforms). The current code uses a manual `"* "` prefix instead, so the macOS dot never appears. Fix: replace the manual prefix with the standard Qt mechanism:
   ```python
   # _update_title in app.py
   self.setWindowTitle(f"pringle — {name}[*]")   # [*] is Qt's placeholder
   self.setWindowModified(self._modified)          # drives the dot on macOS
   ```

2. **On-screen save button / indicator:** The window title `*` is easy to miss. An explicit UI element (location and style TBD — to be discussed) would make the save state more prominent. Options to consider:
   - A small `●` dot or `Save` button in the top bar / toolbar area that is highlighted when `_modified` is True and grayed out when clean.
   - A floppy-disk icon button (`💾` or a custom SVG) that triggers `_on_save` on click.
   - A pill-shaped status label (e.g. `"Unsaved"` / `"Saved"`) styled similarly to how the cell status area works.
   - A thin colored border or highlight on the left panel header when unsaved (minimal footprint, no extra button).

**Cross-platform notes:**  
- **macOS:** native dot on the red close button via `setWindowModified` (free once the `[*]` fix above is applied). No extra work needed for the title bar — macOS renders `[*]` as a bullet `•` before the filename automatically.
- **Windows/Linux:** `setWindowModified` causes Qt to substitute `[*]` with `*` in the title. An explicit on-screen indicator matters more on these platforms since there's no native close-button equivalent.

**Open questions (to discuss before implementing):**  
- Where should the save button live? Top-left of the left panel? Inline in the menu/toolbar area? Inside the axis settings popup?
- Should it be icon-only, text-only, or icon+text?
- Should "Save" and "Save As…" both be surfaced, or just "Save"?

---

### FEAT-017 — Dark vs light mode toggle
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Add a toggle (checkbox or button) to switch the application between a dark and a light color scheme. Both the Qt UI panels and the 3D viewport background should update consistently.

**Implementation notes:**
- Qt side: apply a `QApplication.setStyleSheet(...)` swap. A minimal dark palette can be constructed from `QPalette` without a full third-party theme library.
- Viewport background: `renderer.background` (the wgpu canvas clear color) needs to change — currently hardcoded in `renderer.py`. Expose a `set_background_color` method and call it on toggle.
- Axis/bbox/crosshair line colors may need to invert or adjust for legibility against the new background.
- Persist the preference in the session YAML or a user config file so the chosen mode survives restarts.
- The toggle could live in the new Axis Settings popup (FEAT-012) or in a top-level View menu.

---

### FEAT-016 — Color defaults and color picker/slider in style popup
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Extend the existing per-cell style popover (`style_popover.py`) with a proper color picker and opacity slider, replacing the current color dot (which only cycles through a fixed palette). Also establish a global default color sequence so new cells get predictable, Desmos-like colors in order.

**Implementation notes:**
- Qt provides `QColorDialog` out of the box; it can be launched from a "Custom…" button inside the popover to let the user pick any RGBA color.
- Alternatively, embed a compact HSL/RGB slider widget directly in the popover (avoids opening a separate window).
- Opacity slider: a `QSlider` mapped to the alpha channel of the cell's RGBA color; the viewport material's `opacity` and `is_transparent` flag must be updated on change.
- Default sequence: define an ordered list of RGBA defaults (matching Desmos's palette or similar) in `style.py`; `CellListWidget` assigns the next unused color when a cell is created.
- The color dot in the cell row should update live as the picker changes.

---

### FEAT-015 — Application icon
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Add a custom icon for the application window and macOS Dock entry.

**Implementation notes:**
- Set via `QMainWindow.setWindowIcon(QIcon("path/to/icon.png"))` and `QApplication.setWindowIcon(...)` early in startup.
- macOS Dock icon additionally requires a `.icns` file referenced in the app bundle's `Info.plist` (relevant if packaging with PyInstaller or py2app).
- A simple `.png` (256×256 or 512×512) is sufficient for the window title bar on all platforms.

---

### FEAT-014 — Vector / arrow rendering (flow chains and explicit tail+head pairs)
**Status:** Open  
**Logged:** 2026-05-16  
**Updated:** 2026-05-20

**Description:**  
Render 3D arrows for two distinct use cases:

1. **Flow mode** — given an (N, 3) scatter array, draw N−1 arrows between consecutive pairs of points, visualizing directionality along a path or trajectory.
2. **Vector field mode** — given an (N, 6) array (columns 0–2 = tail, 3–5 = head), draw N independent arrows as an arbitrary vector field. An (N, 4) array is the 2D version: tail (x, y) and head (x, y) with z=0.

A third option — treating (N, 6) as position + direction vector rather than tail + head — is intentionally not included: it reduces to vector field mode by computing `head = tail + direction`, so no separate mode is needed.

---

**Arrow geometry — pygfx backend:**

pygfx has no built-in arrow primitive. The correct approach is a single combined unit-arrow mesh rendered via `gfx.InstancedMesh` — one GPU draw call for all N arrows. The unit arrow points along +Z from `z=0` (tail) to `z=1` (head):

```python
def _build_unit_arrow_geometry(shaft_r=0.03, head_r=0.09,
                                head_frac=0.25, segments=8):
    """Shaft cylinder + cone head, combined into one Geometry."""
    shaft_h = 1.0 - head_frac   # e.g. 0.75
    head_h  = head_frac         # e.g. 0.25

    # Shaft: cylinder centered at origin → shift so z ∈ [0, shaft_h]
    sg = gfx.cylinder_geometry(
        radius_bottom=shaft_r, radius_top=shaft_r,
        height=shaft_h, radial_segments=segments)
    sp = sg.positions.data.copy();  sp[:, 2] += shaft_h / 2
    sn = sg.normals.data.copy()

    # Head: cone (top radius=0) centered at origin → shift to z ∈ [shaft_h, 1]
    cg = gfx.cylinder_geometry(
        radius_bottom=head_r, radius_top=0.0,
        height=head_h, radial_segments=segments)
    cp = cg.positions.data.copy();  cp[:, 2] += shaft_h + head_h / 2
    cn = cg.normals.data.copy()

    positions = np.concatenate([sp, cp], axis=0)
    normals   = np.concatenate([sn, cn], axis=0)
    indices   = np.concatenate([sg.indices.data,
                                 cg.indices.data + len(sp)], axis=0)
    return gfx.Geometry(positions=positions, normals=normals, indices=indices)
```

This geometry is built once and cached (module-level singleton). Changing arrow count or direction does not require rebuilding it.

**Per-arrow transform matrix:**

Each arrow is placed by a 4×4 matrix that rotates the unit +Z arrow to the desired direction, scales it to the arrow length, and translates it to the tail position:

```python
def _arrow_matrix(tail, head):
    d = np.asarray(head, dtype=np.float64) - tail
    L = np.linalg.norm(d)
    if L < 1e-10:
        return None          # zero-length arrow — skip
    d_hat = d / L

    z = np.array([0.0, 0.0, 1.0])
    axis = np.cross(z, d_hat)
    s = np.linalg.norm(axis)
    c = float(np.dot(z, d_hat))

    if s < 1e-8:             # parallel or anti-parallel
        R = np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    else:
        axis /= s
        K = np.array([[ 0,       -axis[2],  axis[1]],
                       [ axis[2],  0,       -axis[0]],
                       [-axis[1],  axis[0],  0      ]])
        R = np.eye(3) + s * K + (1 - c) * (K @ K)   # Rodrigues

    # Scale: multiply the Z column by L so the unit arrow becomes length L
    M = np.eye(4, dtype=np.float32)
    M[:3, 0] = R[:, 0]
    M[:3, 1] = R[:, 1]
    M[:3, 2] = R[:, 2] * L   # Z column scaled by arrow length
    M[:3, 3] = tail           # tail is the origin of the unit arrow (z=0)
    return M
```

**`make_arrow_mesh` function (`renderer.py`):**

```python
_ARROW_GEO = None   # module-level cache

def make_arrow_mesh(arrows: np.ndarray,   # (N, 6): [tail_x,y,z, head_x,y,z]
                    color=(0.9, 0.6, 0.1, 1.0),
                    normalize: bool = False) -> gfx.InstancedMesh:
    global _ARROW_GEO
    if _ARROW_GEO is None:
        _ARROW_GEO = _build_unit_arrow_geometry()

    tails, heads = arrows[:, :3], arrows[:, 3:]
    if normalize:
        # Pin all arrows to the same length (mean magnitude)
        mags = np.linalg.norm(heads - tails, axis=1, keepdims=True)
        mean_mag = float(np.nanmean(mags))
        dirs = (heads - tails) / np.maximum(mags, 1e-10)
        heads = tails + dirs * mean_mag

    mat = gfx.MeshPhongMaterial(color=color, side="front")
    mesh = gfx.InstancedMesh(_ARROW_GEO, mat, len(arrows))
    valid = 0
    for i, (t, h) in enumerate(zip(tails, heads)):
        M = _arrow_matrix(t, h)
        if M is not None:
            mesh.set_matrix_at(i, M)
            valid += 1
    return mesh
```

---

**Shape detection and render types:**

Extend `_detect_shape` (`evaluator.py`) to recognise vector arrays before the existing scatter checks:

```python
if val.ndim == 2 and val.shape[1] == 6:
    return "vectors", val       # 3D tail+head pairs
if val.ndim == 2 and val.shape[1] == 4:
    return "vectors_2d", val    # 2D tail+head pairs (z=0 plane)
```

Priority: `(N, 6)` → vectors before `(N, 3)` → scatter, so a 6-column array is never misread as scatter.

For 2D vectors, promote to 3D before passing to `make_arrow_mesh`:
```python
arrows_3d = np.column_stack([val[:, :2],
                              np.zeros(len(val)),
                              val[:, 2:4],
                              np.zeros(len(val))])
```

**Flow mode — consecutive-pair arrows:**

Flow mode is a fourth option in the scatter render mode radio selector (FEAT-033), alongside "Circles", "Line", "Spheres". When `scatter_render_mode == "arrows"`:

```python
pts = result.data   # (N, 3) scatter array
arrows = np.concatenate([pts[:-1], pts[1:]], axis=1)   # (N-1, 6)
obj = make_arrow_mesh(arrows, color=style.color,
                      normalize=style.normalize_arrows)
```

This converts a trajectory into N−1 flow arrows with no change to the evaluator — just the render dispatch in `_on_cell_result`.

---

**`CellStyle` additions:**

```python
normalize_arrows: bool = False   # pin all arrows to equal length
```

The normalize toggle appears in the style popover alongside the render mode radio buttons (only visible when render mode is "arrows" or render type is "vectors"/"vectors_2d"). Persisted to YAML.

---

**`_on_cell_result` dispatch (`app.py`):**

```python
elif result.render_type in ("vectors", "vectors_2d"):
    data = result.data
    if result.render_type == "vectors_2d":
        data = np.column_stack([data[:, :2], np.zeros(len(data)),
                                data[:, 2:], np.zeros(len(data))])
    obj = make_arrow_mesh(data, color=style.color,
                          normalize=style.normalize_arrows)
    vp.add_object(cell_id, obj)
```

Flow mode is handled in the existing `scatter` dispatch block by switching on `style.scatter_render_mode == "arrows"` and converting consecutive pairs as above.

---

**Performance:**

- Unit geometry: ~160 vertices and ~280 triangles (8 segments, shaft + cone). Fixed cost.
- `InstancedMesh` with N instances: one draw call. Scales to thousands of arrows with no meaningful overhead.
- Per-arrow matrix computation: one cross-product, one Rodrigues rotation, one 4×4 fill — O(N) CPU work, takes < 1 ms for N ≤ 1000.
- The bottleneck for large vector fields (N > 10K) is the Python loop over `set_matrix_at`. This can be pre-vectorized if needed by constructing all matrices as a batched numpy operation and uploading in one call (requires checking pygfx's InstancedMesh API for bulk matrix upload).

---

### FEAT-018 — Load external data files into data cells
**Status:** Open  
**Logged:** 2026-05-17

**Description:**  
Allow a data cell to load an external file by providing a quoted path as the RHS of an assignment. When the user presses ▷, the app detects that the source is a path literal, attempts to load the file, and exposes the result as a numpy array in the shared namespace — identical to any other data cell output. Load errors (bad path, unsupported format, malformed content) are surfaced in the cell's status area with a descriptive message rather than crashing.

**UX flow:**
```
d = "path/to/data.npy"
```
1. User types the above in a data cell and presses ▷.
2. The loader detects the string literal RHS and dispatches to the appropriate format handler.
3. On success: the cell shows `ok` status, exports `d` (the array or dict) into the shared namespace, and displays the shape in the preview area (e.g. `(1000, 3)`).
4. On failure: the cell shows an `error` status with a plain-language message (e.g. "File not found: path/to/data.npy" or "CSV parse error: non-numeric value in column 2, row 47"). No popup — consistent with how other cell errors are handled.

**Supported formats:**

| Extension | Loader | Notes |
|-----------|--------|-------|
| `.npy` | `np.load(path, allow_pickle=False)` | Single array; see security note below |
| `.npz` | `np.load(path, allow_pickle=False)` | Zip of named arrays; expose as a dict `{"x": arr, ...}` and also unpack each key as `d_x`, `d_y`, etc. into the namespace |
| `.csv` | `np.loadtxt(path, delimiter=",", comments="#")` | Falls back to `np.genfromtxt` with `invalid_raise=False` for files with missing values; skip header rows that can't be parsed as floats |
| `.tsv` | Same as CSV with `delimiter="\t"` | |
| `.txt` | `np.loadtxt(path)` (whitespace-delimited) | |
| `.mat` | `scipy.io.loadmat(path)` | Optional — only if scipy is available; expose the variable dict, let the user index it like `d["x"]` |
| `.json` | `json.load` → `np.array(...)` | Only if the JSON structure is a flat list or list-of-lists; reject otherwise with a clear error |

Other formats (HDF5, Parquet, Excel) are out of scope for v1 — they pull in large optional dependencies and have complex internal structure; log them as "unsupported format" rather than silently failing.

**Implementation sketch:**

Detection happens in `_run_data_cell` (or a new `_load_file_cell` helper called from it) before the usual `run_cell` path:
```python
import ast, re
source = cell.source().strip()
# Match:  name = "some/path"  or  name = 'some/path'
m = re.fullmatch(r'(\w+)\s*=\s*(["\'])(.+?)\2', source)
if m:
    var_name, _, file_path = m.group(1), m.group(2), m.group(3)
    _load_file_into_cell(cell, var_name, Path(file_path))
    return
```
`_load_file_into_cell` resolves the path, dispatches by suffix, wraps the loader call in a `try/except`, and writes the result into `_data_cell_ns` exactly as a computed array would be.

**Security considerations — read carefully:**

- **Pickle deserialization / RCE** (`np.load`): Numpy `.npy` and `.npz` files that contain Python object arrays require pickling. A maliciously crafted `.npy` file with a pickled payload can execute arbitrary code on load. **Always call `np.load(path, allow_pickle=False)`.** If the file requires pickle, numpy raises a `ValueError`; surface it as: "File requires pickle deserialization, which is disabled for security. Re-save the array with `np.save()` using a numeric dtype." Similarly, `scipy.io.loadmat` uses pickle internally for some object types — use only the non-pickle code path if scipy is added.

- **Path traversal**: A relative path like `../../.ssh/id_rsa` resolves relative to the process working directory and could read sensitive files. The loader should call `Path(file_path).resolve()` and optionally warn if the resolved path escapes a user-configured data directory. At minimum, log the resolved absolute path in the cell status so the user can see exactly what was read.

- **Zip bombs** (`.npz`): `.npz` is a zip archive. A malicious file could decompress to gigabytes from a small on-disk size. Add a size cap: check `os.path.getsize(path)` before loading and reject files above a reasonable threshold (e.g. 500 MB) with a clear error. Note this does not fully protect against zip bombs — a more robust approach is to open the zip and check member sizes before extracting.

- **Large file / memory exhaustion**: Even legitimate files can be arbitrarily large. The 500 MB cap above applies here too. Surface the file size in the cell's `ok` preview (e.g. `(1000000, 3) — 22.9 MB`) so the user has visibility.

- **`open()` is currently blocked in equation cells** (`safety.py:23`) but data cells are explicitly more permissive. File loading must stay confined to data cells and the dedicated loader path — it should not be possible to trigger file I/O from an equation cell expression.
