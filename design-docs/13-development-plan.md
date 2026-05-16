# Development Plan

## Implementation Status (as of 2026-05-16)

All planned phases (0–12) are **complete**. The prototype is fully runnable via `python -m pringle.app`. 44 tests pass across unit, integration, and GPU offscreen rendering suites.

### Completed phases
| Phase | Description | Status |
|---|---|---|
| 0 | Project setup, dependencies, package structure | ✓ |
| 1 | GPU baseline — pygfx surface + orbit controls | ✓ |
| 2 | Expression evaluation engine | ✓ |
| 3 | Qt + pygfx integration (QRenderWidget) | ✓ |
| 4 | Cell widget UI | ✓ |
| 5 | Live cell list with debounced evaluation | ✓ |
| 6 | Slider cells with reactive downstream evaluation | ✓ |
| 7 | Dependency graph, topological evaluation, incremental slider updates | ✓ |
| 8 | Constraint and piecewise sub-cells | ✓ |
| 9 | Data panel and recurrence cells | ✓ |
| 10 | View settings panel (axis bounds, camera presets) | ✓ |
| 11 | YAML session persistence (Ctrl+S/O/N) | ✓ |
| 12 | Polish — undo/redo, copy/paste, folders, style popover, empty state | ✓ |

### Post-plan features added
| Feature | Description |
|---|---|
| GPU rendering tests | `tests/test_rendering.py` — offscreen frame capture tests for the full evaluator→mesh→GPU pipeline |
| Smooth constraint edges | Triangle boundary clipping (`_clip_mesh_to_mask`) replaces NaN staircase |
| Zero-size buffer guard | Invisible placeholder mesh when all triangles clipped (surfaces, scatter, lines) |
| Scatter fallback | Any (N,3)/(N,2) variable auto-plotted, not just the magic name `points` |
| Camera orbit fix | `controller.target` always reset to origin after fit; no camera jump on slider update |
| CellWidget morphing | Typing `a = 1` in any cell promotes it to a SliderWidget in-place |
| Coordinate axes + wireframe box | Permanent overlay with X/Y/Z lines and 12-edge bounding box; all three toggleable |
| Equalize Axes button | Sets x/y span to match the z span (`[−z_span/2, +z_span/2]`) for equal-length axes |
| WASD world-space pan | Moves orbit target in world axes; continuous hold via Qt key events; macOS accent popover suppressed |
| Orbit crosshair | Small three-axis indicator at `controller.target`, updated every frame |
| Dark theme | Style popover and constraint inputs use dark backgrounds |
| Default YAML format | File dialogs default to `.yaml` instead of `.pringle` |
| Slider redesign (2-row) | New layout: value spinbox top-right, min/max/step below bar; no ticker buttons; smart integer display; range auto-expand; step snapping |
| Unified cell list | Equation and data cells in one scrollable list; `+ Equation` / `+ Data cell` buttons; data cells run on demand, share equation namespace |
| Data cell namespace | Data cells see all slider values and equation exports; exports persist across reactive rebuilds |
| Inline value preview | Gray text below each cell: scalar value or 1D array elements (left), array shape (right); bare expressions also previewed |
| Z bounds UI | Z min/max spinboxes restored to Axis Bounds panel; persisted in session file |
| Unified size control | Style popover "Size" sets both line_width and point_size together |
| Bug fixes | BUG-002, BUG-003, BUG-007, BUG-008 (false undefined warnings for function-definition cells) |

### Open items (see `14-backlog.md`)
- BUG-001: Constraint edge clipping still visibly jagged at normal resolutions
- BUG-006: Camera shifts when toggling cell visibility
- Axis labels (tick marks, "X"/"Y"/"Z" text) — deferred to v2

---

## Guiding Principles

1. **Vertical slices, not horizontal layers** — each phase produces something visually runnable and testable, not an invisible engine layer.
2. **PNG frame capture from day one** — every phase that touches the renderer includes a headless render test. This closes the loop between code changes and visual correctness without manual inspection.
3. **Defer complexity** — the evaluation engine, dependency graph, and YAML serialization are all independently testable before UI is wired up.

