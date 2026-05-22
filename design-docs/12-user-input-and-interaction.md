# User Input and Interaction

## 3D Viewport: Mouse Controls

| Action | Gesture | Notes |
|---|---|---|
| Orbit | Left-click drag | Rotates around scene center; "up" is always up (orbit model, not free-look) |
| Pan | Right-click drag or Middle-click drag | Translates the camera laterally |
| Zoom | Scroll wheel | Moves camera toward/away from orbit center |
| Reset view | Double-click viewport (or "Recenter" button) | Snaps to default isometric view |

All three are handled by pygfx's `OrbitController` with default bindings — no custom code needed. The orbit-around-center model is correct for inspecting mathematical surfaces; it prevents disorienting roll and keeps axes readable.

## 3D Viewport: Keyboard Controls (WASD)

WASD pans the **orbit target** — the point the camera orbits around and zooms toward — in the **camera's horizontal reference frame**. The camera translates by the same delta so its angle and distance to the target are preserved.

| Key | Movement |
|---|---|
| `W` | Forward in camera's horizontal frame (toward target projected onto XY) |
| `S` | Backward |
| `A` | Left (camera-relative) |
| `D` | Right (camera-relative) |
| `Space` | +Z (world up, unconditional) |
| `Shift` | −Z (world down, unconditional) |

"Forward" is the camera-to-target vector projected onto the XY plane and normalized. "Right" is forward rotated 90° clockwise. When the camera is directly overhead (forward XY magnitude < 1e-6), forward falls back to world +Y.

**Step size** scales with the camera's current distance to the target (0.7% per frame at 60 fps), giving consistent feel whether zoomed in or out.

**Key handling is at the Qt level** (`keyPressEvent`/`keyReleaseEvent` on `PringleViewport`), not through wgpu's event system. `event.accept()` suppresses the macOS press-and-hold accent character popover. `focusOutEvent` clears held keys to prevent stuck movement when focus switches to the expression panel.

**Known limitation:** pygfx's `OrbitController` right-drag pan moves the camera view but does not update `controller.target`. After a mouse pan, the WASD orbit target may differ from the visual center. WASD always operates relative to `controller.target`.

### Orbit Target Crosshair

A small three-axis crosshair is rendered at `controller.target` and updated every frame. It shows:
- Short red/green/blue arms along ±X, ±Y, ±Z (colors match the main axis lines but muted)
- Arm length = 2.5% of the maximum axis range

The crosshair makes the orbit pivot visible during WASD panning and mouse orbiting. It can be toggled independently via the **Crosshair** checkbox in the View Settings overlay section.

## View Settings (Axis Settings Dialog)

Clicking the ⚙ gear icon in the top-right corner of the viewport opens a floating non-modal **Axis Settings dialog** (`AxisSettingsDialog`). It is not embedded in the left panel or below the viewport. Clicking ⚙ again or the dialog's X button closes it.

### Axis Bounds

Six numeric input fields — min and max for each axis:

```
X  [ -5 ] to [ 5 ]
Y  [ -5 ] to [ 5 ]
Z  [ -5 ] to [ 5 ]
```

Clicking **"Apply Bounds"** after editing:
- Regenerates the spatial grid (`np.linspace` with new x/y bounds) and re-evaluates all cells
- Updates the wireframe bounding box and axis overlay extents using the z bounds

Note: z bounds control only the visual overlay (wireframe box, axis lines) — they do not affect expression evaluation, since the grid is 2D (x, y only).

**"Equalize Axes"** sets x and y to `[−z_span/2, +z_span/2]` where `z_span = z_max − z_min`. This gives all three axes equal length, useful after evaluating a function to match the data range. Z bounds are left unchanged.

### Parametric Grid Bounds

Separate inputs for `(u, v)` grid used by parametric surfaces:

```
U  [ 0 ] to [ 6.283 (2π) ]
V  [ 0 ] to [ 6.283 (2π) ]
```

### Grid Resolution

A single slider or numeric input controlling grid resolution (shared by `x,y` and `u,v` grids):

