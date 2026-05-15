# Session Format (YAML)

## Overview

All Pringle session state is serialized to a portable YAML file. This enables:
- **Lightweight saves** — a session is a single human-readable file
- **Version control** — YAML diffs are meaningful and reviewable
- **Sharing** — send a `.pringle.yml` file; open it in Pringle
- **Reproducibility** — exact cell content, slider values, and viewport state are captured

The YAML file is the source of truth for a session. The UI is a view over this file; saving writes the current UI state to it, loading reads it back.

## File Structure

```yaml
pringle_version: "0.1.0"

viewport:
  x_range: [-3.5, 3.5]
  y_range: [-3.5, 3.5]
  z_range: [-2.8, 3.3]
  grid: true
  labels: true
  background: [0.1, 0.1, 0.1]   # RGB
  camera:
    azimuth: 45.0
    elevation: 30.0
    distance: 8.0

equation_panel:
  - id: "eq-001"
    type: surface             # surface | curve | scatter | piecewise | lambda | slider | comment | folder
    expression: "z = a*x**2 + b*y**2"
    visible: false
    style:
      color: [0.2, 0.4, 0.9, 1.0]   # RGBA
      opacity: 1.0
      line_width: 1.5
      point_size: 6.0
      line_style: solid              # solid | dashed | dotted
      display_mode: filled           # filled | wireframe | both
      show_label: true
    constraints: []

  - id: "eq-002"
    type: piecewise
    expression: "z = [f, g, h]"
    visible: true
    style:
      color: [0.9, 0.4, 0.2, 1.0]
      display_mode: filled
    conditions:
      - "x**2 + y**2 < 1"
      - "x**2 + y**2 < 2"
      - "x**2 + y**2 >= 2"

  - id: "eq-003"
    type: surface
    expression: "z = sin(x) * cos(y)"
    visible: true
    style:
      color: [0.3, 0.8, 0.4, 1.0]
      display_mode: both             # filled + wireframe
      line_width: 0.8
    constraints:
      - "x**2 + y**2 < 4"

  - id: "eq-004"
    type: slider
    expression: "a = 0.6"
    config:
      min: 0.0
      max: 2.0
      step: null                     # null = continuous
      animation: loop                # static | loop | bounce | once
      speed: 1.0                     # units per second
      reflect: false

  - id: "eq-005"
    type: slider
    expression: "t = 0"
    config:
      min: 0.0
      max: 10.0
      step: null
      animation: loop
      speed: 1.0
      reflect: false

  - id: "eq-006"
    type: lambda
    expression: "f(x,y) = x**2 + y**2"
    visible: true
    style:
      color: [0.7, 0.3, 0.9, 1.0]

  - id: "eq-007"
    type: comment
    content: "This block demonstrates piecewise surface rendering."

  - id: "eq-008"
    type: folder
    label: "Helper Functions"
    collapsed: false
    visible: true
    children: ["eq-006"]

data_panel:
  - id: "data-001"
    type: data
    expression: |
      step = 1
      T = arange(0, 10 + step, step)

  - id: "data-002"
    type: recurrence
    expression: "path = zeros((10, 2))"
    initial_condition: "array([1.0, 0.1])"
    recursion: "path[n] = 2 * path[n-1]"

  - id: "data-003"
    type: data
    expression: "height = g(path)"
```

## Cell Type Values

| `type` | Panel | Description |
|---|---|---|
| `surface` | equation | Explicit `z = f(x,y)` or auto-render from `f(x,y) = ...` |
| `curve` | equation | `y = f(x)` or `x = f(y)` |
| `scatter` | equation | `points = ...` or bare (N,3) array |
| `piecewise` | equation | `z = [f, g, h]` with condition sub-cells |
| `parametric` | equation | `xyz = ...` |
| `lambda` | equation | `f(x,y) = expr` definition; optionally auto-renders |
| `slider` | equation | Scalar assignment with drag handle |
| `comment` | equation | Bare string literal; text annotation |
| `folder` | equation | Collapsible group with `children` list of IDs |
| `data` | data | Arbitrary numpy/scipy setup code |
| `recurrence` | data | Array with `initial_condition` and `recursion` sub-cells |

## Style Defaults

```yaml
style_defaults:
  color_palette:           # assigned cyclically to new cells
    - [0.24, 0.42, 0.78, 1.0]   # blue
    - [0.85, 0.33, 0.33, 1.0]   # red
    - [0.33, 0.75, 0.41, 1.0]   # green
    - [0.89, 0.65, 0.24, 1.0]   # amber
    - [0.62, 0.38, 0.85, 1.0]   # purple
    - [0.24, 0.73, 0.84, 1.0]   # teal
  opacity: 1.0
  line_width: 1.5
  point_size: 6.0
  line_style: solid
  display_mode: filled
  show_label: true
```

## Versioning and Compatibility

The `pringle_version` field enables future migration. When loading a file with an older version, Pringle applies a migration chain to bring the format up to the current schema. Breaking changes increment the minor version; additive changes do not.

## Diff Example

A version-controlled YAML diff for changing a slider range is readable:

```diff
   - id: "eq-004"
     type: slider
     expression: "a = 0.6"
     config:
-      max: 2.0
+      max: 5.0
       animation: loop
```

This makes session history meaningful in git — each commit represents a meaningful state of the visualization.
