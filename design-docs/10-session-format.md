# Session Format (YAML)

## Overview

All Pringle session state is serialized to a portable YAML file. This enables:
- **Lightweight saves** — a session is a single human-readable file
- **Version control** — YAML diffs are meaningful and reviewable
- **Sharing** — send a `.yaml` file; open it in Pringle
- **Reproducibility** — exact cell content, slider values, and viewport state are captured

The YAML file is the source of truth for a session. The UI is a view over this file; saving writes the current UI state to it, loading reads it back.

## Actual File Structure (v1)

The on-disk format written and read by `pringle/session.py`:

```yaml
version: 1

grid:
  x_min: -5.0
  x_max: 5.0
  y_min: -5.0
  y_max: 5.0
  z_min: -5.0      # controls wireframe/axes visual z extent
  z_max: 5.0
  n: 64            # grid points per axis

cells:
  - id: "550e8400-..."
    type: equation          # equation | slider | data | folder
    source: "z = sin(x) * cos(y)"
    visible: true
    style:
      color: [0.22, 0.40, 0.88, 1.0]   # RGBA floats 0–1
    sub_cells:
      - type: constraint           # constraint | condition | initial_condition | recursion
        source: "x**2 + y**2 < 4"

  - id: "..."
    type: slider
    source: "a = 2"
    name: "a"
    value: 2.0           # current position (may differ from source if dragged)
    min_val: 0.0
    max_val: 10.0
    step: 0.1
    style:
      color: [0.85, 0.33, 0.33, 1.0]
    sub_cells: []

  - id: "..."
    type: data
    source: |
      T = linspace(0, 10, 100)
      path = zeros((100, 3))
    style:
      color: [0.33, 0.75, 0.41, 1.0]
    sub_cells:
      - type: initial_condition
        source: "path[0] = array([1.0, 0.0, 0.0])"
      - type: recursion
        source: "path[n] = path[n-1] * 0.95"

  - id: "..."
    type: folder
    name: "Helper Functions"
    collapsed: false
    style:
      color: [0.55, 0.55, 0.55, 1.0]
    sub_cells: []
```

## Cell Types

| `type` | Description |
|---|---|
| `equation` | Any expression — surface, curve, scatter, parametric, lambda, or comment. Auto-detected at eval time. |
| `slider` | Scalar assignment detected as `name = value`. Has additional `name`, `value`, `min_val`, `max_val`, `step` fields. |
| `data` | Arbitrary numpy/scipy code, run on demand via ▷. Can have `initial_condition` and `recursion` sub-cells for recurrence patterns. |
| `folder` | Collapsible group. Has `name` and `collapsed` fields; no source. |

## Sub-cell Types

| `type` | Used on | Description |
|---|---|---|
| `constraint` | equation | Boolean mask; sets z=NaN where False |
| `condition` | equation | Piecewise branch selector |
| `initial_condition` | data | Seed value for a recurrence |
| `recursion` | data | Recurrence rule, e.g. `path[n] = path[n-1] * 0.9` |

## Style Fields

Only `color` (RGBA) is currently persisted per cell. The `CellStyle` also holds `line_width`, `point_size`, and `opacity`, but these are not yet saved/loaded (they reset to defaults on reload).

Default palette (assigned cyclically):
```python
PALETTE = [
    (0.22, 0.40, 0.88, 1.0),   # blue
    (0.13, 0.53, 0.20, 1.0),   # green
    (0.82, 0.18, 0.18, 1.0),   # red
    (0.55, 0.55, 0.55, 1.0),   # gray (data cells)
]
```

## Grid Config

`z_min`/`z_max` control how the wireframe bounding box and axis overlays are drawn in the 3D scene. They do **not** affect expression evaluation (which only uses `x`, `y` grids). Changing them via the Axis Bounds panel and clicking "Apply Bounds" updates the overlay immediately without re-evaluating cells.

## Versioning

The `version: 1` field enables future migration. `load_session` raises `ValueError` for unrecognised version numbers. Old sessions without `z_min`/`z_max` default to ±5.0.

## Diff Example

A YAML diff for changing a slider range is readable:

```diff
   type: slider
   source: "a = 2"
-  max_val: 10.0
+  max_val: 20.0
```

This makes session history meaningful in git — each commit represents a meaningful state of the visualization.
