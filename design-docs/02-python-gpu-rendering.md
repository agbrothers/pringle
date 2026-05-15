# Python GPU Rendering: Options and Tradeoffs

## How WebGL / GPU Rendering Works

WebGL is the browser's API for GPU-accelerated graphics (based on OpenGL ES). The pattern:

1. **Upload data buffers** — arrays of vertices, normals, colors sent to GPU memory (VRAM)
2. **Upload shaders** — small programs in GLSL (C-like) that run in parallel on thousands of GPU cores
3. **Draw call** — the GPU runs the **vertex shader** (positions each point) and **fragment shader** (colors each pixel) simultaneously across all vertices/pixels

For animated surfaces, encoding the time parameter as a **GLSL uniform** (a single float sent per frame) means the GPU re-evaluates the entire surface without re-uploading vertex data. This is the key to smooth 60fps animation of parametric surfaces.

**Ray marching** (used by Desmos for implicit surfaces): a fragment shader fires a ray from the camera through each pixel and steps along it until it hits the surface `f(x,y,z) = 0`. Massively parallel — one ray per pixel — and never requires building a mesh. Enables interactive implicit surface rendering that CPU marching cubes cannot match.

## Python GPU Library Landscape

| Library | Abstraction | GPU API | Best For |
|---|---|---|---|
| `PyOpenGL` | Raw OpenGL | OpenGL | Full control; lots of boilerplate |
| `moderngl` | Pythonic OpenGL wrapper | OpenGL | Custom shaders without the boilerplate |
| `Vispy` | Scientific viz; `gloo` (low) + `scene` (high) | OpenGL | Mature, widely used in scientific Python |
| `wgpu-py` + `pygfx` | Scene graph on WebGPU | WebGPU | Modern API, Python-native, cross-platform |
| `PyVista` | Mesh/surface viz wrapping VTK | OpenGL (via VTK) | Easy mesh generation, marching cubes built in |
| `Mayavi` | High-level scientific viz | OpenGL (via VTK) | Powerful but heavy dependency |

## Recommended Options

### Option A: Vispy (mature, safe choice)
- Two-level API: `gloo` for raw GLSL shaders, `scene` for cameras/lights/interaction
- Supports embedding in PyQt, wxPython, or a standalone window
- Active community, stable API, extensive examples
- Custom shader support means Desmos-style GPU evaluation is achievable
- **Limitation**: OpenGL (not WebGPU); the API feels dated compared to modern GPU APIs

### Option B: wgpu-py + pygfx (modern, forward-looking)
- `wgpu-py` is the Python binding for WebGPU — the direct successor to both WebGL and OpenGL
- `pygfx` is a 3D scene graph built on it (essentially a Python Three.js)
- Designed explicitly for scientific visualization
- Cross-platform (Windows, Mac, Linux) without OS-specific OpenGL quirks
- Supports compute shaders natively (useful for grid evaluation on GPU)
- **Limitation**: newer project (~2022 onward), smaller community, less documentation

### Option C: PyVista (easiest for mesh-based surfaces)
- Wraps VTK; handles marching cubes, surface normals, mesh smoothing out of the box
- Excellent for explicit `z = f(x,y)` and implicit surfaces
- Built-in interactive viewer with orbit controls
- **Limitation**: limited custom shader access — less suited for GPU-side expression evaluation or ray marching

## Recommended Stack for Pringle

**3D viewport**: Vispy or pygfx/wgpu-py
**UI panels** (expression editor, sliders): Dear PyGui or PyQt6, with the GPU canvas embedded
**Implicit surfaces** (first version): PyVista's marching cubes on CPU, or a custom ray-march fragment shader later

### Performance Model for Animated Surfaces

| Approach | Re-render cost | Notes |
|---|---|---|
| CPU numpy eval + buffer re-upload | ~5–20ms per frame at 256×256 | Fine for 30fps; straightforward |
| GLSL uniform (t encoded in shader) | ~0.1ms per frame | Expression must be compiled to GLSL |
| GPU compute shader (grid eval on GPU) | ~1–2ms per frame | Flexible; expression compiled to WGSL/GLSL compute |

The CPU approach is the right starting point. GLSL compilation can be added later as an optimization for smooth animation.

## Decision: pygfx + wgpu-py

**pygfx** is the chosen rendering backend for Pringle. See `05-architecture-decisions.md` for full rationale. Key factors: clean material system, correct line width on macOS, WBOIT transparency, WebGPU future-proofing.

Implicit surfaces are deferred to v2. Shader compilation of expressions is deferred to v2. CPU numpy + buffer re-upload is the v1 evaluation strategy.

## WASD Camera Controls

Both Vispy and pygfx support keyboard-driven camera navigation via key press event callbacks.

**pygfx implementation:** `OrbitController` handles mouse-based orbit. WASD is connected to controller methods in the canvas key event handler:

```python
def on_key_press(event):
    if event.key == "w":   controller.zoom(0.95)
    elif event.key == "s": controller.zoom(1.05)
    elif event.key == "a": controller.rotate(0, -0.05)
    elif event.key == "d": controller.rotate(0,  0.05)
    elif event.key == " ": controller.rotate(-0.05, 0)
    elif event.key == "shift": controller.rotate(0.05, 0)
```

The camera always orbits a center point (up is always up), preserving spatial orientation — essential for inspecting mathematical surfaces. A `FlyController` (first-person, WASD built-in) is available as an alternative mode for exploring enclosed regions or vector fields from inside.
