# Pringle — Closed Features

Features that have been implemented. Entries are preserved here for historical reference.

See [15-feature-backlog.md](15-feature-backlog.md) for open features.

---

### FEAT-044 — Text editing improvements: tab width, scroll pass-through, bracket wrapping
**Status:** Closed (implemented 2026-05-22)

**Implementation:**
- **`cell_widget.py`**: Added `QFontMetricsF` import. Added module-level `_WRAP_PAIRS` dict mapping opening bracket keys to `(open, close)` pairs. In `CellTextEdit.__init__`, added `setTabStopDistance` to 4 character widths after font is set. In `keyPressEvent`: Tab inserts 4 literal spaces and returns; selection + bracket key wraps selection with the pair and returns (Part C). Added `wheelEvent` that calls `event.ignore()` to propagate scroll to the outer panel (Part B).
- **`comment_cell_widget.py`**: Added `QFontMetricsF` import. Added `setTabStopDistance` to 4 character widths in `_CommentEdit.__init__` for consistency.

**Tests:** `tests/test_phase4_5.py::TestCellTextEdit` — `test_tab_inserts_four_spaces`, `test_tab_stop_distance_is_four_chars`, `test_wheel_event_ignored`, `test_bracket_wraps_selection`, `test_bracket_no_selection_falls_through`, `test_square_bracket_wraps_selection`.

---

### FEAT-043 — Slider visual cleanup: remove color dot, align name with cell text
**Status:** Closed (implemented 2026-05-22)

**Implementation:**
- **`slider_widget.py`**: Removed `self._color_dot` (QPushButton construction, `row1.addWidget`, and `_update_color_dot()` call and method). Name label is now the first widget in row 1, left-aligned with the color dots of equation cells (both start at the 4px content margin). `_name_label.setFixedWidth` set to 62px so the spinbox's left edge aligns with the min_box's left edge in row 2 (`4 + 62 + 6 = 72 = 4 + 28 + 6 + 28 + 6`). `style.color` on the slider's `CellStyle` is preserved for potential future use.

---

### FEAT-042 — Editable slider variable name (rename by clicking the name label)
**Status:** Closed (implemented 2026-05-22)

**Implementation:**

- **`slider_widget.py`**: Added `_ClickableLabel` (a `QLabel` subclass that emits `clicked`). Replaced the static `_name_label` with a `_ClickableLabel` instance that has an `IBeamCursor` and "Click to rename" tooltip. Added `name_changed = pyqtSignal(str, str, str)` (old_name, new_name, cell_id). Clicking the label calls `_on_name_clicked`, which stores a reference to `self._row1` (the row 1 `QHBoxLayout`) and swaps the label for a dynamically created `QLineEdit` via `replaceWidget`. `_on_name_text_changed` shows a red border for invalid input. `_on_name_commit` validates the proposed name (non-empty, `isidentifier()`, not in `MAGIC_NAMES | SPATIAL_NAMES`, passes optional `_validate_name` callback), commits if valid, and always swaps the `QLineEdit` back for the label. A `_committing_name` guard prevents re-entrant double-fires from focus-loss events. Added `set_name_validator(fn)` public method.

- **`cell_list.py`**: Added `_make_name_validator(slider)` which returns a closure over `self._cells` that rejects names used by other sliders (checked by identity `c is not slider`). Added `_on_slider_name_changed` handler that calls `_rebuild_namespace()`. Both `add_cell` and `_maybe_morph_to_slider` now connect `name_changed` and call `set_name_validator`.

**Behaviour:** Downstream cells that referenced the old name receive "undefined variable" warnings after a rename — the user updates references manually, consistent with any variable rename.

**Tests:** `tests/test_phase6.py` — `test_rename_emits_name_changed`, `test_rename_updates_source`, `test_rename_no_change_silent`, `test_rename_invalid_non_identifier`, `test_rename_invalid_empty`, `test_rename_rejects_magic_names`, `test_rename_rejects_duplicate_via_validator`, `test_rename_rebuilds_namespace`, `test_rename_duplicate_blocked_by_cell_list`.

