# Pringle

**Interactive 3D scientific visualization for Python.** Define surfaces, vector fields, scatter plots, and dynamical system trajectories using real Python/numpy expressions — then explore them live with sliders and animation.

```bash
pip install pringle
crunch examples/torus.yml
```

## Why Pringle?

**Real Python** — expressions are plain Python/numpy. `sin(x)*cos(y)`, `scipy.special.gamma(x)`, user-defined lambdas — no domain-specific language to learn. Numpy functions are available by name (`sin`, `cos`, `linspace`, `random`, …) with no prefix required.

**Live interactivity** — any named scalar assignment (`a = 1.0`) becomes a slider. Drag it and every dependent expression re-evaluates instantly via a reactive dependency graph, at 60 fps on a background thread.

**User controls** - Fly through your plot like a video game, using the WASD controls to move around + SPACE/SHIFT to move up and down. 

**Animate anything** — press ▷ on any slider and it loops over its range automatically. Camera orbit and pan stay fluid even while the scene is re-evaluating.

**GPU-accelerated rendering** — powered by [pygfx](https://github.com/pygfx/pygfx) + [wgpu-py](https://github.com/pygfx/wgpu-py). Smooth Phong shading, order-independent transparency, and drop shadows — not matplotlib's software renderer.

**Version-controlled sessions** — sessions are human-readable YAML files. `git diff` shows exactly what changed; send a single `.yml` file to share a visualization with a collaborator.

**Vector fields** — native 2D and 3D arrow rendering, auto-detected from array shapes `(N, 4)` and `(N, 6)`.

**Recurrence relations** — express ODE trajectories directly: `path[n] = path[n-1] + dt * deriv(path[n-1])` with an initial condition sub-cell. Re-evaluates reactively on every slider tick.

**Piecewise expressions** — `z = [f, g, h]` with condition sub-cells produces a single unified surface.

**Constraint masking** — boolean sub-cells clip any surface without touching the expression.

**Folders and comments** — organize complex sessions; collapsed folders keep the expression panel clean.

## Pringle vs. Other Tools

| | Pringle | Desmos 3D | matplotlib `Axes3D` | Plotly |
|---|---|---|---|---|
| Language | Python / numpy | Custom math notation | Python | Python |
| Live sliders | ✓ | ✓ | — | Requires Dash |
| GPU rendering | ✓ (wgpu) | ✓ (WebGL) | — | — |
| Vector fields | ✓ | — | — | Limited |
| Recurrence / ODE paths | ✓ | Limited | Manual | Manual |
| scipy / custom functions | ✓ | — | ✓ | ✓ |
| Version-controllable | ✓ (YAML) | — | — | — |

## Installation

```bash
pip install pringle
```

Requires Python ≥ 3.11.

## Running Pringle

```bash
# Open a saved session
crunch path/to/session.yml

# Open a tutorial
crunch examples/tutorials/01_hello_surface.yml

# Alternative pringle alias
pringle examples/tutorials/01_hello_surface.yml
```

## Expression Language

Cells evaluate as plain Python. Spatial variables `x`, `y`, `u`, `v` are injected as numpy arrays over the evaluation grid. Output type is determined by the **magic variable** assigned:

| Assignment | Renders as |
|---|---|
| `z = ...` | Explicit surface `(N, M)` |
| `xyz = ...` | Parametric surface or curve `(3, N, M)` or `(3, N)` |
| `points = ...` | Scatter plot `(N, 3)` or `(N, 2)` |
| `f(x, y) = ...` | Auto-rendered surface + reusable namespace function |

Shapes `(N, 4)` and `(N, 6)` are auto-detected as 2D and 3D vector fields respectively. They are viewed as N row vectors, with each row having the tail and head coordinates concatenated together.  

## Tutorials

Step-by-step sessions in [`examples/tutorials/`](examples/tutorials/):

| File | Concept |
|---|---|
| [`01_hello_surface.yml`](examples/tutorials/01_hello_surface.yml) | First surface — explicit `z = sin(x) * cos(y)` |
| [`02_sliders.yml`](examples/tutorials/02_sliders.yml) | Interactive slider parameters |
| [`03_animation.yml`](examples/tutorials/03_animation.yml) | Animated slider — traveling wave |
| [`04_parametric.yml`](examples/tutorials/04_parametric.yml) | Parametric surface — sphere via `xyz` |
| [`05_constraints.yml`](examples/tutorials/05_constraints.yml) | Constraint sub-cells — clipping a surface |
| [`06_scatter.yml`](examples/tutorials/06_scatter.yml) | Scatter plot — helix point cloud |
| [`07_vector_field.yml`](examples/tutorials/07_vector_field.yml) | 2D vector field — gradient of a surface |
| [`08_recurrence.yml`](examples/tutorials/08_recurrence.yml) | Recurrence relation — integrating an ODE |

More complex real-world examples live in [`examples/`](examples/).

## Further Reading

- [`design-docs/01-desmos-3d-overview.md`](design-docs/01-desmos-3d-overview.md) — inspiration and comparison with Desmos 3D
- [`design-docs/03-expression-evaluation.md`](design-docs/03-expression-evaluation.md) — expression language, security model, and namespace
- [`design-docs/04-animation-and-time-variation.md`](design-docs/04-animation-and-time-variation.md) — animation loop and performance model
- [`design-docs/07-cell-types-and-blocks.md`](design-docs/07-cell-types-and-blocks.md) — all cell types: equation, slider, folder, comment; piecewise and constraints
- [`design-docs/08-visual-styling.md`](design-docs/08-visual-styling.md) — colors, colormaps, opacity, and render modes
- [`design-docs/10-session-format.md`](design-docs/10-session-format.md) — full YAML session schema reference
- [`design-docs/11-recurrence-relations.md`](design-docs/11-recurrence-relations.md) — recurrence syntax, execution model, and ODE integration
- [`design-docs/12-user-input-and-interaction.md`](design-docs/12-user-input-and-interaction.md) — keyboard shortcuts, camera controls, WASD navigation
