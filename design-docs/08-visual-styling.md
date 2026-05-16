# Visual Styling

## User-Facing Interface

Each cell in the equation panel has a colored dot to its left — the cell's current primary color. Clicking it opens a style panel (popover or sidebar drawer). The style panel is identical in concept to Desmos's: a compact set of controls for that cell's visual properties. The user never needs to write styling into the expression itself.

```
● ─────────────────────────────────────────────
│  z = sin(x) * cos(y)          [👁] [✕]
│  [+ constraint]
●
  ↓ click the dot

  ┌─────────────────────────┐
  │  ● ● ● ● ● ● [custom]  │  ← color swatches
  │  Opacity  ──●──── 80%   │
  │  Width    ──●──── 1.5   │  ← for curves
  │  Display  [Filled ▾]    │  ← filled/wire/both
  │  Label    [✓ show]      │
  └─────────────────────────┘
```

Style properties are stored as rendering metadata on the cell — separate from the expression string. Changing a style property does not re-evaluate the expression; it only updates a material/uniform value. Style changes are instantaneous.

## Style Properties per Render Type

| Property | Surface | Curve | Scatter | Notes |
|---|---|---|---|---|
| Color | ✓ | ✓ | ✓ | RGBA; hex input + color swatch |
| Opacity | ✓ | ✓ | ✓ | |
| Size | wireframe only | ✓ | ✓ | Single control sets both line width and dot size |
| Line style | — | ✓ | — | Solid / dashed / dotted (future) |
| Display mode | ✓ | — | — | Filled / wireframe / both (future) |
| Label visibility | ✓ | ✓ | ✓ | Future |

**Size** is a unified control: changing it in the style popover sets both `line_width` (for curves/wireframe) and `point_size` (for scatter dots) to the same value. This keeps the UI simple and ensures consistent visual weight across render types.

## CellStyle Data Model

```python
from dataclasses import dataclass

@dataclass
class CellStyle:
    color: tuple = (0.22, 0.40, 0.88, 1.0)  # RGBA floats 0–1
    opacity: float = 1.0
    line_width: float = 2.0    # curves, wireframe; also set by the Size control
    point_size: float = 6.0    # scatter dots; also set by the Size control
```

`line_width` and `point_size` are separate fields internally but exposed as a single "Size" control in the popover. The popover initializes the spinbox from `line_width`; changing it updates both fields simultaneously.

This is trivially serializable to JSON for session persistence. The renderer reads from `CellStyle` when building or updating the visual object for the cell.

Default colors are assigned from a preset palette (cycling through it as cells are added), matching Desmos's behavior.

## Implementation: Vispy vs pygfx

### Vispy

Vispy visual objects accept color and style at creation and via property setters:

```python
# Surface
mesh = scene.visuals.Mesh(vertices, faces, color=style.color)
mesh.shading = "smooth"

# Curve
line = scene.visuals.Line(points, color=style.color, width=style.line_width,
                           connect="strip", method="agg")  # 'agg' for anti-aliased

# Scatter
scatter = scene.visuals.Markers()
scatter.set_data(points, face_color=style.color, size=style.point_size)
```

Updating a style property:
```python
mesh.color = new_color          # triggers shader uniform update; no geometry re-upload
line.set_data(color=new_color)
```

**Vispy line width caveat:** OpenGL ignores `glLineWidth` > 1px on macOS and many modern drivers. Using `method='agg'` renders lines as anti-aliased textured quads, which supports arbitrary width but is slower. Use `method='gl'` only for thin hairlines.

**Vispy transparency caveat:** multiple transparent surfaces require back-to-front sorting per frame (painter's algorithm) for correct blending. Vispy does not automate this for mesh visuals. For v1, treat opacity as a nice-to-have that works correctly for a single transparent surface at a time. Full OIT (order-independent transparency) is a v2 concern.

### pygfx (preferred for styling)

pygfx uses an explicit Material system analogous to Three.js:

```python
import pygfx as gfx

# Surface
material = gfx.MeshPhongMaterial(color=style.color, opacity=style.opacity)
mesh = gfx.Mesh(geometry, material)

# Wireframe overlay (display_mode == "both")
wf_material = gfx.MeshWireframeMaterial(color=style.color, thickness=style.line_width)
wf_mesh = gfx.Mesh(geometry, wf_material)

# Curve
line_material = gfx.LineMaterial(color=style.color, thickness=style.line_width)
line = gfx.Line(geometry, line_material)

# Scatter
points_material = gfx.PointsMaterial(color=style.color, size=style.point_size)
scatter = gfx.Points(geometry, points_material)
```

Updating a style property:
```python
material.color = new_color      # dirty-tracked; propagates to GPU automatically
material.opacity = new_opacity
```

**pygfx advantages for styling:**
- Material properties map 1:1 to what the style panel controls — very clean binding
- Line width works correctly (lines rendered as screen-space quads, not GL lines)
- Transparency is better handled (weighted blended OIT available)
- No manual sorting needed for transparent surfaces

pygfx is the preferred backend for styling specifically because of the cleaner material abstraction and the line width / transparency improvements.

## Display Mode: Wireframe Overlay

When `display_mode == "both"`:
- The surface mesh is rendered first (filled, with Phong shading)
- A second draw call renders wireframe edges on top

In pygfx this is two materials on two Mesh objects sharing the same geometry. In Vispy it requires a `MeshVisual` for the filled pass and a `Line` or second `Mesh` with `mode='lines'` for the wireframe, plus a polygon offset to prevent z-fighting between the two passes.

## Transparency (Nice-to-Have)

Opacity < 1.0 on surfaces requires careful blending:

- **Single transparent surface**: simple alpha blending works; no special handling needed
- **Multiple overlapping transparent surfaces**: requires correct back-to-front sorting or OIT
  - Painter's algorithm (sort meshes by camera depth): easy, correct for non-intersecting surfaces
  - Weighted blended OIT (WBOIT): approximate but fast, handles intersecting geometry; available in pygfx
- **v1 stance**: implement opacity as a style property; document that multiple overlapping transparent surfaces may show visual artifacts. Fix in v2 using WBOIT or depth sorting.

## Session Persistence

`CellStyle` is serialized alongside the cell's expression content in the session file (JSON). When a session is loaded, styles are restored and applied to the visual objects before the first render.
