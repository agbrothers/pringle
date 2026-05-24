# Architecture Decisions and Open Questions

This document tracks the high-level design decisions for Pringle and the open questions that need resolution before or during prototyping.

## Guiding Principles

1. **Python-native expression syntax** — expressions use Python math syntax evaluated against a whitelisted numpy/scipy namespace. No custom notation or LaTeX.
2. **GPU-first rendering** — the 3D viewport uses a real GPU backend, not matplotlib. This enables smooth animation and large grid sizes.
3. **Reactive evaluation** — changing a slider or expression re-evaluates only the affected cells, not the entire scene. Evaluation order is determined by a dependency graph, not visual order.
4. **Progressive complexity** — immediately useful for simple `z = f(x,y)` and grows to support parametric surfaces, constraints, vector fields, and ODE integration.
5. **Warn, don't crash** — cell errors surface as inline warnings; the rest of the scene continues rendering.
6. **Everything serializable** — all session state (expressions, UI config, style, slider values, viewport) is stored in a portable YAML file. Sessions are diffable, version-controllable, and shareable.

## Decided

| Decision | Choice | Rationale |
|---|---|---|
| Target environment | Standalone desktop window | Best performance; direct GPU access; no web-dev complexity |
| Expression language | Python math syntax, numpy/scipy namespace | Natural for Python users; no prefix needed; limited attack surface |
| Expression security | Whitelisted namespace (numpy/scipy only) + no builtins + AST safety check | Strong posture for personal/trusted use; upgrade to subprocess isolation before full public release |
| Data panel security | Whitelisted namespace + no builtins (no AST check) | Data panel is intentionally more permissive; document clearly |
| Data re-evaluation | Per-cell ▶ Run button only; never automatic | Prevents stochastic re-sampling from being tied to slider/animation updates |
| Time variation | `t` is **not** reserved — it is a regular slider name in v1; a dedicated animation mechanism is deferred to v2 | `t` removed from `SPATIAL_NAMES` and `grid_vars()` (FEAT-041); injecting `t=0` was dead code that blocked a common slider name |
| Evaluation order | Dependency graph (topological sort), not visual order | Visual order is for organization only; cells can be freely dragged/reordered |
| Undefined variable handling | Static AST free-variable analysis → inline warning + "add slider" suggestion button | Mirrors Desmos UX; guides users toward correct cell structure |
| Shape validation | Validate output shapes after exec; show inline cell warning on mismatch | Never crash the renderer; isolate errors to the offending cell |
| Expression blocks | Single-expression primary cell + typed sub-cells (constraints, color fn) | Keeps block semantics simple; multi-line helpers are separate top-level cells |
| Constraint model | UI-driven constraint sub-cells (input boxes with visual indicator); backend: `np.logical_and` + `np.where` | Masks invalid regions; composable; constraints can reference `z` after it is computed |
| Piecewise functions | `z = [f, g, h]` (list of callables/arrays) + N condition sub-cells; `np.select` with implicit prior-condition negation | List syntax is ordered and unambiguous; UI auto-creates N condition cells |
| Piecewise validation | Warn and suppress render if number of conditions ≠ number of pieces | Explicit error rather than silent mismatch |
| Helper functions | `f(x,y) = expr` → preprocessed to `f = lambda x, y: expr` | Unambiguous (never valid Python); concise; matches math notation |
| f(x,y) auto-render | Cells defining spatial-argument functions auto-render (see table below); visibility toggle controls display | Reduces friction; functions are immediately visual AND compositional |
| Auto-plot output detection | Priority: (1) magic name, (2) function signature, (3) return shape inference | Tries to plot anything plottable; never plots scalars, 1D arrays, or plain lists |
| Bare (N,3) / (N,2) arrays | Default render type: scatter; style panel allows switching to line (connected points) | Matches Desmos behavior; resolves ambiguity without parse-time inference |
| Visibility toggle | Per-cell boolean; off = skip renderer submission but still evaluate namespace | Allows modular helpers that are never directly rendered |
| Recurrence relations | Sub-cells `initial_condition:` and `recursion:` available on any cell; adding a recursion sub-cell auto-enables data mode; rendered shape inferred via `_detect_shape` (vectors, scatter, etc.); unrecognised shapes exported namespace-only | `add_sub_cell("recursion")` calls `set_data_mode(True)`; `_eval_cell` skips auto-switch when recurrence rule present |
| Session persistence | YAML file serializing all cell content, sub-cells, style, slider config, and viewport state | Diffable, version-controllable, shareable; human-readable |
| Grid evaluation (v1) | CPU numpy vectorized eval + buffer re-upload | Simple, debuggable, sufficient for 30fps at 128×128 |
| Magic variable scoping | Magic names (`z`, `y`, `xyz`, etc.) are local to cell execution; never exported to shared namespace | Allows multiple `z = expr` cells without collision; spatial grid vars are never shadowed |
| Duplicate magic name cells | Two cells both writing `z = expr` → two independent surfaces | Each renders separately; no shared namespace conflict |
| Unified dependency graph | All cells (equation and data) on the same DAG; panel separation is UI-only | Solves boot order; data cells can reference equation lambdas; both panels freely reorderable |
| Data cell reactivity | Auto-evaluates on upstream parameter changes (slider animation, upstream cell edits), same as any equation cell; text edits to the cell or sub-cells mark stale instead of debounce-re-evaluating; `→` button increments `_rng_seed` (produces new draws) | Stable random draws during slider animation; user controls resampling explicitly |
| Session boot sequence | (1) load YAML, (2) build DAG, (3) eval reactive cells (sliders/lambdas), (4) ▶▶ Run All data, (5) eval render cells, (6) first render | Guarantees lambdas available to data cells at load time |
| Comment cell detection | Source starts with `#`; auto-morphs to `CommentCellWidget` on focus-out. Auto-reverse: editing the text so it no longer starts with `#` immediately morphs back to an equation cell via `_on_comment_changed`. `# ` prefix is stored as literal text in the edit field — no separate margin decoration. | Bidirectional morph keeps the cell type in sync with the text without requiring an explicit toggle |
| (u,v) parametric grid default | `[0, 2π] × [0, 2π]`; configurable in View Settings panel | Captures full rotation for common cylindrical/spherical surfaces |
| WASD camera controls | Pan the orbit target in world space: W=+Y, S=−Y, A=−X, D=+X, Space=+Z, Shift=−Z. Step = 5% of camera-to-target distance per keypress (single-step) → 0.7% per frame (continuous hold). Continuous movement tracked via Qt `keyPressEvent`/`keyReleaseEvent`; `event.accept()` suppresses the macOS press-and-hold accent popover. `focusOutEvent` clears held keys to prevent stuck movement. | Handled at the Qt level (not wgpu) so macOS text-input interception is bypassed |
| Constraint boundary clipping | Triangles crossing the constraint boundary are clipped at the exact edge using linear interpolation, producing smooth diagonal cuts instead of a pixel-stepped staircase. Triangles entirely outside are discarded; boundary triangles become 1 or 2 new triangles with midpoint vertices. Pre-mask z values (`z_raw`) are used for vertex positions so boundary interpolation is finite. | `_clip_mesh_to_mask()` in `renderer.py`; O(n_triangles) with edge cache |
| Zero-size buffer guard | When all triangles are clipped away (e.g., slider at zero with a constraint that excludes everything), `make_surface_mesh` returns an invisible placeholder mesh (opacity=0, 1 degenerate triangle) rather than passing an empty buffer to `gfx.Geometry` which would crash. | Prevents `ValueError: Buffer size cannot be zero` on slider edge cases |
| Scatter fallback for non-magic names | After checking magic names (`z`, `xyz`, `y`, `x`, `points`), `_detect_magic` scans all other user-assigned variables for plottable shapes — `(N,3)`, `(N,2)`, `(3,)`, `(2,)`. First match is scatter-plotted. | Allows `p = array([[0,0,0]])` to render without requiring the magic name `points` |
| Camera orbit target | `fit_camera()` always resets `controller.target` to `(0,0,0)` after `show_object()`. Without this, a constrained surface living above z=0 pulls the orbit center upward, making the origin appear off-screen. | `PringleRenderer.fit_camera()` |
| Camera fit on add | `PringleViewport.add_object()` only calls `fit_camera()` when the cell_id is new to the scene. Slider updates that replace an existing object leave the camera untouched. | Prevents camera jumping when dragging a slider |
| CellWidget → SliderWidget morphing | Morph is deferred to focus-out (BUG-043): `CellWidget.commit_requested` fires on `CellTextEdit.focus_lost` and triggers `_maybe_morph_to_slider`. Negative literals (`a = -3`) are supported via UnaryOp unwrapping in `is_slider_cell` (BUG-044). Out-of-range values expand the slider's bounds rather than clamping (BUG-045). | Prevents mid-edit snapping; supports full numeric range |
| Recurrence loop index | User writes `n`; internally renamed to `_pringle_loop_n` before execution | Prevents collision with any slider or variable named `n` |
| Slider animation eval thread | Cell evaluation during slider animation runs on a `QThread`-backed `_EvalWorker`; results posted back to main thread via queued signal | Main thread is free to process camera events at 60 fps; no camera lag during animation. `eval_threaded=False` default keeps tests synchronous (avoids Python 3.13 incremental GC / QThread lifecycle issues). See `CellListWidget` in `cell_list.py` |
| Animation tick coalescing | `_pending_eval` stores only the latest `(name, value)` tick; dispatched when the worker becomes free | Animation frames are never queued; if eval takes longer than 16 ms the display skips frames rather than building a backlog |
| DAG caching | `CellListWidget._get_dag()` caches the `nx.DiGraph` keyed on `{cell_id: source()}` for all evaluable cells; rebuilds only when any source changes | Eliminates ~40 AST parses per animation tick (was 2.2 ms; now <0.01 ms per tick) |
| Invisible cell pruning during animation | `_dispatch_pending_eval` uses backward-reachability from visible output cells to compute `required_ids`; invisible cells with no visible dependents are skipped entirely; invisible ancestors of visible cells are still evaluated | Avoids executing numpy work that is immediately discarded; saves ~3.5 ms/tick when a recurrence output cell is invisible |
| Expression bounds on sliders and axis limits | Slider min/max/step and axis bound fields are `_ExprBox` (QLineEdit subclass) that accept either a plain float or a Python expression resolved against a scalar-only namespace. On commit: float → plain mode; expression → stored as `_raw_expr`, resolved value drives behavior. After each `_rebuild_namespace()`, `re_resolve` is called on all slider boxes; `set_resolver` is pushed to `ViewSettingsWidget` from `PringleWindow` via the `namespace_rebuilt` signal. Axis bounds do NOT auto-apply on namespace change — only on the next "Apply Bounds" click. Resolver merges equation-namespace scalar constants (`pi`, `e`, `inf`, `nan`) with shared-namespace scalars. YAML: `min_expr`, `max_expr`, `step_expr` on slider cells; `x_min_expr` … `z_max_expr` in the view block (all optional, omitted for plain numeric). |