```
Resolution  [ 64 ] ──●────  (8 – 256)
```

### Toggle Controls

| Toggle | Default | Notes |
|---|---|---|
| Axes | On | X/Y/Z axis lines through origin (red/green/blue) |
| Wireframe | On | 12-edge bounding box at axis extents |
| Crosshair | On | Small three-axis indicator at the orbit target |
| Shadow | Off | Flat projection of scene objects onto the z_min floor plane |
| Light bg | Off | Toggles viewport background between dark and light |

All toggle states persist in the session `view` YAML block.

### Camera Presets

Row of buttons: **Isometric**, **Top** (looking down -Z), **Front** (looking at XZ plane), **Side** (looking at YZ plane), **Reset**. Each snaps the `OrbitController` to a predefined quaternion/position.

### Step Size (Grid Lines)

Optional: a numeric input controlling the spacing between grid lines. Defaults to auto-computed from axis range (nice round numbers: 1, 2, 5, 10...). A "Auto" checkbox re-enables auto-computation after manual override.

---

## Expression Panel: Cell Interaction

### Selection and Focus

- **Click anywhere on a cell** → selects the cell; keyboard focus moves to that cell's text input
- Focused cell has a visible border highlight
- One cell is always focused (the most recently clicked or created)
- **Tab** → moves focus to the next cell below; **Shift+Tab** → moves focus up
- **Escape** → deselects (removes focus from all cells); focus returns to the viewport

### Text Editing Within a Cell

Standard text editor behavior in a `QPlainTextEdit`:
- Arrow keys, Home/End, Ctrl+A select all, etc.
- Multi-line input is allowed — the cell expands vertically as content grows
- **Enter / Return**: if the cursor is at the end of the cell content, creates a new empty cell directly below and moves focus there. If the cursor is mid-text (not at end), inserts a newline within the cell.

This matches Desmos behavior: Enter always advances to the next cell when you're done typing an expression, but allows multi-line blocks within one cell.

### Cell Deletion

- **Backspace on an empty cell** → deletes the cell and moves focus to the cell above
- **Delete key on a non-empty cell** → standard text deletion (no cell removal)
- A small **✕ button** appears on hover at the top-right of the cell for explicit deletion (shows a confirmation if the cell has content)

### Cell Reordering

Each cell has a **drag handle** on its left edge. Dragging reorders cells within the unified cell list. A blue indicator line shows the insertion point during drag. Visual order is cosmetic; the dependency graph re-sorts automatically on next evaluation.

Dragging a **folder header** moves the entire folder+members block as a unit. Members maintain their relative order after the move. Hidden (collapsed) members are skipped in drop-target computation so the indicator always lands at a visible cell boundary.

### Undefined Variable Suggestion

When a cell references a name not defined anywhere in the session:

```
⚠  'a' is not defined    [+ Add slider for 'a']
```

Clicking the suggestion button inserts a new slider cell for `a` with default value `1.0` and range `[0, 10]`. This matches Desmos's inline suggestion behavior.

---

## Sub-Cell Interactions

### Adding Sub-Cells

A **"+" button** appears at the bottom-left of a focused equation cell. Clicking it opens a small dropdown:
- Add Constraint
- *(future: Add Color Function)*

Selecting "Add Constraint" appends a constraint sub-cell below the primary cell, indented slightly and marked with a visual indicator (e.g., a filter icon or dashed left border).

### Constraint Sub-Cell

- Standard text input; evaluates a boolean expression with `x`, `y`, and the computed magic variable (`z`, `xyz`, etc.) in scope
- Visual indicator: dashed left border + filter icon (🔽 or similar)
- Error styling if the expression doesn't return a boolean array
- Remove button (✕) on hover

---

## Global Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Z` | Undo (cell content changes + cell additions/deletions) |
| `Ctrl+Shift+Z` or `Ctrl+Y` | Redo |
| `Ctrl+S` | Save session to current YAML file |
| `Ctrl+Shift+S` | Save As (open file dialog) |
| `Ctrl+O` | Open session (file dialog) |
| `Ctrl+N` | New empty session |
| `Ctrl+Enter` | Force re-evaluate focused cell (useful for data cells) |
| `F` | Toggle first-person fly mode in viewport |
| `Ctrl+[` / `Ctrl+]` | Collapse / expand focused folder cell |