---

## PNG Frame Capture Strategy

pygfx + wgpu-py supports offscreen rendering — a GPU surface rendered to a texture, read back to CPU, and saved as a PNG using Pillow or imageio. This works headlessly (no display required) and inside pytest.

```python
# Pseudocode: offscreen render → PNG
renderer = gfx.WgpuRenderer(gfx.offscreen_target((800, 600)))
renderer.render(scene, camera)
frame = renderer.target.read()          # numpy array, shape (H, W, 4), dtype uint8
import imageio
imageio.imwrite("tests/frames/frame.png", frame)
```

Each phase below includes a `tests/frames/` PNG that should be inspected after each run. Automated checks assert:
- Frame is not all black (renderer is producing output)
- Frame is not all one color (mesh is visible, not degenerate)
- Optionally: pixel-level regression comparison against a stored reference PNG (generated once, checked into git)

---

## Phase 0: Project Setup

**Goal**: working package structure, dependencies installed, tests run.

### Tasks
- Update `pyproject.toml`: add `pygfx`, `wgpu`, `PyQt6`, `imageio`, `pytest`, `pyyaml`
- Create package: `pringle/` with `__init__.py`
- Create `tests/` directory with `conftest.py`
- Confirm `uv sync` installs cleanly on macOS

### Test
```
pytest tests/ --collect-only   # should find tests without errors
python -c "import pygfx, wgpu, PyQt6"   # should import cleanly
```

---

## Phase 1: GPU Baseline — Standalone pygfx Surface

**Goal**: render a hardcoded `sin(x)*cos(y)` surface in a standalone wgpu window with orbit controls. No Qt yet.

### Tasks
- Create `pringle/renderer.py`: builds a pygfx scene with a hardcoded surface mesh
- Wire up `OrbitController` with default mouse bindings
- Save one frame to `tests/frames/phase1_surface.png`
- Add WASD key event handler using `OrbitController` methods

### File: `pringle/renderer.py`
Key objects:
```
WgpuRenderer
  Scene
    DirectionalLight
    AmbientLight
    Mesh(geometry=BufferGeometry, material=MeshPhongMaterial)
  PerspectiveCamera
  OrbitController
```

### Test
- `tests/test_phase1.py`: headless render of a 64×64 sin(x)*cos(y) mesh → `phase1_surface.png`
- Visual inspection: smooth blue surface, visible shading gradient, no black frame

---

## Phase 2: Expression Evaluation Engine

**Goal**: evaluate arbitrary numpy expressions on a spatial grid and produce correctly shaped arrays.

### Tasks
- Create `pringle/namespace.py`: build `EQUATION_NAMESPACE` from explicit numpy/scipy imports
- Create `pringle/safety.py`: `SafetyChecker` AST `NodeVisitor`; `check_ast(tree)` raises on `Import`, `ImportFrom`, `Call` to forbidden names
- Create `pringle/grid.py`: `make_grid(x_bounds, y_bounds, n)` → `x, y` meshgrids (N, M)
- Create `pringle/evaluator.py`: `run_cell(source, namespace, grid_vars)` → `local_namespace`
- Create `pringle/preprocess.py`: `preprocess(source)` — handle `f(x,y) = expr` → lambda, comment detection, bare expression capture
- Create `pringle/detect.py`: `detect_output(local_ns, grid)` → `(render_type, data)` or `None`

### Test
- `tests/test_evaluator.py`: unit tests for each expression type
  - `z = sin(x) * cos(y)` → shape `(N, M)` float array
  - `y = x**3` → shape `(N,)` float array
  - `f(x,y) = x**2 + y**2` → lambda in namespace, auto-renders as surface
  - `z = [f, g]` with conditions → piecewise detection
  - Constraint application → NaN at masked positions
  - Security: `import os` → raises; `__import__('os')` → raises
  - Shape mismatch → warning returned, no exception

