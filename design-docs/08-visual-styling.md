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

| Property | Surface | Curve | Scatter | Vectors | Notes |
|---|---|---|---|---|---|
| Color | ✓ | ✓ | ✓ | ✓ | RGBA; hex input + color swatch |
| Opacity | ✓ | ✓ | ✓ | ✓ | |
| Size | — | ✓ | ✓ | — | Single control sets both `line_width` and `point_size` (world-space units) |
| Colormap | ✓ | ✓ | ✓ | — | Named matplotlib colormap; overrides flat color when selected |
| Colormap reversed | ✓ | ✓ | ✓ | — | ⇄ toggle next to swatch row |
| Render mode | — | — | ✓ | — | Mutually exclusive radio: Circles / Line / Spheres |
| Normalize arrows | — | — | — | ✓ | Pin all arrows to equal length |
| Line style | — | ✓ | — | — | Solid / dashed / dotted (future) |
| Display mode | ✓ | — | — | — | Filled / wireframe / both (future) |

**Size** is a unified control: changing it in the style popover sets both `line_width` (for curves/wireframe) and `point_size` (for scatter dots) to the same value. This keeps the UI simple and ensures consistent visual weight across render types.

## CellStyle Data Model

```python
from dataclasses import dataclass

@dataclass
class CellStyle:
    color: tuple = (0.22, 0.40, 0.88, 1.0)  # RGBA floats 0–1
    opacity: float = 1.0
    line_width: float = 0.05   # world-space units; curves/wireframe
    point_size: float = 0.1    # world-space units; scatter dots
    colormap: str | None = None             # matplotlib colormap name; None = flat color
    colormap_reversed: bool = False
    scatter_render_mode: str = "circles"    # "circles" | "line" | "spheres"
    normalize_arrows: bool = False          # pin all flow/vector arrows to equal length
    show_critical_points: bool = False      # overlay critical point markers on surfaces
```

`line_width` and `point_size` are separate fields internally but exposed as a single "Size" control in the popover (range 0.005–2.0, step 0.005, 3 decimal places). Line width and point size use **world-space units** (`thickness_space="world"`, `size_space="world"` in pygfx materials) so they scale consistently with zoom level. Overlay objects (axes, bbox, crosshair) remain in screen space.

All `CellStyle` fields are serialized to YAML on save and restored on load. Default colors are assigned from a preset palette (cycling as cells are added).

The style popover (`StylePopoverWidget`) shows a two-column layout when `show_render_mode=True` (data cells): the left column holds Color/Opacity/Size spinboxes; the right column holds Circles/Line/Spheres radio buttons. A colormap swatch row (5 gradient buttons, 48×28 px each, rendered via matplotlib) and a ⇄ reverse toggle appear below. Clicking the active swatch deselects it (reverts to flat color).

## Implementation: pygfx

pygfx is the rendering backend. Vispy was evaluated during design but not used. pygfx uses an explicit Material system analogous to Three.js:

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
- Line width works correctly (lines rendered as world-space quads, not GL lines)
- Transparency is handled via WBOIT — no manual sorting needed

## Display Mode: Wireframe Overlay

When `display_mode == "both"`:
- The surface mesh is rendered first (filled, with Phong shading)
- A second draw call renders wireframe edges on top

In pygfx this is two materials on two Mesh objects sharing the same geometry. In Vispy it requires a `MeshVisual` for the filled pass and a `Line` or second `Mesh` with `mode='lines'` for the wireframe, plus a polygon offset to prevent z-fighting between the two passes.

## Transparency

Opacity < 1.0 is fully supported via **Weighted Blended OIT (WBOIT)**. When `opacity < 1.0`, materials are constructed with `alpha_mode="weighted_blend"` — pygfx accumulates weighted color contributions from all transparent fragments at each pixel and resolves them in a single post-pass. This is order-independent: self-overlapping surfaces, intersecting transparent meshes, and multiple transparent objects all render correctly without triangle-order artifacts.

`alpha_mode="auto"` (the default when `opacity == 1.0`) uses standard depth write for correct z-occlusion of opaque geometry.

## Session Persistence

`CellStyle` is serialized alongside the cell's expression content in the session file (JSON). When a session is loaded, styles are restored and applied to the visual objects before the first render.
