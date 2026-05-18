# Pringle — Feature Backlog

Desired features and enhancements are logged here as they are identified. Each entry includes a description, motivation, and implementation notes or open questions where known.

See [14-backlog.md](14-backlog.md) for the bug backlog.

---

## Open

### FEAT-023 — Persist axis/overlay toggle states across session save/load
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
The visibility state of the Axes, Wireframe bounding box, and Crosshair overlays is not saved to the session YAML. All three checkboxes always reset to checked (visible) on load, regardless of how they were when the session was saved.

**Root cause:**  
`save_session` in `session.py` writes only a `grid` block (bounds + resolution) and a `cells` list. There is no `view` block. The three checkbox widgets (`_axes_cb`, `_bbox_cb`, `_crosshair_cb` in `view_settings.py:104–117`) each default to `setChecked(True)` on construction and are never read during save or written during restore.

**Fix — add a `view` block to the session YAML:**

```python
# session.py — save_session: add alongside "grid" and "cells"
"view": {
    "show_axes":      view_settings._axes_cb.isChecked(),
    "show_bbox":      view_settings._bbox_cb.isChecked(),
    "show_crosshair": view_settings._crosshair_cb.isChecked(),
},
```

On restore, after `restore_cell_list` completes, read the block and push it into `ViewSettingsWidget`. Setting the checkbox state will emit the existing `axes_visibility_changed`, `bbox_visibility_changed`, and `crosshair_visibility_changed` signals, which already wire to `renderer.set_axes_visible` etc. — so no additional plumbing is needed:

```python
view = data.get("view", {})
view_settings._axes_cb.setChecked(view.get("show_axes", True))
view_settings._bbox_cb.setChecked(view.get("show_bbox", True))
view_settings._crosshair_cb.setChecked(view.get("show_crosshair", True))
```

The `get(..., True)` defaults ensure older session files (without a `view` block) load with all overlays visible, matching the current default behaviour.

**`save_session` currently takes only `cell_list` and `grid_config`** — the `view_settings` widget reference will need to be passed in as a third argument (or the relevant state extracted at the call site in `app.py` before calling `save_session`).

**Stretch goal:** also save the camera position (`camera.local.position`) and orbit target (`controller.target`) so the viewport reopens at the same angle the user left it.

---

### FEAT-017 — Dark vs light mode toggle
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Add a toggle (checkbox or button) to switch the application between a dark and a light color scheme. Both the Qt UI panels and the 3D viewport background should update consistently.

**Implementation notes:**
- Qt side: apply a `QApplication.setStyleSheet(...)` swap. A minimal dark palette can be constructed from `QPalette` without a full third-party theme library.
- Viewport background: `renderer.background` (the wgpu canvas clear color) needs to change — currently hardcoded in `renderer.py`. Expose a `set_background_color` method and call it on toggle.
- Axis/bbox/crosshair line colors may need to invert or adjust for legibility against the new background.
- Persist the preference in the session YAML or a user config file so the chosen mode survives restarts.
- The toggle could live in the new Axis Settings popup (FEAT-012) or in a top-level View menu.

---

### FEAT-016 — Color defaults and color picker/slider in style popup
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Extend the existing per-cell style popover (`style_popover.py`) with a proper color picker and opacity slider, replacing the current color dot (which only cycles through a fixed palette). Also establish a global default color sequence so new cells get predictable, Desmos-like colors in order.

