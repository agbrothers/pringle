# User Input and Interaction

## 3D Viewport: Mouse Controls

| Action | Gesture | Notes |
|---|---|---|
| Orbit | Left-click drag | Rotates around scene center; "up" is always up (orbit model, not free-look) |
| Pan | Right-click drag or Middle-click drag | Translates the camera laterally |
| Zoom | Scroll wheel | Moves camera toward/away from orbit center |
| Reset view | Double-click viewport (or "Recenter" button) | Snaps to default isometric view |

Orbit, pan, and zoom are handled by `_PringleOrbitController` (a `gfx.OrbitController` subclass in `renderer.py`) for its math, but the event wiring uses a custom `_IncrementalOrbitHandler` (`renderer.py`) instead of `OrbitController.register_events()`. The stock event system snapshots camera state at drag-start; the custom handler calls `controller.rotate()` / `.pan()` / `.zoom()` with per-frame incremental pixel deltas so the controller always reads live camera state, enabling WASD and mouse orbit simultaneously (BUG-013). The orbit-around-center model prevents disorienting roll and keeps axes readable. `_PringleOrbitController` overrides `_update_rotate` to fix a pygfx v0.16.0 bug where elevation rotation was applied to camera orientation around the hardcoded world-X axis but to camera position around the actual world-space right vector — at non-zero azimuth these diverge, causing the scene to drift or spin during vertical drags (BUG-178).

**Orbit momentum (coasting):** On left-drag release, `_compute_coast_velocity()` averages the last 100 ms of drag samples to compute angular velocity (ω_az, ω_el) in rad/s. Two constants gate the coast: `_COAST_DEADZONE = 2.0` rad/s — drags below this speed produce no coasting (prevents accidental momentum from micro-adjustments); `_COAST_SCALE = 0.25` — velocities that exceed the deadzone are scaled down before storing, so coasting feels deliberate rather than 1:1 with raw drag speed. Coasting runs at constant velocity (no decay) until interrupted by a new pointer-down event. Camera-reading cells do not update during free orbit (the 100 ms poll was removed in ARCH-176); they update on the next slider move, cell edit, or grid change.

## 3D Viewport: Keyboard Controls (WASD)

WASD pans the **orbit target** — the point the camera orbits around and zooms toward — in the **camera's horizontal reference frame**. The camera translates by the same delta so its angle and distance to the target are preserved.

| Key | Movement |
|---|---|
| `W` / `↑` | Forward in camera's horizontal frame (toward target projected onto XY) |
| `S` / `↓` | Backward |
| `A` / `←` | Left (camera-relative) |
| `D` / `→` | Right (camera-relative) |
| `Space` | +Z (world up, unconditional) |
| `Shift` | −Z (world down, unconditional) |

"Forward" is the camera-to-target vector projected onto the XY plane and normalized. "Right" is forward rotated 90° clockwise. When the camera is directly overhead (forward XY magnitude < 1e-6), forward falls back to world +Y.

**Step size** scales with the camera's current distance to the target (0.7% per frame at 60 fps), giving consistent feel whether zoomed in or out.

**Key handling is at the Qt level** (`keyPressEvent`/`keyReleaseEvent` on `PringleViewport`), not through wgpu's event system. `event.accept()` suppresses the macOS press-and-hold accent character popover. `focusOutEvent` clears held keys to prevent stuck movement when focus switches to the expression panel.

**Note on right-drag pan:** `OrbitController._update_pan` does update `controller.target` when a custom target is set (which Pringle always uses), so mouse pan and WASD stay in sync.

### Orbit Target Crosshair

A small three-axis crosshair is rendered at `controller.target` and updated every frame. It shows:
- Short red/green/blue arms along ±X, ±Y, ±Z (colors match the main axis lines but muted)
- Arm length = 2.5% of the maximum axis range

The crosshair makes the orbit pivot visible during WASD panning and mouse orbiting. It can be toggled independently via the **Crosshair** checkbox in the View Settings overlay section.

## View Settings (Axis Settings Dialog)

