# Animation and Time Variation

## Desmos's Approach

Desmos approximates time-varying behavior through **parameter animation**: any named parameter (slider) can be set to loop over a range at a fixed rate. There is no explicit "time" concept — `t` is just a slider that happens to increment automatically. This is flexible (you control the rate and range) but indirect.

Pringle can make time a first-class concept while preserving the same slider-driven flexibility.

## Core Model

Every expression can reference a set of **named parameters** in addition to spatial coordinates:

- `x`, `y`, `z`, `u`, `v` — spatial coordinates (reserved)
- `t` — time (reserved; auto-increments when animation is running)
- `a`, `b`, `n`, `k`, ... — user-defined sliders

Each parameter has:
- A current value
- A range `[min, max]`
- An optional animation mode: **loop**, **bounce**, **once**, or **static**
- A rate (units per second, or steps per second for discrete parameters)

## Animation Loop

```
Tick (frame callback, ~60fps target)
    ↓
Advance t (and any other animating parameters) by dt
    ↓
For each expression that references changed parameters:
    Re-evaluate over the grid
    Update the GPU buffer / uniform
    ↓
Render frame
```

The tick is driven by the display refresh (via a timer or `requestAnimationFrame` equivalent). The render step and the evaluation step are decoupled — if evaluation takes longer than one frame, the render still fires at the display rate using the last computed mesh.

## Performance Model for Re-evaluation

| Approach | Cost | When to use |
|---|---|---|
| **CPU numpy eval + buffer re-upload** | 5–20ms at 256×256 | Default; sufficient for 30fps static-ish surfaces |
| **GLSL/WGSL uniform** (t encoded in shader) | ~0.1ms | Expression compiled to GPU shader; ideal for smooth animation |
| **GPU compute shader** (full grid eval on GPU) | ~1–2ms | Flexible; supports arbitrary math; later optimization |

### Recommended progression:

**v1**: CPU numpy evaluation + vertex buffer re-upload per frame. Simple, debuggable, fast enough for most surfaces at reasonable grid resolution.

**v2**: Compile expression to GLSL (or WGSL for wgpu-py). Upload `t` and slider values as uniforms. The GPU evaluates the surface formula across all grid points in parallel. This enables smooth 60fps animation of complex parametric surfaces.

## Grid Resolution vs. Frame Rate Tradeoff

| Grid size | Vertices | CPU eval time (approx) | Notes |
|---|---|---|---|
| 64 × 64 | ~4K | < 1ms | Coarse; fine for fast prototyping |
| 128 × 128 | ~16K | ~2–5ms | Good default |
| 256 × 256 | ~65K | ~10–20ms | High quality; borderline for 60fps CPU eval |
| 512 × 512 | ~260K | ~60–100ms | Needs GPU eval for smooth animation |

A **multi-resolution strategy** (coarse while animating / dragging, fine when paused) mimics what Desmos does and is straightforward to implement.

## Parametric Surfaces with Time

A time-varying parametric surface `(x,y,z) = f(u, v, t)` requires re-evaluating three functions per grid point per frame. At 128×128 this is ~16K evaluations of three numpy expressions — comfortably real-time on CPU.

```python
# Example: rotating parametric torus
# x = (R + r*cos(v)) * cos(u + t)
# y = (R + r*cos(v)) * sin(u + t)
# z = r * sin(v)
```

The user would enter three expressions (for x, y, z) referencing `u`, `v`, and any sliders including `t`.

## Slider UI

Each parameter entry in the expression panel should render as:

```
[ a ]  ──●───────────  [-2.0 ............. 5.0]   ▷ loop
```

Controls:
- Drag the handle to set value manually
- Click the range endpoints to edit bounds
- Click the play button to start animation
- Cycle through: loop / bounce / once / static

## Relationship to Expression Dependency Graph

The animation system only needs to re-evaluate expressions that **reference** the parameter being animated. A static surface `z = sin(x) * cos(y)` (no parameters) never needs re-evaluation. This dependency tracking is determined at compile time by inspecting the expression AST for free variable names.

## Stretch Goals

- **ODE integration**: define a vector field `(dx/dt, dy/dt, dz/dt) = f(x,y,z,t)` and integrate trajectories using `scipy.integrate.solve_ivp`, rendering streamlines or particle paths
- **Frame recording**: export animation to GIF or MP4 using `imageio` or `ffmpeg`
- **Synchronized parameters**: multiple sliders can share a single animation clock (e.g., `a = sin(t)`, `b = cos(t)`)