**Implementation notes:**
- Qt provides `QColorDialog` out of the box; it can be launched from a "Custom…" button inside the popover to let the user pick any RGBA color.
- Alternatively, embed a compact HSL/RGB slider widget directly in the popover (avoids opening a separate window).
- Opacity slider: a `QSlider` mapped to the alpha channel of the cell's RGBA color; the viewport material's `opacity` and `is_transparent` flag must be updated on change.
- Default sequence: define an ordered list of RGBA defaults (matching Desmos's palette or similar) in `style.py`; `CellListWidget` assigns the next unused color when a cell is created.
- The color dot in the cell row should update live as the picker changes.

---

### FEAT-015 — Application icon
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Add a custom icon for the application window and macOS Dock entry.

**Implementation notes:**
- Set via `QMainWindow.setWindowIcon(QIcon("path/to/icon.png"))` and `QApplication.setWindowIcon(...)` early in startup.
- macOS Dock icon additionally requires a `.icns` file referenced in the app bundle's `Info.plist` (relevant if packaging with PyInstaller or py2app).
- A simple `.png` (256×256 or 512×512) is sufficient for the window title bar on all platforms.

---

### FEAT-014 — Vector arrows
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Support rendering 3D vector fields as arrow glyphs — a set of origin points each with a direction and optional magnitude-scaled length.

**Implementation notes:**
- Expected input: an `(N, 3)` positions array paired with an `(N, 3)` directions array (or a single `(N, 6)` array where columns 0–2 are origins and 3–5 are vectors). The magic variable name (e.g. `arrows`) or a style toggle would trigger this render type.
- pygfx does not have a built-in arrow/glyph primitive. Each arrow must be constructed from geometry: a `Line` for the shaft and a cone (or a second short line pair forming a "V") for the head. For large fields this is expensive if done per-arrow; consider instanced geometry or a custom shader approach.
- A simpler v1 approach: pre-build a single arrow mesh and use `gfx.InstancedMesh` to render N copies with per-instance transform matrices. pygfx supports instanced meshes, which makes this GPU-efficient.
- Shaft length should scale with vector magnitude by default; a "normalize" style toggle should pin all arrows to equal length.
- Color follows the cell's assigned color, with the colormap extension (FEAT-013) applying naturally once that is built.

---

### FEAT-013 — Conditional coloring and colormap support
**Status:** Open  
**Logged:** 2026-05-16

**Description:**  
Allow the color of a rendered object to be driven by a data-dependent mapping rather than a single uniform color. Three specific sub-goals:
1. Apply a colormap to a surface by Z value.
2. Color curve segments by segment index (position along the path).
3. Color objects by a time-varying scalar (e.g. a slider variable).

**Tech stack assessment (pygfx / wgpu-py):**

All three material types used in the renderer (`MeshPhongMaterial`, `LineMaterial`, `PointsMaterial`) support `color_mode="vertex"` and accept a `colors` buffer on `gfx.Geometry`. This is the correct mechanism for all three sub-goals.

- **Z-value colormap on surfaces** — Feasible. For each vertex, normalize its Z coordinate into `[0, 1]` relative to `z_min`/`z_max`, sample a colormap at that value to get an RGBA, and write it into `geometry.colors`. Set `material.color_mode = "vertex"`.
- **Curve coloring by segment index** — Feasible. `LineMaterial` supports `color_mode="vertex"`. Assign each vertex a color `colormap(i / N)`. Colors are linearly interpolated between adjacent vertices by the GPU, giving a smooth gradient along the path.
- **Time-varying color** — Feasible but requires the color array to be recomputed on each slider update (not only on geometry rebuild). This hooks into the reactive update pipeline: when a slider that appears in the color expression changes, the per-vertex color buffer must be recomputed and re-uploaded. The mechanism exists (reactive eval already reruns cells on slider change) but the renderer currently only rebuilds geometry, not color buffers independently. A partial-update path (update colors without rebuilding the mesh) would be needed for performance.

**Known limitation — lighting interaction:**  
`MeshPhongMaterial` modulates vertex colors by the Phong lighting model, so colormap values toward black will appear very dark under typical scene lighting regardless of the actual data range. For faithful colormap display, either switch to `MeshBasicMaterial` (unlit) when a colormap is active, or expose a shininess/flatShading control to minimize the effect.

**Known limitation — no built-in colormaps:**  
pygfx does not ship named colormaps (viridis, plasma, etc.). Options:
- Use `matplotlib.cm` to generate RGBA arrays — matplotlib is a common scientific dep and likely already present.
- Implement a small set of colormaps (viridis, turbo, grayscale) directly in `style.py` as hardcoded LUTs for zero extra dependencies.

**UX sketch:**  
In the style popover, a "Color by" dropdown: `Uniform | Z value | Index | Expression`. Selecting a non-uniform mode reveals a colormap picker (named presets + min/max clamp controls). The expression mode allows a free-form scalar expression referencing cell variables.

---




### FEAT-018 — Load external data files into data cells
**Status:** Open  
**Logged:** 2026-05-17

**Description:**  
Allow a data cell to load an external file by providing a quoted path as the RHS of an assignment. When the user presses ▷, the app detects that the source is a path literal, attempts to load the file, and exposes the result as a numpy array in the shared namespace — identical to any other data cell output. Load errors (bad path, unsupported format, malformed content) are surfaced in the cell's status area with a descriptive message rather than crashing.

**UX flow:**
```
d = "path/to/data.npy"
```
1. User types the above in a data cell and presses ▷.
2. The loader detects the string literal RHS and dispatches to the appropriate format handler.
3. On success: the cell shows `ok` status, exports `d` (the array or dict) into the shared namespace, and displays the shape in the preview area (e.g. `(1000, 3)`).
4. On failure: the cell shows an `error` status with a plain-language message (e.g. "File not found: path/to/data.npy" or "CSV parse error: non-numeric value in column 2, row 47"). No popup — consistent with how other cell errors are handled.

**Supported formats:**

| Extension | Loader | Notes |
|-----------|--------|-------|
| `.npy` | `np.load(path, allow_pickle=False)` | Single array; see security note below |
| `.npz` | `np.load(path, allow_pickle=False)` | Zip of named arrays; expose as a dict `{"x": arr, ...}` and also unpack each key as `d_x`, `d_y`, etc. into the namespace |
| `.csv` | `np.loadtxt(path, delimiter=",", comments="#")` | Falls back to `np.genfromtxt` with `invalid_raise=False` for files with missing values; skip header rows that can't be parsed as floats |
| `.tsv` | Same as CSV with `delimiter="\t"` | |
| `.txt` | `np.loadtxt(path)` (whitespace-delimited) | |
| `.mat` | `scipy.io.loadmat(path)` | Optional — only if scipy is available; expose the variable dict, let the user index it like `d["x"]` |
| `.json` | `json.load` → `np.array(...)` | Only if the JSON structure is a flat list or list-of-lists; reject otherwise with a clear error |

Other formats (HDF5, Parquet, Excel) are out of scope for v1 — they pull in large optional dependencies and have complex internal structure; log them as "unsupported format" rather than silently failing.

**Implementation sketch:**

Detection happens in `_run_data_cell` (or a new `_load_file_cell` helper called from it) before the usual `run_cell` path:
```python
import ast, re
source = cell.source().strip()
# Match:  name = "some/path"  or  name = 'some/path'
m = re.fullmatch(r'(\w+)\s*=\s*(["\'])(.+?)\2', source)
if m:
    var_name, _, file_path = m.group(1), m.group(2), m.group(3)
    _load_file_into_cell(cell, var_name, Path(file_path))
    return
```
`_load_file_into_cell` resolves the path, dispatches by suffix, wraps the loader call in a `try/except`, and writes the result into `_data_cell_ns` exactly as a computed array would be.

**Security considerations — read carefully:**

- **Pickle deserialization / RCE** (`np.load`): Numpy `.npy` and `.npz` files that contain Python object arrays require pickling. A maliciously crafted `.npy` file with a pickled payload can execute arbitrary code on load. **Always call `np.load(path, allow_pickle=False)`.** If the file requires pickle, numpy raises a `ValueError`; surface it as: "File requires pickle deserialization, which is disabled for security. Re-save the array with `np.save()` using a numeric dtype." Similarly, `scipy.io.loadmat` uses pickle internally for some object types — use only the non-pickle code path if scipy is added.

- **Path traversal**: A relative path like `../../.ssh/id_rsa` resolves relative to the process working directory and could read sensitive files. The loader should call `Path(file_path).resolve()` and optionally warn if the resolved path escapes a user-configured data directory. At minimum, log the resolved absolute path in the cell status so the user can see exactly what was read.

- **Zip bombs** (`.npz`): `.npz` is a zip archive. A malicious file could decompress to gigabytes from a small on-disk size. Add a size cap: check `os.path.getsize(path)` before loading and reject files above a reasonable threshold (e.g. 500 MB) with a clear error. Note this does not fully protect against zip bombs — a more robust approach is to open the zip and check member sizes before extracting.

- **Large file / memory exhaustion**: Even legitimate files can be arbitrarily large. The 500 MB cap above applies here too. Surface the file size in the cell's `ok` preview (e.g. `(1000000, 3) — 22.9 MB`) so the user has visibility.

- **`open()` is currently blocked in equation cells** (`safety.py:23`) but data cells are explicitly more permissive. File loading must stay confined to data cells and the dedicated loader path — it should not be possible to trigger file I/O from an equation cell expression.

---

## Closed

### FEAT-019 — "Fit to data" for axis bounds
**Status:** Closed (implemented 2026-05-18)  
**Description:** Added a "Fit to Data" button to `ViewSettingsWidget` (alongside "Equalize Axes") wired to a new `fit_requested` signal. `PringleWindow._on_fit_to_data` iterates `renderer._objects` (cell objects only, not overlays), unions their `get_world_bounding_box()` AABBs (skipping any with non-finite values), computes a uniform enclosing cube with 5% padding and a minimum half-span of 0.5, then updates both the spinboxes and the grid/overlay via `_on_bounds_changed`. Empty scene and degenerate data are handled as no-ops.

---

### FEAT-020 — World-space line width and point size (scale with zoom)
**Status:** Closed (implemented 2026-05-18)  
**Description:** Added `thickness_space="world"` to `LineMaterial` in `make_line_mesh` and `size_space="world"` to `PointsMaterial` in `make_scatter_mesh`. Recalibrated defaults: `line_width` 2.0 → 0.05, `point_size` 6.0 → 0.1 (world units; ~2–5 px equivalent at default view distance). Style popover Size range updated from `0.5–20 / step 0.5` to `0.005–2.0 / step 0.005 / 3 decimals`. Overlay lines (axes, bbox, crosshair) remain in screen space.

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

### FEAT-022 — Persist slider play state across session save/load
**Status:** Closed (implemented 2026-05-18)  
**Fix:** `cell_to_dict` now saves `is_playing` and `anim_mode` for `SliderWidget` cells. `restore_cell_list` sets `anim_mode` per slider during the restore loop, then after all cells are reconstructed does a second pass calling `_on_play_toggled(True)` on any sliders that were playing — deferred so the shared namespace is fully populated before the first animation tick fires.

---

### FEAT-021 — Slider animation loop mode (wrap vs ping-pong)
**Status:** Closed (implemented 2026-05-18)  
**Fix:** Added `_anim_mode: str = "pingpong"` to `SliderWidget`. A small `↔` / `⟳` toggle button in row 2 (right of ▷) switches modes; `set_anim_mode(mode)` keeps the button text and tooltip in sync. `_anim_tick` now branches on `_anim_mode`: loop wraps the value directly back to the opposite boundary; ping-pong (default) reverses direction as before.

---

### FEAT-001 — Axis visualization with toggle
**Status:** Closed (implemented 2026-05-15, commit `41a40fe`)  
**Fix:** Three `gfx.Line` objects (red=X, green=Y, blue=Z) added as permanent overlay scene objects; `set_axes_visible()` toggles them. Axis labels and tick marks deferred to v2.