The header bar (`PringleHeaderBar`) spans the full window width above the left/right splitter. Its layout (left to right): logo · **PRINGLE** wordmark · **New** · **Open** · **Save** · **Export** · stretch · **camera icon** (screenshot) · **globe icon** (view settings). File buttons use a pill style (`border-radius: 10px`). The **Save** button text and border turn `#E9A15F` when the session has unsaved changes. The **camera** button (SVG `camera-fill.svg`) saves a PNG snapshot of the current canvas frame, defaulting to `~/Downloads/pringle_screenshot.png`; its border flashes `#E9A15F` briefly on click. The **globe** button (SVG `globe.svg`) toggles the Axis Settings popover and turns blue (`#4a9eff`) when open. Both icon buttons are right-aligned after the stretch.

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
- One cell is always focused (the most recently clicked or created)
- **Tab** → moves focus to the next cell below; **Shift+Tab** → moves focus up
- **Escape** → deselects (removes focus from all cells); focus returns to the viewport

**Active-cell highlight (FEAT-148).** The cell whose subtree holds keyboard focus paints its body band `@active-cell-bg` (vs the `#111111` panel); all four cell types participate (equation/data, slider, folder header, comment). `CellListWidget` connects to the app-wide `QApplication.focusChanged` signal and toggles a dynamic `active` Qt property on the owning cell (`_on_focus_changed` → `_owning_cell` → `_set_active_cell`/`_mark_active`, which re-polishes the cell **and its subtree** so descendant QSS rules re-resolve). Behavior:
- **One active cell at a time**; focus moving between cells moves the highlight.
- **Clear-on-blur with sticky popovers**: the highlight clears when focus leaves the panel (viewport, header, another app), but persists while the cell's *own* pop-up/dialog is open (style popover, colour picker, slider controls) — those are parented to the cell, so `_active_cell_for` resolves the active cell from `QApplication.activePopupWidget()`/`activeModalWidget()` when no field holds focus.
- **Implementation note**: the band is painted by each cell's `#cell_content` container (named in every cell widget's `_build_ui`), scoped in `theme.qss` as `<CellType>[active="true"] #cell_content[, … QWidget]`. It is *not* painted on the cell root — a QSS `background` fills the whole widget rect ignoring the folder indent (a `contentsMargins`), so painting on the root would bleed `@active-cell-bg` into the indent strip. Scoping under `#cell_content` keeps the indent strip panel-coloured and prevents the recolor from leaking into the (root-parented) pop-ups. The swatch/drag-handle column keeps its own colour. Active state is transient UI only — never persisted to the session YAML.

### Text Editing Within a Cell

