# Pringle — Feature Backlog

Desired features and enhancements are logged here as they are identified. Each entry includes a description, motivation, and implementation notes or open questions where known.

See [14-bug-backlog.md](14-bug-backlog.md) for the bug backlog.  
See [17-closed-features.md](17-closed-features.md) for implemented features.

---

### FEAT-028 — Folder cells with actual containment, indentation, and collapse
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
`FolderCellWidget` exists and renders a collapsible header banner, but it is a purely visual divider — it has no cell membership tracking, no indentation, and collapsing it does nothing to the cells below it. This feature makes folders functional: cells explicitly belong to a folder, expanding/collapsing the folder shows/hides its members, and members are visually indented.

**What's already implemented (`folder_cell_widget.py`):**  
- Header row with ▶/▼ toggle, editable name, rename (✏), delete (✕), drag handle.  
- `set_collapsed(bool)` / `toggle()` — updates the arrow and hides/shows `_body`, which is currently always empty.  
- Session serialization (`cell_to_dict` / `restore_cell_list`) handles `type: folder` in the YAML.  
- `CellListWidget` skips `FolderCellWidget` during DAG evaluation.

**What needs to be built:**

1. **Explicit cell membership:** Each non-folder cell needs a `folder_id: str | None` field (default `None` = top level). `CellListWidget` maintains a `_folder_members(folder_id) → [cell_ids]` lookup. Session YAML adds a `folder_id` key to each cell dict. Positional inference (cells between folder banners belong to the one above) is simpler but breaks on drag-reorder; explicit IDs are the correct approach (matching Desmos's internal `folderId` field).

2. **Collapse/expand hides member cells:** `FolderCellWidget.set_collapsed` emits a new `collapse_changed(cell_id, collapsed)` signal. `CellListWidget` handles it by calling `cell.setVisible(not collapsed)` on all member widgets. Cells continue to evaluate and render when their folder is collapsed — this is panel-only, not visibility in the renderer sense.

3. **Visual indentation:** Member cells get a left margin (`setContentsMargins(indent, ...)`) or a left-border decoration when inside an open folder. `CellListWidget` applies/removes this margin when folder membership changes or when a cell is added to a folder.

4. **Folder visibility eye icon:** Add an eye button to the folder header row. Toggling it calls `renderer.set_visible(cell_id, folder_visible and cell_visible)` for all members. This is additive — a cell renders only if both its own eye and its folder's eye are on. The folder eye state persists in the YAML.

5. **Drag cells into/out of folders:** When a cell is dragged and dropped, the drop position determines folder membership. Dropping between two member cells assigns the dragged cell to that folder; dropping before the folder header or after the last member removes it from the folder. A visual "drop zone" highlight should indicate folder membership as the user drags.

6. **No nesting:** Folders cannot contain other folders. If a folder is dragged inside another folder, it is placed at the top level adjacent to the target folder.

**Desmos reference:** see `01-desmos-3d-overview.md` — Organization Features → Folders, updated 2026-05-18.

---

### FEAT-027 — Comment cells triggered by `#`
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
When a user types `#` as the first character in any cell, the cell automatically morphs into a comment cell — free text, never evaluated, no namespace contribution, no color dot, no eye icon. The cell wraps text and grows vertically as content is added. Removing the `#` from the start reverts it to a normal equation cell.

**Design decision — trigger character:** `#` only. Single/double-quoted strings and `"""` docstrings are not triggers; they evaluate as Python string literals in equation cells. Design doc `07-cell-types-and-blocks.md` has been updated to reflect this.

**Implementation:**

- **`CommentCellWidget`**: a new thin widget class (similar in structure to `FolderCellWidget` — no evaluation, no sub-cells). Contains a `QPlainTextEdit` in word-wrap mode with auto-grow behavior, a drag handle, and a delete (✕) button. No color dot, no eye icon, no sub-cell (+) button.

- **Auto-grow height:** connect `document().contentsChanged` to a slot that sets the widget height to `document().size().toSize().height() + vertical_margins`. `QPlainTextEdit` with `setVerticalScrollBarPolicy(ScrollBarAlwaysOff)` and `setSizePolicy(Expanding, Preferred)` is the standard Qt pattern for this.

- **Auto-morph detection** (`cell_list.py` — `_on_cell_changed`): if the source of a `CellWidget` starts with `#`, replace it in `_cells` and the layout with a `CommentCellWidget`, preserving `cell_id` and position. The inverse: if a `CommentCellWidget`'s text no longer starts with `#`, replace it with a `CellWidget`.

- **Appearance:** gray or muted styling to distinguish from active cells — e.g. slightly lighter background, italic or regular-weight text, no status indicator row. The `#` is stripped from the displayed text and shown as a small fixed `#` decoration on the left margin of the cell (similar to how the color dot occupies that position on equation cells), so the user's free text fills the edit area cleanly.

- **Session format:** serialized as `type: comment` with a `source` field containing the full text (including the leading `#`). `restore_cell_list` reconstructs a `CommentCellWidget` for these entries.

- **Limitations:** none significant. `QPlainTextEdit` handles multi-line text and word wrap natively. The auto-grow pattern is well-established in Qt. The morph/de-morph logic is the same as the existing slider morph and carries the same caveats (cell_id is preserved; undo history may need updating if undo is tracked at the cell level).

- **Polish fixes applied 2026-05-18:** (1) `#` label pinned to `AlignTop` with `padding-top: 5px` to align with the first text line. (2) Auto-grow implemented via `_CommentEdit` subclass (same pattern as `AutoGrowEdit`) — `setFixedHeight` called on self inside the subclass rather than from the outer widget. (3) `comment.focus()` called in `_maybe_morph_to_comment` immediately after the layout swap so the cursor returns automatically.

**Desmos reference:** see `01-desmos-3d-overview.md` — Organization Features → Comment Cells, updated 2026-05-18.

---

### FEAT-026 — Drop shadow projected onto bottom plane of bounding box
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
Render a semi-transparent shadow of each plotted object projected straight down onto the `z_min` floor plane of the wireframe bounding box. The shadow would be a flat, dark silhouette that helps orient the user in 3D space and gives a sense of height above the floor.

**Performance cost: essentially zero.** A straight-down orthographic shadow is just geometry — copy each object's vertex positions, clamp all Z coordinates to `z_min`, and render with a semi-transparent dark material. This adds geometry to the normal render pass but requires no extra GPU passes, no depth textures, and no shadow maps.

**Why not use pygfx's built-in shadow maps?**  
pygfx does support `cast_shadow` / `receive_shadow` on world objects and `DirectionalLight`, and the shadow pipeline covers Mesh, Line, and Points. However, shadow maps add a full extra render pass per frame per casting light — overhead that is unwarranted here since a straight-down projection is mathematically exact with the simpler technique.

**Implementation:**  
For each cell object in `_objects`, maintain a corresponding "shadow" object: a copy of the geometry with all Z values flattened to `z_min + ε` (tiny offset to avoid Z-fighting with the wireframe floor edge), rendered with a `MeshBasicMaterial` / `LineMaterial` / `PointsMaterial` in near-black at ~30–40% opacity:

```python
def _make_shadow(obj: gfx.WorldObject, z_floor: float) -> gfx.WorldObject | None:
    geom = obj.geometry
    if geom is None or geom.positions is None:
        return None
    pos = np.array(geom.positions.data, dtype=np.float32).copy()
    pos[:, 2] = z_floor + 1e-3          # flatten + tiny Z offset
    shadow_geom = gfx.Geometry(positions=pos, indices=geom.indices)
    if isinstance(obj, gfx.Mesh):
        mat = gfx.MeshBasicMaterial(color=(0, 0, 0, 0.35), side="both")
        return gfx.Mesh(shadow_geom, mat)
    elif isinstance(obj, gfx.Line):
        mat = gfx.LineMaterial(color=(0, 0, 0, 0.35), thickness=obj.material.thickness)
        return gfx.Line(shadow_geom, mat)
    elif isinstance(obj, gfx.Points):
        mat = gfx.PointsMaterial(color=(0, 0, 0, 0.35), size=obj.material.size)
        return gfx.Points(shadow_geom, mat)
    return None
```

Shadow objects are tracked in a parallel `_shadow_objects: dict[str, gfx.WorldObject]` dict in `PringleRenderer`, added/removed alongside their source objects in `add_object` and `remove_object`. They are also hidden when the source object is hidden (`set_visible`).

**The `z_min` value needs to be kept in sync with the axis bounds.** When the user changes the Z min spinbox, all shadow objects should have their floor Z updated. This means either rebuilding shadow geometry on bounds change, or storing the floor plane as a uniform and doing the projection in a custom shader (more complex but avoids CPU geometry copies on every bounds change).

**Excluded from bounding box calculations:** Shadow objects must be excluded from `get_data_bounding_box` (FEAT-019) and `fit_camera` so they don't inflate the scene bounds or affect camera fitting.

**Toggle and opacity:** Add a "Shadow" checkbox to the axis/view settings panel alongside the existing Axes, Wireframe, and Crosshair toggles, with a companion opacity spinbox or slider (range 0.0–1.0, default ~0.35). The checkbox wires the same way as the other overlays — a `shadow_visibility_changed` signal on `ViewSettingsWidget` connected to a `set_shadow_visible` method on `PringleRenderer` that shows/hides all entries in `_shadow_objects`. The opacity control calls a `set_shadow_opacity` method that updates the alpha on each shadow material. Default visibility TBD (off by default seems reasonable given it adds visual noise for simple plots). Both values persist in the `view` YAML block introduced by FEAT-023.

**Style consideration:** Shadow color should adapt for light vs. dark backgrounds (FEAT-024) — near-black on white, near-white on dark.

---

### FEAT-025 — Save button and unsaved-changes indicator
**Status:** Open  
**Logged:** 2026-05-18

**Description:**  
Add a visible save button and/or an unsaved-changes indicator to the UI. The app already tracks `_modified` and keyboard shortcuts (`Cmd+S` / `Ctrl+S`) work, but there is no on-screen affordance communicating save state or providing a click target for users who don't know the shortcut.

**What's already in place (`app.py:324–335`):**  
- `_modified: bool` is set on every cell/slider change and cleared on save.
- `_update_title()` prepends `"* "` to the window title when modified — e.g. `"* pringle — rossler.yml"`.
- `Cmd+S` / `Ctrl+S` (save) and `Cmd+Shift+S` / `Ctrl+Shift+S` (save-as) shortcuts are registered.

**What's missing:**

1. **Native macOS close-button dot:** Qt provides `QMainWindow.setWindowModified(bool)` and a `[*]` placeholder in `setWindowTitle`. When used together, Qt automatically shows the native dot inside the red traffic-light close button on macOS (and an asterisk in the title on other platforms). The current code uses a manual `"* "` prefix instead, so the macOS dot never appears. Fix: replace the manual prefix with the standard Qt mechanism:
   ```python
   # _update_title in app.py
   self.setWindowTitle(f"pringle — {name}[*]")   # [*] is Qt's placeholder
   self.setWindowModified(self._modified)          # drives the dot on macOS
   ```

2. **On-screen save button / indicator:** The window title `*` is easy to miss. An explicit UI element (location and style TBD — to be discussed) would make the save state more prominent. Options to consider:
   - A small `●` dot or `Save` button in the top bar / toolbar area that is highlighted when `_modified` is True and grayed out when clean.
   - A floppy-disk icon button (`💾` or a custom SVG) that triggers `_on_save` on click.
   - A pill-shaped status label (e.g. `"Unsaved"` / `"Saved"`) styled similarly to how the cell status area works.
   - A thin colored border or highlight on the left panel header when unsaved (minimal footprint, no extra button).

**Cross-platform notes:**  
- **macOS:** native dot on the red close button via `setWindowModified` (free once the `[*]` fix above is applied). No extra work needed for the title bar — macOS renders `[*]` as a bullet `•` before the filename automatically.
- **Windows/Linux:** `setWindowModified` causes Qt to substitute `[*]` with `*` in the title. An explicit on-screen indicator matters more on these platforms since there's no native close-button equivalent.

**Open questions (to discuss before implementing):**  
- Where should the save button live? Top-left of the left panel? Inline in the menu/toolbar area? Inside the axis settings popup?
- Should it be icon-only, text-only, or icon+text?
- Should "Save" and "Save As…" both be surfaced, or just "Save"?

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