---

## Panel Dividers (Draggable Splits)

One draggable split:

1. **Left/Right**: the vertical divider between the left panel (unified cell list) and the 3D viewport. Default left-panel width is 480 px. Drag to resize.

The View Settings is a floating dialog, not a panel section — no divider for it.

---

## Animation Controls

Animation is per-slider. Each slider cell has:

```
[▷ Play / ‖ Pause]  [↔ / ⟳ mode toggle]  [min] [──●──] [max]  · step [step]
```

- **▷ / ‖**: starts/stops bouncing the value between min and max at the step interval (~60 fps via `QTimer`)
- **↔ / ⟳**: toggles between ping-pong (bounces at boundaries) and loop (wraps directly back) mode
- Play state and mode are persisted in the session YAML (`is_playing`, `anim_mode`)
- On session load, sliders that were playing are restarted after the namespace is fully populated

There is no global animation bar or global `t` variable.

---

## Style Popover

Clicking a cell's **color dot** opens a compact popover. For data cells (`show_render_mode=True`), the popover uses a two-column layout:

```
┌──────────────────────────────────────────┐
│  Color   [#3866e0] [■]   (●) Circles     │
│  Opacity ────────  1.00  ( ) Line        │
│  Size    ────────  0.05  ( ) Spheres     │
│                                          │
│  Colormap:                               │
│  [viridis][plasma][inferno][hot][hsv][⇄] │
└──────────────────────────────────────────┘
```

For equation cells the render-mode column is omitted. Controls:

- **Color** — hex input + live swatch (updates on each valid 7-char `#rrggbb` edit)
- **Opacity** — range 0.05–1.0, step 0.05
- **Size** — unified control: sets both `line_width` (curves) and `point_size` (scatter). Range 0.005–2.0, step 0.005, world-space units
- **Render mode** — Circles / Line / Spheres radio buttons (data cells only; mutually exclusive)
- **Colormap** — 5 gradient swatch buttons (48×28 px, rendered via matplotlib); clicking the active swatch deselects (reverts to flat color). ⇄ button reverses the colormap

The popover is a `Qt.WindowType.Popup` frame; it closes on any click outside it.

---

## Missing UX Considerations Checklist

These are the areas not captured elsewhere that v1 should address before shipping:

| Concern | Recommended approach |
|---|---|
| **Undo/redo** | Qt's `QUndoStack`; track cell text changes, additions, deletions |
| **Copy/paste cells** | `Ctrl+C` / `Ctrl+V` on a selected cell; paste inserts below current cell |
| **Loading indicator** | Spinner or progress bar on cells actively computing (>100ms eval) |
| **Stale indicator placement** | Orange dot or "↻ stale" badge at the cell's top-right corner (data cells only) |
| **Error display** | Red text below the cell showing the Python exception message (truncated to one line; expandable) |
| **Run All button** | Prominent "▶▶ Run All" button at the top of the Data Panel; runs all data cells in dependency order |
| **New cell button** | "+" button at the bottom of each panel (below all cells) to add a new empty cell |
| **Session title** | Editable title in the window title bar; defaults to filename |
| **Unsaved changes indicator** | Asterisk (*) in title bar when session has unsaved changes |
| **Cell type label** | Small chip on data cells ("data") and recurrence cells ("recurrence") to distinguish from equation cells |
| **Empty session state** | A placeholder message in empty panels: "Press + to add an expression" |
| **Grid regeneration on bound change** | Changing axis bounds re-evaluates all spatial cells — show a brief loading indicator if >200ms |
| **Slider value display** | Show current numeric value next to the drag handle; double-click to type an exact value |
| **Visibility toggle position** | Eye icon (👁) at the right of the cell row, always visible (not just on hover) |
| **Folder cell** | A collapsible group; drag cells into/out of folders; folder has its own visibility toggle |
