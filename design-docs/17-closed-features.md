# Pringle — Closed Features

Features that have been implemented. Entries are preserved here for historical reference.

See [15-feature-backlog.md](15-feature-backlog.md) for open features.

---

### FEAT-038 — Expose surface gradients as a shared renderer primitive
**Status:** Closed (implemented 2026-05-20)

**Implementation:** Added `_grid_gradients(x, y, z) → (dz_dx, dz_dy)` to `renderer.py` — extracts the two `np.gradient` calls that were previously buried inside `_grid_normals`. Refactored `_grid_normals` to accept pre-computed `(dz_dx, dz_dy)` rather than `(x, y, z)`. `make_surface_mesh` calls `_grid_gradients` once before the clip pass and threads the result to `_grid_normals`; the gradients remain available as local variables for any downstream consumer (FEAT-036 critical points, FEAT-035 gradient coloring, etc.) at zero additional `np.gradient` cost. Pure internal refactor — no changes to the evaluator, cell namespace, or YAML format.

---

### FEAT-034 — Colormap normalization uses visible (constrained) data range
**Status:** Closed (implemented 2026-05-18)

**Implementation:** Added `v_min`/`v_max` override params to `_apply_colormap` in `renderer.py`. In `make_surface_mesh`, when `constraint_mask` is active, computes `cmap_min/max` from the masked `z` array (NaN outside constraint) rather than from clipped vertex positions — bypasses boundary vertex inflation from `_clip_mesh_to_mask`. In `make_line_mesh`, builds a `valid` mask over non-NaN points, constructs `linspace(0, 1, n_valid)` only over those points, and places the resulting colors at the valid positions in a full-length colors array — the visible portion of a constrained curve now maps to the full [0, 1] gradient.

---

### FEAT-033 — Replace scatter render-mode checkboxes with mutually exclusive radio selector
**Status:** Closed (implemented 2026-05-18)

**Implementation:** Replaced `scatter_as_line: bool` and `scatter_as_spheres: bool` in `CellStyle` with `scatter_render_mode: str = "circles"` ("circles" | "line" | "spheres"). Style popover restructured to two-column layout when `show_render_mode=True`: left column holds Color/Opacity/Size spinboxes, right column holds a `QButtonGroup` of three `QRadioButton` items. `_on_render_mode_changed(btn_id, checked)` maps button ID to mode string. `app.py` dispatch replaced with a single `mode = style.scatter_render_mode` branch. Session YAML writes `scatter_render_mode`; `_load_scatter_mode()` helper in `session.py` provides backward-compat fallback for old files with boolean flags.

---

### FEAT-032 — 3D sphere render mode for scatter points
**Status:** Closed (implemented 2026-05-18)

**Implementation:** Added `scatter_as_spheres: bool = False` to `CellStyle` and persisted in YAML. `make_scatter_mesh` gains `as_spheres` parameter; when True, builds a `gfx.InstancedMesh` with `gfx.sphere_geometry(radius=size/2, width_segments=8, height_segments=6)` and sets per-instance transforms via `pylinalg.mat_from_translation`. Opacity and `alpha_mode="blend"` applied the same as the flat-point path. Style popover adds a "Spheres" checkbox alongside the existing "Line" checkbox in the render-mode row.

---

### FEAT-028 — Functional folder cells with containment, collapse, and session persistence
**Status:** Closed (implemented 2026-05-18)

**Implementation:**
- `cell_list.py` — added `_cell_folder: dict[str, str | None]`, `_folder_collapsed`, `_folder_visible` dicts and `_skip_folder_inference` flag. New helpers: `_folder_members`, `_infer_folder`, `_assign_folder`, `_apply_indent`, `_is_render_visible`. Drag-and-drop infers new folder membership from drop position. Folder collapse/expand, visibility signals connected and handled.
- `folder_cell_widget.py` — added `collapse_changed` and `folder_visibility_changed` signals; eye button for viewport visibility; folder name is now a click-to-edit `QPushButton` (✏ button removed for UI uniformity). Two-state `_committing` guard prevents `editingFinished` double-fire.
- `session.py` — `cell_to_dict` accepts `folder_id` kwarg; folder dicts include `visible`. `restore_cell_list` uses two-pass approach: Pass 1 creates all cells with `_skip_folder_inference=True`; Pass 2 applies memberships, indentation, and collapsed/visible states.
- `+ Data cell` button replaced with `+ Folder`.

