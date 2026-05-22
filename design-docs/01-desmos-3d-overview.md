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
7. **Inertia / momentum rotation**: releasing the mouse while rotating causes the figure to continue spinning at the release velocity and gradually decelerate to a stop. See below.

## Interactivity Model

- **Reactive dependency graph**: expressions form a DAG. Changing slider `a` invalidates any surface referencing `a` and triggers re-evaluation + re-render.
- **Sliders**: any bare assignment (`a = 1`) gets a slider automatically. Dragging streams updates at 30–60 fps.
- **Real-time compilation**: expression string → AST → JS code → evaluated in a loop. Fast enough to happen on every keystroke.
- **View settings panel**: axis bounds, grid visibility, labels — separate from the expression system, just reconfigure the viewport.
- **Parameter animation**: a parameter can be set to loop over a range, driving time-varying behavior without explicit animation logic.

### Camera Inertia (Momentum Rotation)

When the user releases the mouse during an orbit drag, Desmos does not stop the rotation instantly. Instead, the scene continues spinning at the release velocity and decelerates smoothly to a stop. The mechanics:

1. **Velocity sampling during drag**: While the pointer is held, every `pointermove` event records a `(Δazimuth, Δelevation, Δtime)` sample. Only the most recent samples — typically covering a trailing window of ~80–150 ms — are kept. This filters out the initial acceleration phase and captures only the instantaneous "flick" velocity at the moment of release.

2. **Velocity at release**: On `pointerup`, the sampled window is averaged to produce an angular velocity vector `(ω_az, ω_el)` in radians per second (spherical coordinates).

3. **Coast loop**: Each animation frame after release, the scene is rotated by `ω_az * dt` and `ω_el * dt` (where `dt` is the frame delta in seconds). The velocity is then multiplied by an exponential decay factor:
   ```
   ω *= decay^dt     # e.g. decay = 0.90 per second, in the form pow(0.90, dt)
   ```
   This gives a frame-rate-independent exponential deceleration that feels natural at any display refresh rate.

4. **Stop threshold**: When `|ω|` falls below a small threshold (e.g. `0.01 rad/s`), the coast loop terminates and the camera is fully at rest.

5. **Interruption**: Any new pointer-down event immediately cancels the coast and transfers control back to direct drag. Touch pinch-zoom similarly cancels coasting.

The net effect: slow deliberate releases produce a gentle glide; fast flicks produce a prolonged spin. This is the standard "throw" gesture pattern, also used in iOS list scrolling and most 3D design tools (Blender's "Auto Smooth" orbit, Three.js `OrbitControls.enableDamping`).

## Key Design Tradeoffs

| Decision | Desmos' choice | Alternatives |
|---|---|---|
| Math → code | Compile to JS, eval numerically | Symbolic (SymPy), interpret AST |
| 3D rendering | Custom WebGL (no Three.js) | Three.js, Babylon.js |
| Implicit surfaces | Ray marching in fragment shader (likely) | CPU marching cubes |
| UI framework | React + WebGL canvas | Pure canvas, SVG |
| Animated surfaces | GLSL uniforms updated per frame | CPU re-evaluation + buffer re-upload |
| Float precision | 64-bit in JS; 32-bit in GLSL | Trade-off: 32-bit is faster but causes artifacts at large coordinates |

## Visual Styling

Each expression cell has a colored dot that opens a per-expression style panel. Controls vary by expression type:

| Control | Applies to | Notes |
|---|---|---|
| Color (preset swatches + hex input) | All types | Stored as rendering metadata, passed as a shader uniform — no expression re-evaluation |
| Opacity (0–100%) | Surfaces | Alpha channel; requires sorted or OIT blending for multiple overlapping surfaces |
| Line width | Curves, wireframe overlay | WebGL `gl_LineWidth`; clamped to 1px on many modern drivers — usually implemented as textured quads |
| Point size | Scatter | Passed as a vertex attribute or uniform |
| Line style (solid / dashed / dotted) | Curves | Implemented as a texture-based dash pattern in the fragment shader |
| Display mode | Surfaces | Filled, wireframe, or both; wireframe is a second render pass with polygon offset to prevent z-fighting |
| "Reverse contrast" | Surfaces | Inverts surface shading for readability on dark backgrounds |
| Label visibility | All types | Toggles the expression's text label in the viewport |

Style properties are stored separately from the expression string — they are rendering metadata attached to each cell. Changing a color or opacity does not re-evaluate the expression; it only updates a shader uniform. This makes style changes instantaneous.

## Organization Features

### Folders

Desmos allows expressions to be grouped into named, collapsible folders.

**Behavior:**
- A `+ Folder` button in the expression panel creates a new folder header.
- Each expression has an explicit `folderId` property; dragging a cell into a folder sets its `folderId`. Cells with no `folderId` are at the top level.
- The folder header shows a colored dot, an editable name, and a ▶/▼ collapse arrow.
- **Collapse:** clicking the arrow hides all member cells from the expression panel. The cells continue to evaluate and render — collapsing is purely a panel UI operation, not a visibility change.
- **Folder visibility toggle:** the folder header also has an eye icon. Toggling it off suppresses rendering for all member cells without changing their individual visibility flags. This is additive — a cell is rendered only if both its own visibility and its folder's visibility are on.
- **Indentation:** member cells are visually indented under the folder header (a thin colored left border or left margin) when the folder is expanded.
- **No nesting:** Desmos does not support folders inside folders.
- **Drag to reorganize:** cells can be dragged out of a folder back to the top level or into a different folder. The folder itself can be dragged to reorder it within the panel.
- **Folder drag moves members as a unit:** when a folder header is dragged to a new position, all of its member cells follow immediately after it — both when the folder is expanded and when it is collapsed. The member cells maintain their original relative order. After the move, the folder lands at the drop position with all members stacked below it, as if the folder+members are a single block. Dragging an individual member cell out of the block removes it from the folder and places it at the drop target as a top-level cell.
- **Drop indicator placement:** the blue drop indicator line always represents where the folder header will land; members are implied to follow. The indicator never appears in the middle of a multi-line cell — it snaps to the gap between cells.

### Comment Cells

Desmos supports note/comment cells as a distinct cell type (separate from the expression evaluator). In Desmos 2D the cell type is `"text"`; in Desmos 3D it behaves the same way.

**Behavior:**
- Created by selecting "Note" from the `+` add menu, or in some versions by typing a `#` or `"` as the first character.
- A comment cell is pure free text — it is never evaluated, never contributes to the namespace, and has no visibility toggle or color dot.
- The cell wraps text and grows vertically as content is added.
- Visually distinct from expression cells: typically italic, gray, or a lighter font weight.
- Useful for labeling groups of expressions, documenting parameter choices, or leaving scratch notes.

---

## What Desmos 3D Does Not Support

These are gaps a Python clone could address:

- Vector fields (arrows at grid points showing ∇f, curl, divergence)
- Flow / streamlines and trajectories from ODEs
- Animation as a first-class concept (Desmos approximates this with parameter looping)
- Python ecosystem integration (define surfaces using actual scipy/numpy functions)
- Color mapping based on a separate scalar function (e.g., color a surface by curvature or speed)
- Numerical methods visualized live (gradient descent paths, Newton trajectories, etc.)