Standard text editor behavior in a `QPlainTextEdit`:
- Arrow keys, Home/End, Ctrl+A select all, etc.
- Multi-line input is allowed — the cell expands vertically as content grows
- **Enter / Return**: inserts a newline with auto-indent — the new line is pre-filled with the same leading whitespace as the current line. If the current line's stripped text ends with `:` (e.g. `def f():`, `for i in range(n):`, `if x > 0:`, `else:`, `try:`, `with …:`), one additional indent level (4 spaces) is added.
- **Shift+Enter**: creates a new empty equation cell directly below and moves focus there (from any cursor position).
- **Ctrl+Enter** (Cmd+Enter on macOS): creates a new folder cell directly below and moves focus there.
- **Home**: moves cursor to the first non-whitespace character on the current line. If the cursor is already there (or the line has no indent), moves to column 0. Matches VSCode/PyCharm smart-home behaviour.
- **Shift+Home**: same as `Home` but extends the selection anchor to the destination position.
- **Backspace** when the cursor is on a line whose content to the left is entirely spaces: deletes back to the previous 4-space tab stop (e.g. cursor at column 6 → deletes 2 spaces back to column 4; cursor at column 4 → deletes 4 spaces back to column 0). Falls through to normal single-character delete if any non-space precedes the cursor on the line.
- **Cmd+Delete** (macOS): deletes all text on the current line to the left of the cursor (kill to start of line). No-op when the cursor is already at the start of a block.
- **Cmd+]** (in a multi-line cell): indents every line overlapping the current selection by 4 spaces.
- **Cmd+[** (in a multi-line cell): outdents every line overlapping the current selection by up to 4 spaces.
- **Cmd+/** (in an equation or slider cell): toggles `# ` on the cursor's current line, or on every line that overlaps the selection. All toggled lines are treated as a single undo step. If the first line ends up starting with `#` after the toggle, the cell auto-morphs to a `CommentCellWidget`.
- **Cmd+/** (in a comment cell): cell-level uncomment — morphs the cell back to an equation cell (same as `Cmd+Option+/`).

These shortcuts apply to equation cells, comment cells, and all text fields on slider cells (value, min, max, name). Text-indent (`Cmd+]/[`) is a no-op on single-line fields (slider value, min, max, name) since there is nothing to indent.

- **Up arrow on first visual line / Down arrow on last visual line**: moves focus to the adjacent cell or subcell in the flat visual order (Jupyter-style cross-cell navigation). Pressing Up/Down on an interior visual line (including wrapped lines within a single logical block) moves the cursor within the cell normally without escaping. Boundary detection uses `QTextLayout.lineForTextPosition()` so that visually-wrapped single-block cells behave correctly.

**Cross-cell navigation flat order** (FEAT-053): `CellListWidget._focus_targets()` returns `(id, widget)` pairs in visual order — equation cell main edit, then its subcells in order, then next cell, etc. Folder headers are skipped; members of collapsed folders are excluded. Slider cells land on the `value` spinbox when navigated into. Navigation is a simple index ±1 lookup on this list.

**Within-slider arrow navigation:** Full keyboard traversal across all visible fields:

| From | Key | To |
|---|---|---|
| name | Right (at end) | value spinbox (cursor at 0) |
| name | Left (at pos 0) | cell above |
| name | Up / Cmd+Up | cell above |
| name | Down | min box |
| name | Cmd+Down | cell below (skips min/max row) |
| value spinbox | Left (at pos 0) | name field (cursor at end) |
| value spinbox | Up / Cmd+Up | cell above |
| value spinbox | Down | min box |
| value spinbox | Cmd+Down | cell below (skips min/max row) |
| min | Up | value spinbox |
| min | Down | cell below |
| min | Right (at end) | max box (cursor at 0) |
| max | Up | value spinbox |
| max | Down | cell below |
| max | Left (at pos 0) | min box (cursor at end) |

`step` is not in the layout (controls popover only) — no arrow-key navigation needed.

### Cell Deletion

- **Backspace on an empty cell** → deletes the cell and moves focus to the cell above
- **Delete key on a non-empty cell** → standard text deletion (no cell removal)
- A small **✕ button** appears on hover at the top-right of the cell for explicit deletion (shows a confirmation if the cell has content)

### Cell Reordering

Each cell has a **drag handle** on its left edge. Dragging reorders cells within the unified cell list. A blue indicator line shows the insertion point during drag. Visual order is cosmetic; the dependency graph re-sorts automatically on next evaluation.

Dragging a **folder header** moves the entire folder+members block as a unit. Members maintain their relative order after the move. Hidden (collapsed) members are skipped in drop-target computation so the indicator always lands at a visible cell boundary.

### Syntax Highlighting (FEAT-063 / FEAT-147)

`PringleHighlighter` (`syntax_highlighter.py`) is a `QSyntaxHighlighter` attached to every `CellTextEdit` document. It operates per-line via `highlightBlock`. Colors come from `syntax_theme.py`.

**Token → color table (GitHub Dark palette):**

| Token | Example | Color |
|---|---|---|
| Magic vars / grid inputs | `x`, `y`, `z`, `xyz`, `n` | `MAGIC_COLOR` `#E9A15F` |
| Whitelisted numpy/scipy functions | `sin`, `zeros`, `concatenate` | `FUNCTION_COLOR` `#D7BEF6` |
| Any identifier immediately before `(` | `bifurcate(...)`, `dE(...)` | `FUNCTION_COLOR` `#D7BEF6` |
| Identifier after `def` | `bifurcate` in `def bifurcate(...)` | `FUNCTION_COLOR` `#D7BEF6` |
| Function parameters (signature + body) | `memories`, `k`, `β` throughout cell | `MAGIC_COLOR` `#E9A15F` |
| Numeric literals | `42`, `3.14`, `1e-6` | `NUMBER_COLOR` `#7DB4F9` |
| Literal constants | `None`, `True`, `False` | `NUMBER_COLOR` `#7DB4F9` |
| Control-flow keywords | `def`, `for`, `return`, `if`, … | `OPERATOR_COLOR` `#EC7C6F` |
| Arithmetic / comparison operators | `+`, `*`, `<=`, `!=` | `OPERATOR_COLOR` `#EC7C6F` |
| Rainbow brackets | `(`, `[`, `{` (depth-colored) | `RAINBOW_BRACKETS` |
| Inline `#` comments | `## BUILD OUTPUT DATA` | `COMMENT_COLOR` `#79838E` |

**Keyword set** (`def return for while continue break not in if elif else and or is pass lambda del assert raise try except finally with as`). Intentionally excludes `import`/`from`/`class`/`async`/`yield` — blocked by the safety layer and would mislead users.

**Argument scoping.** On every `contentsChanged`, `safety.get_param_names()` parses the cell source and extracts all `def`/lambda parameter names. If the set changes, `rehighlight()` recolors the entire cell body. This is cell-wide (a same-named free variable outside the function also gets `MAGIC_COLOR`) — per-function scoping deferred to v2.

**Pass ordering in `highlightBlock`** (later passes override earlier on overlapping spans):
1. Static rules (magic → func → number → literals → keywords → operators), code region only
2. Function-call pattern (identifiers before `(`, skipping keywords and magic names)
3. `def`-name pass (identifier after `def` keyword)
4. Argument-names pass (arg names win over whitelisted function names)
5. Rainbow brackets, code region only
6. Comment span (last — overwrites everything inside `#…`)

Brackets inside a `#` comment do not change rainbow nesting depth.

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
| `Ctrl+Shift+E` | Export session as standalone Python script (native save dialog, defaults to same name as current session with `.py` extension) |
| camera toolbar button | Save current canvas frame as PNG (native save dialog, defaults to `~/Downloads/pringle_screenshot.png`) |
| `Ctrl+Enter` / `Cmd+Enter` | Add new folder cell below focused cell (in the expression panel); force re-evaluate focused cell when focus is on the viewport |
| `Shift+Enter` | Add new equation cell below focused cell (in the expression panel) |
| `Cmd+/` | **In equation/slider cell:** toggle `# ` on current line or all selected lines (single undo step). **In comment cell:** cell-level uncomment — morphs back to equation/slider. |
| `Cmd+Option+/` (macOS) / `Cmd+Shift+/` (other) | **Cell-level comment toggle:** morph focused equation/slider cell → `CommentCellWidget`, or comment cell → equation/slider. With a multi-line selection, strips `# ` from every selected line on uncomment. |
| `Ctrl+[` / `Ctrl+]` | Collapse / expand focused folder cell |
| `Cmd+]` | **In a text cell:** indent selected lines by 4 spaces. **In a slider field:** no-op. |
| `Cmd+[` | **In a text cell:** outdent selected lines by up to 4 spaces. **In a slider field:** no-op. |
| `Cmd+Shift+]` | Move focused cell into the folder directly above it (equation, slider, comment cells; no-op on folder cells and when no folder is adjacent above) |
| `Cmd+Shift+[` | Outdent focused cell out of its current folder, placing it below the folder's last member (no-op when cell is not in a folder) |
| `Alt+↑` | **In a multi-line cell (equation, comment):** move the current line up within the cell (swap with line above); no-op at first line. **In a slider field:** no-op (single-line). |
| `Alt+↓` | **In a multi-line cell:** move current line down (swap with line below); no-op at last line. **In a slider field:** no-op. |
| `Alt+Shift+↑` / `Opt+Shift+↑` | Move entire cell one position up in the expression panel (re-infers folder membership from new position) |
| `Alt+Shift+↓` / `Opt+Shift+↓` | Move entire cell one position down in the expression panel (re-infers folder membership from new position) |

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
│  [viridis][turbo][inferno][hot][hsv][⇄]  │
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
| **Stale indicator placement** | Orange dot in the data-mode row of equation cells that produce scatter arrays; goes orange when the expression or upstream deps changed since the last `→` click |
| **Error display** | Red text below the cell showing the Python exception message (truncated to one line; expandable) |
| **New cell button** | "+" button at the bottom of the cell list to add a new empty cell |
| **Session title** | Editable title in the window title bar; defaults to filename |
| **Unsaved changes indicator** | Save button text and border turn `#E9A15F` (orange) when the session has unsaved changes; `[*]` appended to window title. `CellListWidget` emits `session_dirtied` on any structural change (cell add/remove/edit via `_rebuild_namespace`) or style change (`_on_equation_cell_style_updated`); `PringleWindow._mark_modified` connects to this signal. Debounce timers are cancelled after session load/init so the flag is never set spuriously on open. |
| **Empty session state** | A placeholder message in empty panels: "Press + to add an expression" |
| **Grid regeneration on bound change** | Changing axis bounds re-evaluates all spatial cells — show a brief loading indicator if >200ms |
| **Slider value display** | Show current numeric value next to the drag handle; double-click to type an exact value |
| **Visibility toggle position** | *(implemented)* SVG `eye-fill.svg` / `eye-slash.svg` at the right of the folder header row; white on hover; no pressed-button chrome |
| **Folder cell** | *(implemented)* Collapsible group header with caret SVG toggle, eye visibility toggle, rename, and drag handle |