---

### FEAT-027 — Comment cells triggered by `#`
**Status:** Closed (implemented 2026-05-18)

**Implementation:**
- `comment_cell_widget.py` — new `CommentCellWidget` with `_CommentEdit` subclass of `QPlainTextEdit`. Auto-grow via `documentSizeChanged` signal (post-layout, correct for word-wrap); `resizeEvent` override recomputes height on initial layout pass (fixes load-time single-line height — BUG-017). `wheelEvent` overridden to `ignore()` so scroll falls through to outer panel. Layout: `[DragHandle] [# label AlignTop] [_CommentEdit] [✕]`.
- `cell_list.py` — `_maybe_morph_to_comment` / `_maybe_morph_from_comment` swap cell widget on `#` prefix change, preserving `cell_id` and calling `focus()` post-swap to restore cursor.
- Session: `type: comment`, `source` includes leading `# `.

---

### FEAT-029 — Insert new cell below the currently focused cell
**Status:** Closed (implemented 2026-05-18)  
**Description:** When the user has a cursor active in a cell, clicking "+ Equation" or "+ Folder" inserts the new cell immediately below that cell rather than appending to the bottom of the panel.

**Implementation:**
- `cell_list.py` — added `_focused_cell_id()` helper: builds `{id(widget): cell_id}` from `_cells`, then walks up from `QApplication.focusWidget()` via `.parent()` until a match is found. Returns `None` if no cell is focused (falls back to append behavior).
- Both add buttons gain `setFocusPolicy(Qt.FocusPolicy.NoFocus)` so clicking them does not steal keyboard focus from the active cell before the `clicked` signal fires.
- Button connections updated to `lambda: self.add_cell(after_id=self._focused_cell_id())` and `lambda: self.add_folder(after_id=self._focused_cell_id())`. The `after_id=None` fallback preserves existing append behavior when no cell is focused.

---

### FEAT-019 — "Fit to data" for axis bounds
**Status:** Closed (implemented 2026-05-18)  
**Description:** Added a "Fit to Data" button to `ViewSettingsWidget` (alongside "Equalize Axes") wired to a new `fit_requested` signal. `PringleWindow._on_fit_to_data` iterates `renderer._objects` (cell objects only, not overlays), unions their `get_world_bounding_box()` AABBs (skipping any with non-finite values), computes a uniform enclosing cube with 5% padding and a minimum half-span of 0.5, then updates both the spinboxes and the grid/overlay via `_on_bounds_changed`. Empty scene and degenerate data are handled as no-ops.

---

### FEAT-020 — World-space line width and point size (scale with zoom)
**Status:** Closed (implemented 2026-05-18)  
**Description:** Added `thickness_space="world"` to `LineMaterial` in `make_line_mesh` and `size_space="world"` to `PointsMaterial` in `make_scatter_mesh`. Recalibrated defaults: `line_width` 2.0 → 0.05, `point_size` 6.0 → 0.1 (world units; ~2–5 px equivalent at default view distance). Style popover Size range updated from `0.5–20 / step 0.5` to `0.005–2.0 / step 0.005 / 3 decimals`. Overlay lines (axes, bbox, crosshair) remain in screen space.

---

### FEAT-013 — Colormap support
**Status:** Closed (implemented 2026-05-18)  
**Logged:** 2026-05-16  
**Description:** Apply named colormaps from matplotlib to surface, curve, and scatter render types. Colormaps are selected and reversed from the style popover and persisted in session files.

**Implementation:**

- `pringle/style.py` — added `colormap: str | None` and `colormap_reversed: bool` fields to `CellStyle`; exported `COLORMAPS = ("viridis", "plasma", "inferno", "hot", "hsv")`.
- `pringle/renderer.py` — added `_apply_colormap(values, cmap_name, reverse)` helper (uses `matplotlib.cm`). Updated `make_surface_mesh`, `make_line_mesh`, `make_scatter_mesh` to accept `colormap` and `colormap_reversed` kwargs.
  - **Surfaces**: colormap normalized over the Z range of the final vertex positions (after constraint clipping); uses `MeshBasicMaterial(color_mode="vertex")` to avoid Phong-lighting darkening.
  - **Lines / scatter**: colormap normalized over index range 0..N via `np.linspace(0, 1, N)`.
