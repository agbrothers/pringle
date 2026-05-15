# Desmos 3D: Design Overview

## Architecture

Desmos 3D is a browser-based, reactive expression evaluator coupled to a WebGL renderer. The two halves are:

1. **Expression panel** (left): a list of typed entries that are parsed, compiled to JavaScript, and evaluated over a grid
2. **Viewport** (right): a WebGL scene that re-renders whenever expressions or view settings change

Expressions are compiled to fast numerical functions — not evaluated symbolically. The parser emits JavaScript code that is called in a tight loop over a dense (x,y) or (u,v) grid, often with evaluation happening on the GPU.

## Expression Types

| Type | Example | Notes |
|---|---|---|
| Explicit surface | `z = sin(x) * cos(y)` | Evaluates z on an (x,y) grid |
| Implicit surface | `x² + y² + z² = 1` | Solved with marching cubes or ray marching on a 3D grid |
| Conditional/piecewise | `z = {x > 0 : x², -x²}` | Branches evaluated pointwise; non-matching points are masked |
| Parametric curve | `(cos t, sin t, t)` | Sampled over t ∈ [a,b] |
| Parametric surface | `(u·cos v, u·sin v, u)` | Sampled over (u,v) grid |
| Points / lists | `(1, 2, 3)` or list comprehensions | Scatter plots |
| Vectors | `(a,b,c) → (d,e,f)` | Drawn as arrows |
| Slider / variable | `a = 1.5` | Named parameter with a drag handle; propagates to all expressions |

## Rendering Pipeline

1. **Grid sampling**: explicit surfaces are evaluated on a dense NxN grid (typically 128×128 or 256×256, adaptive). This produces a triangle mesh.
2. **Marching cubes / ray marching**: implicit surfaces either sample a 3D voxel grid and extract an isosurface (CPU), or fire a ray through every pixel and march along it until the surface is hit (GPU fragment shader — much faster for interactive use).
3. **WebGL upload**: the triangle mesh is uploaded to GPU memory. For animated surfaces, only a uniform value (e.g., `t`) needs re-uploading — the GPU re-evaluates the expression on its own.
4. **Phong shading**: directional light + ambient + specular. The surface color (blue/navy default) is a material property.
5. **Transparency**: surfaces can be translucent; handled with depth-sorted rendering passes.
6. **Camera**: arcball orbit controls (mouse drag → quaternion rotation), pan, zoom.

## Interactivity Model

- **Reactive dependency graph**: expressions form a DAG. Changing slider `a` invalidates any surface referencing `a` and triggers re-evaluation + re-render.
- **Sliders**: any bare assignment (`a = 1`) gets a slider automatically. Dragging streams updates at 30–60 fps.
- **Real-time compilation**: expression string → AST → JS code → evaluated in a loop. Fast enough to happen on every keystroke.
- **View settings panel**: axis bounds, grid visibility, labels — separate from the expression system, just reconfigure the viewport.
- **Parameter animation**: a parameter can be set to loop over a range, driving time-varying behavior without explicit animation logic.

## Key Design Tradeoffs

| Decision | Desmos' choice | Alternatives |
|---|---|---|
| Math → code | Compile to JS, eval numerically | Symbolic (SymPy), interpret AST |
| 3D rendering | Custom WebGL (no Three.js) | Three.js, Babylon.js |
| Implicit surfaces | Ray marching in fragment shader (likely) | CPU marching cubes |
| UI framework | React + WebGL canvas | Pure canvas, SVG |
| Animated surfaces | GLSL uniforms updated per frame | CPU re-evaluation + buffer re-upload |
| Float precision | 64-bit in JS; 32-bit in GLSL | Trade-off: 32-bit is faster but causes artifacts at large coordinates |

## What Desmos 3D Does Not Support

These are gaps a Python clone could address:

- Vector fields (arrows at grid points showing ∇f, curl, divergence)
- Flow / streamlines and trajectories from ODEs
- Animation as a first-class concept (Desmos approximates this with parameter looping)
- Python ecosystem integration (define surfaces using actual scipy/numpy functions)
- Color mapping based on a separate scalar function (e.g., color a surface by curvature or speed)
- Numerical methods visualized live (gradient descent paths, Newton trajectories, etc.)