---

## Phase 3: Qt + pygfx Integration

**Goal**: embed the pygfx canvas in a PyQt6 window. Both event loops run correctly.

### Tasks
- Create `pringle/app.py`: `QApplication` + `QMainWindow`
- Create `pringle/canvas_widget.py`: a `QWidget` that wraps the wgpu canvas as a native window handle (using `pygfx`'s Qt offscreen or native surface support)
- Create `pringle/layout.py`: horizontal splitter — left panel placeholder + canvas widget
- Confirm: window opens, surface renders, mouse orbit works, window resizes correctly

### Test
- Run `python -m pringle` → window opens with a test surface
- Save screenshot via Qt's `QScreen.grabWindow()` → `tests/frames/phase3_qt_window.png`
- Visual inspection: surface visible in right half, empty left panel

### Notes on wgpu-py + Qt integration
- `wgpu-py` renders into a native OS window handle; embed via `QWindow::fromWinId()` and `QWidget::createWindowContainer()`
- Alternatively, use wgpu's offscreen mode and blit the rendered texture into a `QLabel` or custom `QWidget.paintEvent()` — slower but simpler to set up initially
- Prefer the native handle approach for performance; fall back to blit if integration is difficult

---

## Phase 4: Single Cell UI

**Goal**: a single `QPlainTextEdit` cell that evaluates on edit and renders the result.

### Tasks
- Create `pringle/cell_widget.py`: `CellWidget(QWidget)` — text edit + visibility toggle + color dot
- Debounced evaluation: 300ms after last keystroke, re-evaluate and re-render
- Connect cell output to renderer: replace mesh geometry on update
- Color dot: clicking opens `StylePopover` (stub — just a color picker for now)
- Visibility toggle: eye icon button; toggling hides/shows the mesh in the scene

### Test
- Type `z = sin(x) * cos(y)` → surface appears
- Edit to `z = x**2 - y**2` → surface updates
- Toggle visibility → surface disappears and reappears
- Type invalid Python → red error message below cell, surface remains from last valid eval
- Save frame after each step: `phase4_*.png`

---

## Phase 5: Cell List + Multi-Cell Session

**Goal**: a scrollable list of cells; each is independently evaluated; dependency-unaware (sequential order for now).

### Tasks
- Create `pringle/cell_list.py`: `CellListWidget(QScrollArea)` — ordered list of `CellWidget`
- Enter key at end of cell → inserts new empty cell below
- Backspace on empty cell → deletes cell and moves focus up
- Drag handle on each cell → reorder via drag
- "+" button below list → append new cell
- Sequential evaluation: cells run top-to-bottom; shared namespace accumulates
- Multiple surfaces render simultaneously

### Test
- Two cells: `z = sin(x)*cos(y)` and `z = -sin(x)*cos(y)` → two surfaces in scene
- Reorder cells → evaluation order changes (observable when cells reference each other)
- Delete second cell → only first surface remains
- Save frame: `phase5_two_surfaces.png`

---

## Phase 6: Slider Cells

**Goal**: `a = 1.5` is detected as a slider; dragging it updates all dependent cells.

### Tasks
- Extend `detect.py`: if the cell is a bare scalar assignment (`a = 1.5`), return `cell_type = "slider"`
- Create `pringle/slider_widget.py`: `SliderWidget(QWidget)` — name label + drag handle + value display + range endpoints + animation mode selector
- Slider drag → updates value in shared namespace → triggers re-evaluation of downstream cells
- Animation mode: clicking ▷ increments `t` (or the slider) via a `QTimer`; loop/bounce/once

### Test
- Add cell `a = 2.0`, then `z = a * sin(x) * cos(y)` → slider appears; drag updates surface
- Animation loop: `t` slider loops from 0 to 6.28 → surface animates
- Save frame at `t = π/2`: `phase6_animated.png`

---

## Phase 7: Dependency Graph

**Goal**: cells re-evaluate in correct topological order; only affected cells re-evaluate on change.

### Tasks
- Create `pringle/dag.py`: `build_dag(cells)` → `nx.DiGraph` (or hand-rolled); `topological_sort(dag)` → ordered cell list
- Free-variable extraction: `get_free_names(source)` using `ast` (already in evaluator)
- On slider drag: find cells downstream of the slider in the DAG; re-evaluate only those
- Undefined variable warning: if a free name is not in the DAG, show inline `⚠ 'a' is not defined [+ Add slider]`
- "Add slider" button: inserts a new slider cell for the missing name

### Dependencies: use `networkx` (lightweight; add to pyproject.toml) or implement topological sort manually.

### Test
- Three cells: `a = 2`, `f(x,y) = a * x`, `z = f(x,y) + a` → change `a` → only the last two re-evaluate (not `f` definition, since `f` depends on `a` already)
- Cycle detection: `a = b + 1`, `b = a - 1` → both cells flagged with cycle error
- Undefined variable: `z = q * sin(x)` with no `q` defined → inline warning appears

---

## Phase 8: Sub-Cells (Constraints and Piecewise)

**Goal**: constraint sub-cells mask surfaces; piecewise list syntax works.

### Tasks
- Add "+" dropdown to `CellWidget`: "Add Constraint" appends a `ConstraintSubCell`
- `ConstraintSubCell`: indented, dashed border, filter icon; evaluates boolean expression with `x`, `y`, `z` in scope
- Backend: `apply_constraints(z, constraint_exprs, ns)` → `np.where(mask, z, nan)`
- Piecewise detection: if magic variable is a Python list + N condition sub-cells → `np.select` evaluation

### Test
- `z = x**2 + y**2` with constraint `x**2 + y**2 < 4` → circular disc surface (not full paraboloid)
- Piecewise: `z = [lambda x,y: x**2, lambda x,y: -x**2]` with condition `x > 0` → two-piece surface
- Save frame: `phase8_constraint.png`, `phase8_piecewise.png`

---

## Phase 9: Data Panel and Recurrence Cells

**Goal**: data panel with ▶ Run button; recurrence cells execute correctly.

### Tasks
- Create `pringle/data_panel.py`: `DataPanelWidget` — same cell list structure as equation panel but with ▶ Run button per cell and ▶▶ Run All button at top
- Data cell execution: runs once on ▶ Run; output goes to shared namespace; stale badge when upstream changes
- Create `pringle/recurrence.py`: `parse_recursion_rule()`, `execute_recurrence(cell, namespace)`; NaN-fill + loop + NaN detection warning
- Recurrence cell UI: primary expression + `initial_condition` sub-cells + `recursion` sub-cell

### Test
- Data cell: `import` statement → blocked by security check; show error
- Data cell: `d = np.random.randn(100, 3)` → points appear as scatter in viewport
- Recurrence: `path = zeros((50, 2)); initial_condition: path[0] = array([1.0, 0.0]); recursion: path[n] = path[n-1] @ rotation(0.1)` → spiral path plotted as scatter
- Save frame: `phase9_recurrence.png`

---

## Phase 10: View Settings Panel

**Goal**: axis bounds are configurable; all viewport toggles work.

### Tasks
- Create `pringle/view_settings.py`: `ViewSettingsWidget` — axis bound inputs, toggles, camera preset buttons, resolution slider
- Changing bounds → rebuild grid → mark all cells stale → re-evaluate
- Camera presets → set `OrbitController` position/target
- Grid resolution slider → rebuild grid + re-evaluate
- "Fit all" → compute bbox of all meshes, set bounds + recenter camera

### Test
- Change X bounds to [-10, 10] → grid regenerates, surface stretches
- Toggle axes off → axis lines disappear
- Click "Top" preset → camera snaps to top-down view; save `phase10_top_view.png`

---

## Phase 11: Session Persistence (YAML Save/Load)

**Goal**: full session (cells, styles, slider values, panel layout, viewport) saves to YAML and reloads identically.

### Tasks
- Create `pringle/session.py`: `save_session(cells, viewport_state, layout, path)` → YAML; `load_session(path)` → restores full state
- Wire Ctrl+S / Ctrl+O / Ctrl+N to file dialogs
- Boot sequence on load: build DAG → eval reactive cells → Run All data → eval render cells → render
- Unsaved changes indicator in title bar

### Test
- Save a session with two surfaces + a slider + a data cell
- Close and reopen → session reloads, surfaces identical
- Diff the YAML before/after reload → should be identical
- Automated: `test_session_roundtrip.py` saves, reloads, renders to PNG, compares against reference

---

## Phase 12: Polish and QoL

**Goal**: keyboard shortcuts, undo/redo, folders, copy/paste cells, style popover completion.

### Tasks
- `QUndoStack`: track all cell mutations; Ctrl+Z / Ctrl+Y
- Copy/paste cells (Ctrl+C / Ctrl+V)
- Folder cell: `FolderCellWidget` — collapsible group with drag-in/out support
- Complete style popover: hex color input, opacity slider, line width, display mode, label toggle
- Empty state placeholder: "Press + to add an expression"
- Loading indicator for long evaluations (>100ms)
- Window title with unsaved-changes asterisk

---

## Build Order Summary

| Phase | Deliverable | Validates |
|---|---|---|
| 0 | Project setup | Deps install, tests run |
| 1 | Standalone pygfx surface | GPU render pipeline works |
| 2 | Evaluation engine | Expression → array, security, shape validation |
| 3 | Qt + pygfx integration | Two event loops coexist |
| 4 | Single cell UI | Edit → render loop |
| 5 | Cell list | Multi-cell sessions, ordering |
| 6 | Slider cells | Reactive parameter updates, animation |
| 7 | Dependency graph | Correct evaluation order, undefined var suggestion |
| 8 | Sub-cells | Constraints, piecewise |
| 9 | Data panel + recurrence | Non-reactive execution, array-building patterns |
| 10 | View settings | Axis bounds, camera presets |
| 11 | YAML session | Save/load, boot sequence |
| 12 | Polish | Undo, folders, shortcuts |

Phases 1 and 2 are **fully independent** — they can be developed in parallel. Phases 3–5 must be sequential. Phases 6 and 7 can overlap (slider detection is straightforward; DAG wiring can follow). Phases 8, 9, 10 are independently parallelizable after Phase 7.

---

## Testing Checklist per Phase

Every phase should produce:
1. A `tests/test_phaseN.py` with at least one automated assertion (non-black frame, correct array shape, expected error raised)
2. One or more saved frames in `tests/frames/phaseN_*.png` for visual inspection
3. A brief note in `tests/frames/README.md` describing what each frame should look like

### Reference Frame Workflow

1. Run phase, inspect frame manually, confirm it looks correct
2. Commit the PNG to `tests/frames/references/phaseN_*.png`
3. Add a regression test: `assert pixel_similar(current_frame, reference_frame, tolerance=0.02)`
4. Future runs detect regressions automatically

`pixel_similar` = mean absolute per-pixel difference < tolerance (2% handles minor anti-aliasing variation).

---

## Recommended Starting Point

Begin with **Phase 0** (setup) and **Phase 1** (GPU baseline) in the same sitting — they're both short. Then **Phase 2** (evaluation engine) can be written and fully unit-tested independently of any UI. Having all three done before touching Qt means the Qt integration (Phase 3) starts from a solid, tested foundation.

The mockup goals from `05-architecture-decisions.md` map to phases:
1. GPU renders surface + orbit controls → Phase 1
2. Numpy expression evaluated on grid → Phase 2
3. Slider updates surface in real time → Phase 6
4. Expression panel + GPU canvas in same window → Phase 4
5. Constraint sub-cell masks surface → Phase 8