- `pringle/style_popover.py` — added colormap section: row of 5 gradient swatch buttons (48×28 px, rendered via matplotlib) and a `⇄` reverse toggle. Clicking the active swatch deselects (returns to uniform color).
- `pringle/app.py` — all seven mesh-builder call sites pass `colormap=style.colormap, colormap_reversed=style.colormap_reversed`.
- `pringle/session.py` — `cell_to_dict` saves `colormap`/`colormap_reversed` in the style block; `restore_cell_list` reads them back.

**Remaining sub-goals (not implemented):**
- Time-varying color driven by a slider expression — needs a partial color-buffer update path independent of geometry rebuild.

---

### FEAT-022 — Persist slider play state across session save/load
**Status:** Closed (implemented 2026-05-18)  
**Fix:** `cell_to_dict` now saves `is_playing` and `anim_mode` for `SliderWidget` cells. `restore_cell_list` sets `anim_mode` per slider during the restore loop, then after all cells are reconstructed does a second pass calling `_on_play_toggled(True)` on any sliders that were playing — deferred so the shared namespace is fully populated before the first animation tick fires.

---

### FEAT-021 — Slider animation loop mode (wrap vs ping-pong)
**Status:** Closed (implemented 2026-05-18)  
**Fix:** Added `_anim_mode: str = "pingpong"` to `SliderWidget`. A small `↔` / `⟳` toggle button in row 2 (right of ▷) switches modes; `set_anim_mode(mode)` keeps the button text and tooltip in sync. `_anim_tick` now branches on `_anim_mode`: loop wraps the value directly back to the opposite boundary; ping-pong (default) reverses direction as before.

---

### FEAT-024 — Viewport background color toggle (dark / light)
**Status:** Closed (implemented 2026-05-18)  
**Fix:** `PringleRenderer` now stores `self._bg` and exposes `set_background_color(color)` which replaces the `BackgroundMaterial`. A "Light bg" checkbox added to the toggle row in `ViewSettingsWidget` emits `background_changed(bool)`; `app.py` maps this to `_LIGHT_BG` (0.95, 0.95, 0.95) or `_DARK_BG` (0.067, 0.067, 0.067). `show_light_bg` is persisted in the session `view` block alongside the other overlay states.

---

### FEAT-023 — Persist axis/overlay toggle states across session save/load
**Status:** Closed (implemented 2026-05-18)  
**Fix:** `save_session` now accepts an optional `view` dict and writes it alongside `grid` and `cells`. `_write_session` in `app.py` extracts overlay checkbox states (`show_axes`, `show_bbox`, `show_crosshair`) and camera state (`camera_position`, `orbit_target`) before calling `save_session`. `_on_open` reads the `view` block after restore and pushes it into the checkboxes (which emit their existing signals to update the renderer) and restores the camera position/look-at/controller target. Older session files without a `view` block load with all overlays visible by default.

---

### FEAT-012 — Axis settings popup window
**Status:** Closed (implemented 2026-05-18)  
**Description:** Added `_ViewportContainer` (wraps `PringleViewport`, absolutely-positions a checkable ⚙ button in the top-right corner via `resizeEvent`) and `AxisSettingsDialog` (non-modal `Qt.Tool` `QDialog` containing the existing `ViewSettingsWidget`). `PringleWindow` no longer adds `ViewSettingsWidget` to the left panel — the panel now holds only `CellListWidget`. Clicking ⚙ shows/hides the dialog positioned below the button; closing via the title-bar X unchecks the button via `finished` signal.

---

### FEAT-011 — Convert scatter plot to line/curve
**Status:** Closed (implemented 2026-05-18)  
**Description:** Added `scatter_as_line: bool = False` to `CellStyle`. Style popover gains a "Render: ☐ Line" checkbox (shown only when `show_render_mode=True`). `CellWidget` passes `show_render_mode=self._data_mode`; `DataCellWidget` always passes `True`. `DataCellWidget` emits `render_mode_changed(cell_id)` when the toggle changes; `CellListWidget` re-applies the cached `_last_result` without re-evaluating. `app.py:_on_cell_result` routes `scatter`/`scatter_2d` to `make_line_mesh` when `style.scatter_as_line`. Persisted in session YAML.

