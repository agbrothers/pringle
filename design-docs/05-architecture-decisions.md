# Architecture Decisions and Open Questions

This document tracks the high-level design decisions for Pringle and the open questions that need resolution before or during prototyping.

## Guiding Principles

1. **Python-native expression syntax** — expressions are valid Python math syntax, evaluated against a numpy namespace. No custom notation or LaTeX.
2. **GPU-first rendering** — the 3D viewport uses a real GPU backend, not matplotlib. This enables smooth animation and large grid sizes.
3. **Reactive evaluation** — changing a slider or expression re-evaluates only the affected surfaces, not the entire scene.
4. **Progressive complexity** — the tool should be immediately useful for simple `z = f(x,y)` surfaces and grow to support parametric surfaces, vector fields, and ODE integration.

## Decided

| Decision | Choice | Rationale |
|---|---|---|
| Target environment | Standalone desktop window (not Jupyter, not browser) | Best performance; no web-dev complexity; direct GPU access |
| Expression language | Python math syntax via `eval()` with restricted namespace | Natural for Python users; easy to prototype |
| Expression security (personal) | Raw `eval()` with math-only namespace | Sufficient for local use; swap in AST whitelist before public release |
| Time variation | `t` as a reserved animation parameter; slider UI for all named params | Preserves Desmos's parameter-looping model; makes time first-class |
| Grid evaluation (v1) | CPU numpy vectorized eval + buffer re-upload | Simple, debuggable, sufficient for 30fps at 128×128 |

## Open Questions

### 1. GPU / Rendering Library
**Options**: Vispy (`gloo` + `scene`) vs. wgpu-py + pygfx

- **Vispy**: mature, stable, large community, good documentation, OpenGL
- **pygfx/wgpu-py**: modern WebGPU API, better long-term foundation, smaller community

*Recommendation*: prototype with **Vispy** (faster to get something working); migrate to pygfx if Vispy's API becomes limiting.

### 2. UI Framework for Expression Panel + Sliders
**Options**: Dear PyGui, PyQt6, PySide6, imgui-bundle

- **Dear PyGui**: immediate-mode GUI, easy to prototype, performant, no layout XML
- **PyQt6**: mature, flexible layouts, better for complex panels; more boilerplate
- **imgui-bundle**: Dear ImGui Python bindings; common in graphics/game tooling

*Needs prototyping*: evaluate how easily each embeds a Vispy/wgpu canvas.

### 3. Implicit Surfaces in v1?
Implicit surfaces (`f(x,y,z) = c`) require either:
- **CPU marching cubes** (PyVista/scikit-image `marching_cubes`): simple but slow for large grids
- **GPU ray marching** (fragment shader): fast but requires GLSL compilation of the expression

*Recommendation*: defer implicit surfaces to v2. Focus v1 on explicit `z = f(x,y)` and parametric surfaces — this covers the primary use cases and is far simpler to implement.

### 4. GLSL Compilation of Expressions (GPU-side eval)
Converting user expressions to GLSL enables:
- Smooth 60fps animation (t as a uniform, no buffer re-upload)
- Implicit surface ray marching
- Compute-shader grid evaluation

*Recommendation*: defer to v2. The CPU numpy path is good enough for v1 and avoids the complexity of translating Python ASTs to GLSL.

## Proposed v1 Scope

### Must Have
- Explicit surfaces: `z = f(x, y)` with python math syntax
- Parametric surfaces: `(x,y,z) = (fx(u,v), fy(u,v), fz(u,v))`
- Parametric curves: `(x,y,z) = (fx(t), fy(t), fz(t))`
- Named parameter sliders with editable range
- `t` as a reserved animation parameter with loop/bounce/once/static modes
- GPU-accelerated 3D viewport with orbit/pan/zoom controls
- Multiple expressions in a list (expression panel)
- Per-expression color and visibility toggle

### Nice to Have (v1 stretch)
- Piecewise / conditional expressions: `expr_a if condition else expr_b`
- Basic vector field: arrows at (x,y,z) grid points showing `(fx, fy, fz)`
- Surface color mapped to a scalar function

### Deferred to v2
- Implicit surfaces (`f(x,y,z) = c`)
- GLSL compilation of expressions
- ODE trajectory integration and streamlines
- Frame recording / export

## Mockup Goals

The first coding sprint should produce a minimal prototype that validates:

1. The chosen GPU library can render a surface and respond to orbit/zoom controls
2. A numpy expression can be evaluated on a grid and uploaded as a mesh
3. A slider value can be changed and the surface updates in real time
4. The expression panel and GPU canvas can coexist in the same window

This does not need to be pretty — it just needs to prove the architecture works end-to-end.