---

### FEAT-041 — Remove `t` from spatial variables so `t = value` creates a slider
**Status:** Closed (implemented 2026-05-22)

**Implementation:**
- `preprocess.py`: removed `"t"` from `SPATIAL_NAMES` so `is_slider_cell("t = 1")` now returns `(True, "t", 1.0)`.
- `grid.py`: removed `"t"` from `grid_vars()` return dict and dropped the `t` parameter from the signature.
- `evaluator.py`: updated `run_cell` to drop the dead `t: float = 0.0` parameter and the `grid_vars(grid, t)` call (now `grid_vars(grid)`).

`x`, `y`, `u`, `v` remain reserved spatial names. Animation time is not implemented in v1; a future `t`-variation feature should use a dedicated mechanism.

**Tests:** `tests/test_phase2.py::TestPreprocess::test_t_is_slider`, `test_t_float_is_slider`, `test_t_not_in_grid_vars`, `test_t_slider_not_shadowed_by_grid`.

---

### FEAT-038 — Recurrence and initial condition sub-cells for all renderable array shapes
**Status:** Closed (implemented 2026-05-22)

**Implementation:**

Three changes:

1. **Sub-cell menu ungated** (`cell_widget.py:_on_add_sub_clicked`): All four options — "Add Recursion Rule", "Add Initial Condition", "Add Constraint", "Add Condition" — are now shown unconditionally regardless of `_data_mode`. Previously, recursion/initial-condition options were hidden from non-data-mode cells.

2. **Auto-enable data mode on recursion add** (`cell_widget.py:add_sub_cell`): When `sub_type == "recursion"`, `set_data_mode(True)` is called before the sub-cell is appended. Recurrence requires data mode because the sequential Python loop is too expensive for reactive evaluation.

3. **Shape-aware render type after recurrence** (`cell_list.py:_eval_cell`): The hardcoded `arr.ndim == 2 and arr.shape[1] in (2, 3)` scatter guard is replaced with a call to `_detect_shape(arr)` from `evaluator.py`. This makes recurrence cells render `(N, 6)` as vectors, `(N, 4)` as vectors_2d, `(N, 3)` as scatter, `(N, 2)` as scatter_2d. 3D or otherwise unrecognised shapes fall through to namespace-only export (`render_type = None`). The auto-switch logic that infers data mode from shape is skipped when a recurrence rule is present (to prevent auto-disabling data mode for vector/unrecognised shapes).

**Tests:** `tests/test_feat038.py`

---

### FEAT-014 — Vector / arrow rendering (flow chains and explicit tail+head pairs)
**Status:** Closed (implemented 2026-05-22)

**Implementation:**

Two distinct render modes:

1. **Vector field mode** — an `(N, 6)` array (columns 0–2 = tail, 3–5 = head) detected via `_detect_shape` in `evaluator.py` produces `render_type = "vectors"`. An `(N, 4)` array produces `render_type = "vectors_2d"` (2D tail+head pairs; z columns are zero-padded before dispatch). `_detect_shape` checks for `(N, 6)` and `(N, 4)` before the existing `(N, 3)` / `(N, 2)` scatter checks so a 6-column array is never misread.

2. **Flow mode** — when `scatter_render_mode == "arrows"` on a scatter cell, consecutive scatter points are converted to N−1 arrows via `np.concatenate([pts[:-1], pts[1:]], axis=1)` in `_on_cell_result`.

**Arrow geometry** (`renderer.py`): `_build_unit_arrow_geometry()` builds a shaft cylinder + cone head combined into a single `gfx.Geometry` (unit arrow pointing along +Z, z ∈ [0, 1]). Stored as a module-level singleton `_ARROW_GEO`. `_arrow_matrix(tail, head)` produces the 4×4 float32 instance transform (Rodrigues rotation + Z-column scale by length, translation = tail). `make_arrow_mesh(arrows, color, opacity, normalize)` creates a `gfx.InstancedMesh` — one draw call for all N arrows.