## f(x,y) Auto-Render Rules

| Function signature | Auto-renders as | Notes |
|---|---|---|
| `f(x, y)` | Surface: `z = f(x, y)` | Most common case |
| `f(x)` | Curve: `y = f(x)` | 1D function of x |
| `f(u, v)` | Parametric surface: evaluates over (u,v) grid | |
| Any other args | Namespace-only; no auto-render | e.g., `f(n)`, `f(path)`, `f(x, y, z)` |

## Auto-Plot Shape Inference (Priority Order)

When no magic name is found, infer render type from the output shape:

| Shape | Render type | Notes |
|---|---|---|
| `(N, 3)` | 3D scatter | Default; style panel allows switching to line |
| `(N, 2)` | 2D scatter | Default; style panel allows switching to line |
| `(3,)` | Single 3D point | Scalar scatter with 1 point |
| `(2,)` | Single 2D point | |
| Scalar | No render; warn | |
| `(N,)` | No render; warn | 1D arrays are ambiguous; not plotted |
| `(N, M)` not matching grid | No render; defer | Future: assume z=0 plane |
| Python list / non-array | No render; warn | |

## Decided: Library Choices

### GPU / Rendering Library: **pygfx + wgpu-py**

Chosen over Vispy for the following reasons:
- Material system maps 1:1 to style panel controls (color, opacity, line width, display mode)
- Line width works correctly on macOS (rendered as screen-space quads, not GL lines which are clamped to 1px)
- Transparency handling (WBOIT) available without manual depth sorting
- Modern WebGPU API — better long-term foundation for v2 features (compute shaders, GPU-side expression eval)
- WASD camera controls supported via `FlyController` and `OrbitController` key event callbacks

