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
| Time variation | `t` is a reserved scalar injected per frame; slider UI for all named params | Makes time first-class while preserving Desmos's parameter-looping model |
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
| Recurrence relations | Data cell sub-cells: `initial_condition:` and `recursion:`; executed as a generated for loop | Confined to data panel; no equation panel changes; valid Python rule syntax |
| Session persistence | YAML file serializing all cell content, sub-cells, style, slider config, and viewport state | Diffable, version-controllable, shareable; human-readable |
| Grid evaluation (v1) | CPU numpy vectorized eval + buffer re-upload | Simple, debuggable, sufficient for 30fps at 128×128 |

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

## Open Questions

### 1. GPU / Rendering Library
**Options**: Vispy (`gloo` + `scene`) vs. wgpu-py + pygfx

- **Vispy**: mature, stable, large community, good documentation, OpenGL
- **pygfx/wgpu-py**: modern WebGPU API, better long-term foundation, smaller community, better material system (cleaner styling)

*Recommendation*: prototype with **Vispy** (faster to get something working); migrate to pygfx if Vispy's API becomes limiting. pygfx is preferred long-term for styling and transparency.

### 2. UI Framework for Expression Panel + Sliders
**Options**: Dear PyGui, PyQt6, PySide6, imgui-bundle

*Needs prototyping*: evaluate how easily each embeds a Vispy/wgpu canvas in the same window.

### 3. GLSL Compilation of Expressions (GPU-side eval)
Deferred to v2. CPU numpy path is good enough for v1.

### 4. Implicit Surfaces
Deferred to v2. Focus v1 on explicit and parametric surfaces.

## Proposed v1 Scope

### Must Have
- Explicit surfaces: `z = f(x, y)`
- Parametric surfaces: `xyz = array([fx(u,v), fy(u,v), fz(u,v)])`
- Parametric curves: `xyz = array([fx(t), fy(t), fz(t)])`
- Curve / line plots: `y = f(x)`
- Piecewise surfaces: `z = [f, g, h]` with N condition sub-cells
- Named parameter sliders with editable range and animation modes
- `t` as a reserved animation parameter
- Constraint sub-cells with boolean expressions
- `f(x,y) = expr` syntax sugar → lambda + auto-render
- Auto-plot shape inference for bare array expressions
- Data panel with per-cell ▶ Run button
- Recurrence relations via `initial_condition:` + `recursion:` data cell sub-cells
- Dependency-graph evaluation order with undefined-variable suggestion
- Visibility toggle per cell
- Folders and comment cells (docstring detection)
- Per-cell inline error and shape-mismatch warnings
- GPU-accelerated 3D viewport with orbit/pan/zoom
- YAML session save/load
- Per-expression style panel (color, line width, point size, display mode)

### Deferred to v2
- Implicit surfaces (`f(x,y,z) = c`)
- GLSL/WGSL compilation of expressions for GPU-side eval
- Vector fields (arrow glyphs)
- ODE trajectory integration and streamlines
- Frame recording / export
- Transparency for multiple overlapping surfaces (single surface opacity is v1)
- 2D arrays rendered in z=0 plane

## Mockup Goals

The first coding sprint should prove out:

1. Chosen GPU library renders a surface and responds to orbit/zoom controls
2. A numpy expression is evaluated on a grid and uploaded as a mesh
3. A slider value updates and the surface re-renders in real time
4. The expression panel and GPU canvas coexist in the same window
5. A multi-line block with a constraint sub-cell correctly masks the surface
