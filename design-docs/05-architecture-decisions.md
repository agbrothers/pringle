# Architecture Decisions and Open Questions

This document tracks the high-level design decisions for Pringle and the open questions that need resolution before or during prototyping.

## Guiding Principles

1. **Python-native expression syntax** — expressions use Python math syntax evaluated against a whitelisted numpy/scipy namespace. No custom notation or LaTeX.
2. **GPU-first rendering** — the 3D viewport uses a real GPU backend, not matplotlib. This enables smooth animation and large grid sizes.
3. **Reactive evaluation** — changing a slider or expression re-evaluates only the affected cells, not the entire scene. Evaluation order is determined by a dependency graph, not visual order.
4. **Progressive complexity** — immediately useful for simple `z = f(x,y)` and grows to support parametric surfaces, constraints, vector fields, and ODE integration.
5. **Warn, don't crash** — cell errors surface as inline warnings; the rest of the scene continues rendering.

## Decided

| Decision | Choice | Rationale |
|---|---|---|
| Target environment | Standalone desktop window | Best performance; direct GPU access; no web-dev complexity |
| Expression language | Python math syntax, numpy/scipy namespace | Natural for Python users; no prefix needed; limited attack surface |
| Expression security | Whitelisted namespace (numpy/scipy only) + no builtins + AST safety check | Strong posture for personal/trusted use; upgrade to subprocess isolation before full public release |
| Data panel security | Whitelisted namespace + no builtins (no AST check) | Data panel is intentionally more permissive; document clearly |
| Data re-evaluation | Per-cell "run" button only; never automatic | Prevents stochastic re-sampling from being tied to slider/animation updates |
| Time variation | `t` is a reserved scalar injected per frame; slider UI for all named params | Makes time first-class while preserving Desmos's parameter-looping model |
| Evaluation order | Dependency graph (topological sort), not visual order | Visual order is for organization only; cells can be freely dragged/reordered |
| Undefined variable handling | Static AST free-variable analysis → inline warning + "add slider" suggestion button | Mirrors Desmos UX; guides users toward correct cell structure |
| Shape validation | Validate output shapes after exec; show inline cell warning on mismatch | Never crash the renderer; isolate errors to the offending cell |
| Expression blocks | Multi-line `exec()` blocks; first line is magic variable (visual convention only) | Natural Python decomposition; constraints and helpers on subsequent lines |
| Constraint model | Bare boolean expression lines in a block → `np.where(mask, value, nan)` | Masks invalid regions without crashing; composable |
| Helper functions | `f = lambda x, y: ...` in any cell → available in shared namespace | Mirrors Desmos's `f(x,y) = ...` pattern; no special syntax needed |
| Visibility toggle | Per-cell boolean; off = skip renderer submission but still evaluate namespace | Allows modular building without rendering intermediate pieces |
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

*Needs prototyping*: evaluate how easily each embeds a Vispy/wgpu canvas in the same window.

### 3. GLSL Compilation of Expressions (GPU-side eval)
Converting user expressions to GLSL enables smooth 60fps animation (t as a uniform) and ray-marched implicit surfaces. Adds significant complexity. Deferred to v2.

### 4. Implicit Surfaces
Require marching cubes (CPU) or ray marching (GPU). Deferred to v2. Focus v1 on explicit and parametric surfaces.

## Proposed v1 Scope

### Must Have
- Explicit surfaces: `z = f(x, y)`
- Parametric surfaces: `xyz = array([fx(u,v), fy(u,v), fz(u,v)])`
- Parametric curves: `xyz = array([fx(t), fy(t), fz(t)])`
- Curve / line plots: `y = f(x)` as a magic name
- Named parameter sliders with editable range and animation modes (loop, bounce, once, static)
- `t` as a reserved animation parameter
- Multi-line equation blocks with constraint lines
- Helper functions via lambdas in shared namespace
- Data panel with per-cell run button
- Dependency-graph evaluation order with undefined-variable suggestion
- Visibility toggle per cell
- Folders and comment cells for organization
- Per-cell inline error and shape-mismatch warnings
- GPU-accelerated 3D viewport with orbit/pan/zoom

### Deferred to v2
- Implicit surfaces (`f(x,y,z) = c`)
- GLSL/WGSL compilation of expressions for GPU-side eval
- Vector fields (arrow glyphs)
- ODE trajectory integration and streamlines
- Frame recording / export to GIF or MP4

## Mockup Goals

The first coding sprint should prove out:

1. Chosen GPU library renders a surface and responds to orbit/zoom controls
2. A numpy expression is evaluated on a grid and uploaded as a mesh
3. A slider value updates and the surface re-renders in real time
4. The expression panel and GPU canvas coexist in the same window
5. A multi-line block with a constraint line correctly masks the surface

This does not need to be polished — it validates the architecture works end-to-end.