Trade-off accepted: smaller community, less documentation, more initial setup time than Vispy.

### UI Framework: **PyQt6 / PySide6**

Chosen over Dear PyGui for the following reasons:
- First-class native widget embedding for pygfx canvas (via `QOpenGLWidget` / native window handle)
- Widget system suited for the panel architecture: draggable cells, sub-cells, collapsible folders
- QWidget-based constraint sub-cells and style popovers are straightforward
- PySide6 (same API, LGPL license) is an acceptable drop-in if licensing matters

Trade-off accepted: more boilerplate than Dear PyGui's immediate-mode API.

### 3. GLSL Compilation of Expressions (GPU-side eval)
Deferred to v2. CPU numpy path is good enough for v1.

### 4. Implicit Surfaces
Deferred to v2. Focus v1 on explicit and parametric surfaces.

## Proposed v1 Scope

### Implemented (v1)
- Explicit surfaces: `z = f(x, y)` ✓
- Parametric surfaces/scatter: `xyz = array(...)` ✓
- Curve / line plots: `y = f(x)` ✓
- Piecewise surfaces: `z = [f, g, h]` with N condition sub-cells ✓
- Named parameter sliders with editable range + drag handle ✓
- Slider morph: typing `a = 1` in any cell promotes it to a SliderWidget ✓
- Constraint sub-cells with boolean expressions + smooth boundary clipping ✓
- `f(x,y) = expr` syntax sugar → lambda + auto-render ✓
- Auto-plot shape inference for any (N,3)/(N,2)/(3,)/(2,) user variable ✓
- Dependency-graph evaluation order with undefined-variable warning ✓
- Visibility toggle per cell ✓
- Folders and comment cells (docstring detection) ✓
- Per-cell inline error and shape-mismatch warnings ✓
- GPU-accelerated 3D viewport: orbit/pan/zoom + WASD continuous world-space pan ✓
- YAML session save/load (Ctrl+S/O/N) ✓
- Per-expression style panel (color, line width, point size) ✓
- Coordinate axes (R/G/B) + wireframe bounding box overlay, toggleable ✓
- Orbit-target crosshair indicator, synced every frame, toggleable ✓
- Equalize Axes: sets x/y bounds to match current z data range (bounding sphere radius) ✓
- Undo/redo (snapshot-based), copy/paste cells ✓

### Deferred to v2
- Data panel with per-cell ▶ Run button (designed; not yet implemented)
- Recurrence relations via initial_condition + recursion sub-cells (designed; not yet implemented)
- `t` animation parameter + play/pause controls (designed; not yet implemented)
- Implicit surfaces (`f(x,y,z) = c`)
- GLSL/WGSL compilation of expressions for GPU-side eval
- Vector fields (arrow glyphs)
- ODE trajectory integration and streamlines
- Frame recording / export
- Transparency for multiple overlapping surfaces
- 2D arrays rendered in z=0 plane
- Axis labels and tick marks

## Mockup Goals

The first coding sprint should prove out:

1. Chosen GPU library renders a surface and responds to orbit/zoom controls
2. A numpy expression is evaluated on a grid and uploaded as a mesh
3. A slider value updates and the surface re-renders in real time
4. The expression panel and GPU canvas coexist in the same window
5. A multi-line block with a constraint sub-cell correctly masks the surface