---

### FEAT-010 — Unified line/dot size control
**Status:** Closed (implemented 2026-05-16)  
**Description:** Style popover "Line width" renamed to "Size". The control now sets both `line_width` (curves) and `point_size` (scatter dots) to the same value. Range extended from 10 to 20.

---

### FEAT-009 — Fix equalize axes to use Z span
**Status:** Closed (implemented 2026-05-16)  
**Description:** "Equalize Axes" previously used the scene bounding sphere radius. Now reads `z_min`/`z_max` from spinboxes, computes span, and sets x and y to `[−span/2, +span/2]` so all three axes have equal length.

---

### FEAT-008 — Z bounds spinboxes in Axis Bounds panel
**Status:** Closed (implemented 2026-05-16)  
**Description:** The axis bounds loop only built X and Y rows; Z existed in `GridConfig` but had no UI. Added Z row. Session save/load now persists `z_min`/`z_max`. Loading a session restores the spinboxes and overlay bounds. `_on_bounds_changed` now takes 6 parameters.

---

### FEAT-007 — Inline value previews for equation cells
**Status:** Closed (implemented 2026-05-16)  
**Description:** Non-rendered cells now show small gray text below the cell body:
- Scalar results (e.g. `value = sum(p)`) — value shown left-aligned
- Non-rendered 1D arrays (e.g. `p = array([1,1,1])`) — elements shown left-aligned, truncated with `...` if too wide
- Rendered arrays (surfaces, curves, scatter) — shape shown right-aligned, e.g. `(64, 64)`
- Bare expressions (no assignment) — same preview rules apply, value captured via `eval`

---

### FEAT-006 — Unified cell list (data + equation cells in one panel)
**Status:** Closed (implemented 2026-05-16)  
**Description:** Merged equation panel and data panel into a single scrollable `CellListWidget`. Two add buttons — `+ Equation` and `+ Data cell` — replace the old single `+ Add expression`. Data cells are skipped during reactive evaluation (marked stale) and run on demand via their ▷ button. Data cell exports persist in `_data_cell_ns` and seed the equation namespace.

---

### FEAT-005 — Orbit target crosshair indicator
**Status:** Closed (implemented 2026-05-15, commit `98bcbdb`)  
**Fix:** `gfx.Group` with three short axis lines, repositioned to `controller.target` every frame in `render()`. Toggled via "Crosshair" checkbox.

---

### FEAT-004 — WASD pans orbit target in world space
**Status:** Closed (implemented 2026-05-15, commit `98bcbdb`/`852a7e5`)  
**Fix:** Continuous pan via Qt `keyPressEvent`/`keyReleaseEvent`; `event.accept()` suppresses macOS accent popover.

---

### FEAT-003 — Desmos-style wireframe bounding box
**Status:** Closed (implemented 2026-05-15, commit `41a40fe`)  
**Fix:** 12 `gfx.Line` objects tracing the box edges added as permanent overlay objects; `set_bbox_visible()` toggles them.

---

### FEAT-002 — Slider widget redesign
**Status:** Closed (implemented 2026-05-16)  
**Description:** Complete 2-row layout redesign:
- Row 1: `[color dot] [name] [value spinbox (stretch)] [✕]`
- Row 2: `[▷ play] [min] [slider (stretch)] [max] · step [step]`
- Up/down ticker buttons removed (`NoButtons`)
- Smart decimal display — integers show without decimal point; trailing zeros stripped
- Range auto-expand on creation (if initial value exceeds default max, range doubles)
- Slider snaps to multiples of the step value when dragged

---

### FEAT-001 — Axis visualization with toggle
**Status:** Closed (implemented 2026-05-15, commit `41a40fe`)  
**Fix:** Three `gfx.Line` objects (red=X, green=Y, blue=Z) added as permanent overlay scene objects; `set_axes_visible()` toggles them. Axis labels and tick marks deferred to v2.