**`CellStyle`**: added `normalize_arrows: bool = False` — pins all arrows to equal length (mean magnitude). Shown as a "Normalize lengths" checkbox in `StylePopoverWidget`: always visible when `show_normalize=True` (vector cells), dynamically shown/hidden when Arrows radio is selected (scatter cells). `scatter_render_mode` extended with `"arrows"` as a fourth option.

**Tracking**: `cell_widget.py` / `cell_list.py` maintain `_is_vector_cell` on `CellWidget` (analogous to `_data_mode`) and set it from `_CellWorkerResult.is_vector` in both the synchronous and threaded eval paths.

**Session**: `normalize_arrows` serialized to YAML alongside other style fields; read back with `False` fallback for old files.

**Tests**: `tests/test_vectors.py` — shape detection, run_cell end-to-end, `_arrow_matrix` correctness, `make_arrow_mesh` GPU tests (skipped when GPU unavailable), flow-mode consecutive-pair logic.

---

### FEAT-026 — Drop shadow projected onto bottom plane of bounding box
**Status:** Closed (implemented prior to 2026-05-21)

**Implementation:** `PringleRenderer` maintains `_shadow_objects`, `_shadow_visible`, `_shadow_opacity`, and `_shadow_color`. `_make_shadow_object` copies each object's geometry with Z flattened to `z_min + ε` and renders with a light-colored translucent material. Shadows are created/removed alongside their source objects in `add_object`/`remove_object`, hidden with `set_visible`, and rebuilt via `_rebuild_shadows` when axis bounds change.

---

### FEAT-031 — Halve the crosshair arm length
**Status:** Closed (implemented 2026-05-21)

**Implementation:** Changed the arm multiplier in `renderer.py` from `0.025` to `0.0125`. One line.

---

### FEAT-038 — Auto-expanding text input for constraint and recursion sub-cells
**Status:** Closed (implemented 2026-05-21)

**Implementation:** Added `allow_newline: bool = False` to `CellTextEdit.__init__`. When `True`, the Enter key handler falls through to `super().keyPressEvent()` (inserts a newline) rather than emitting `enter_at_end`. In `ConstraintSubCell._build_ui`, replaced `QLineEdit` with `CellTextEdit(self, allow_newline=True)` — stylesheet updated from `QLineEdit {…}` to `QPlainTextEdit {…}` with `background: transparent`; font-family rule removed (CellTextEdit sets Menlo/Consolas/Courier New via QFont). `source()` updated from `.text()` to `.toPlainText()`. `QLineEdit` removed from imports.

---

### FEAT-039 — Widen the expression panel by 50% by default
**Status:** Closed (implemented 2026-05-21)

**Implementation:** Changed `LEFT_PANEL_WIDTH` in `PringleWindow` (`app.py`) from `320` to `480`. Splitter initialization reads this constant directly; viewport gets `1400 - 480 = 920 px`.

---

### FEAT-040 — Camera-relative WASD panning
**Status:** Closed (implemented 2026-05-21)

**Implementation:** Replaced world-space fixed-axis pan in `_apply_movement` (`app.py`) with camera-relative pan. The horizontal forward vector `(fx, fy)` is computed as the camera-to-target XY component, normalized. WASD key-space directions `(dx_k, dy_k)` are rotated into world XY using the 2D basis: `forward=(fx,fy)`, `right=(fy,-fx)`. The rotation is a single multiply: `dx = dx_k*fy + dy_k*fx`, `dy = -dx_k*fx + dy_k*fy`. Space/Shift have `dx_k=dy_k=0` so they pass through unchanged as world ±Z. Degenerate case (camera directly above target, `|fwd_xy| < 1e-6`) falls back to `(fx,fy)=(0,1)` (world +Y). `_PAN_KEYS` dict and `_pan_target` are unchanged.

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
