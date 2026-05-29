# Panel Architecture

## Overview

The Pringle UI is split into two primary areas:

```
┌─────────────────────┬────────────────────────────────────────┐
│   LEFT PANEL        │                         [⚙]            │
│                     │                                        │
│  ┌───────────────┐  │           3D VIEWPORT                  │
│  │  CELL LIST    │  │                                        │
│  │  (unified)    │  │        (GPU canvas)                    │
│  │               │  │                                        │
│  │  [eq cells]   │  │                                        │
│  │  [folders]    │  │                                        │
│  │  [sliders]    │  │                                        │
│  │  [comments]   │  │                                        │
│  └───────────────┘  │                                        │
│  [+ Equation]       │                                        │
│  [+ Folder  ]       │                                        │
└─────────────────────┴────────────────────────────────────────┘
```

The left panel contains a single **unified cell list** (`CellListWidget`) holding all cell types — equation, slider, folder, and comment — in one scrollable list. There is no separate data panel or panel divider between them. The ⚙ gear icon in the top-right corner of the viewport opens the **Axis Settings dialog** (a floating non-modal `Qt.Tool` window containing axis bounds, overlay toggles, camera presets, and resolution controls).

---

## The Unified Dependency Graph

All cells live on a single directed acyclic graph (DAG). The graph determines evaluation order. Visual order is cosmetic; cells can be freely dragged and reordered.

Edges in the DAG: cell A → cell B if A defines a name that B references (determined by AST free-variable analysis).

**Reactivity:**

| Cell type | Re-evaluates when... |
|---|---|
| Slider | User drags or animation ticks |
| Lambda / helper | Any upstream cell changes |
| Surface / curve / scatter | Any upstream dependency changes |
| Equation cell in data mode | Auto-evaluates like any equation cell; `→` button forces a fresh random sample |

Equation cells that produce an `(N, 2)` or `(N, 3)` scatter array automatically enter **data mode** — they gain a stale indicator and a `→` run button. In data mode the cell still auto-evaluates on upstream changes, but the `→` button clears the pinned RNG state to force a new random sample (useful for stochastic initializations). The stale indicator goes orange when the expression or any upstream dependency has changed since the last `→` click.

### Cycle Detection

If a cycle is detected (e.g., data cell A references name `g` from lambda cell B, and lambda cell B references output from data cell A), both cells are flagged with a cycle error. Cycles cannot be resolved automatically and require the user to break the dependency chain.

---

## Session Initialization (Boot Sequence)

When Pringle opens a saved YAML session:

1. **Load YAML** — restore all cell content, style, slider values, folder membership, and viewport/camera state from file (two-pass restore: Pass 1 creates cells, Pass 2 applies folder membership and collapse/visible states)
2. **Restore RNG state** — each cell that previously had a pinned RNG state has `_pending_rng_state` populated from the session file so the first rebuild reproduces identical random draws
3. **Single rebuild** — `_rebuild_namespace()` evaluates all cells in DAG order; each cell with a `_pending_rng_state` restores that state before evaluating so random draws are reproducible
4. **Cancel debounce timers** — `setPlainText` during cell creation arms a 300 ms debounce timer on each cell widget; these are stopped immediately after the single rebuild so they cannot re-dirty the session after `_modified` is reset
5. **First render** — renderer draws the scene

---

## Shared Namespace

The shared namespace is the communication channel between all cells. It has layers:

```
Layer 1 (lowest):  numpy/scipy whitelist (always present)
Layer 2:           slider values (reactive; updated on drag/animation)
Layer 3:           equation cell exports (lambdas, arrays — all cells in DAG order)
Layer 4:           grid vars injected per-execution (x, y, u, v, t, etc.)
                   — highest priority; cannot be shadowed
```

**Magic variable names (`z`, `y`, `xyz`, `points`, etc.) are NOT exported to the shared namespace.** They are consumed locally by the renderer and scoped to the cell's local execution namespace only. This means:
- Two cells both using `z = expr` produce two independent surfaces without namespace collision
- The spatial `z` grid variable (if ever injected) is never shadowed by a surface expression
- To reference cell A's surface in cell B, use a lambda: `f(x,y) = expr` in cell A, then `z = a * f(x,y)` in cell B

Slider names cannot shadow spatial reserved names (`x`, `y`, `u`, `v`, `t`). The UI warns if a slider is given a reserved name.

---

## Parametric Grid Defaults

The `(u, v)` parametric grid defaults to `[0, 2π] × [0, 2π]` — captures full rotation for cylindrical and spherical surfaces, the most common parametric surface types. Configurable in the View Settings panel alongside the `(x, y, z)` axis bounds. Resolution matches the `(x, y)` grid resolution.

---

## Camera Controls

The 3D viewport supports both mouse-based and keyboard-based navigation:

**Mouse (default orbit mode via pygfx `OrbitController`):**
- Left-drag: orbit (rotate around orbit target)
- Right-drag / middle-drag: pan camera view
- Scroll: zoom toward/away from orbit target

**Keyboard (WASD + Space/Shift — camera-relative pan):**

WASD moves the *orbit target* in the camera's horizontal reference frame. The camera rides along by the same delta, preserving its orientation and distance. "Forward" (W) always means toward the target's ground projection from the camera's current azimuth; "right" (D) is 90° clockwise from forward in the XY plane. Space/Shift remain world-space Z.

| Key | Movement |
|---|---|
| `W` | Forward in camera's horizontal frame (toward target, projected to XY) |
| `S` | Backward |
| `A` | Left (camera-relative) |
| `D` | Right (camera-relative) |
| `Space` | +Z (world up) |
| `Shift` | −Z (world down) |

Step size = 0.7% of camera-to-target distance per frame; continuous movement while key is held.

**Implementation:** `_apply_movement` (`app.py`) computes `fwd = normalize(target[:2] - cam[:2])` at each tick, then rotates each key's direction vector by the 2D basis `(forward, right)`. Degenerate case (camera directly overhead, `|fwd_xy| < 1e-6`) falls back to world +Y. `_PAN_KEYS` dict and `_pan_target` are unchanged.

Key handling is implemented at the **Qt level** (`keyPressEvent` / `keyReleaseEvent` on `PringleViewport`) rather than through wgpu's event system. This lets `event.accept()` suppress the macOS press-and-hold accent character popover for movement keys. `focusOutEvent` clears held keys to prevent stuck movement when the user switches to the expression panel.

**Orbit target crosshair:** A small three-axis crosshair (muted R/G/B arms, 2.5% of max axis range) is rendered at `controller.target` and updated every frame. Toggled via the "Crosshair" checkbox in View Settings. Helps the user identify the orbit pivot when WASD panning.

**Known limitation:** pygfx's right-drag mouse pan moves the camera view but does not update `controller.target`. After a right-drag pan, the WASD pivot may differ from the visual center. The crosshair makes this visible.

**Camera fitting:** `fit_camera()` always resets `controller.target` to `(0, 0, 0)` after `show_object()`. A new cell being added to the scene triggers `fit_camera()`; subsequent updates to the same cell (slider drag, re-eval) do not move the camera.

---

## Unified Cell List

All cell types share a single scrollable `CellListWidget`. Two add buttons at the bottom — **+ Equation** and **+ Folder** — insert below the currently focused cell (or append if nothing is focused). There is no separate data panel or panel-level divider.

### Equation Cells

Reactive: re-evaluate when any upstream dependency changes. Evaluation order is determined by the unified DAG, not visual position.

**Undefined variable suggestion:** When a cell references a name not defined anywhere:
```
⚠ 'a' is not defined   [+ Add slider for 'a']
```
Clicking inserts a new slider cell with name `a`, default value `1`, range `[0, 10]`.

**Style updates are non-reactive:** Changing a cell's color, opacity, size, or colormap via the style popover emits `style_updated` (not `content_changed`) and re-applies the cached last result without re-evaluating the expression. Folder visibility toggles likewise re-apply cached results for member cells.

### Folders

Collapsible groups created via **+ Folder**. Each cell carries a `folder_id` pointer. Drag a cell into a folder's indent zone to assign membership; drag out to remove. Folder headers have:
- Collapse/expand toggle (hides member cells from view; members still evaluate and render)
- Eye icon (viewport visibility toggle for all members without changing their individual `visible` flags)
- Click-to-edit name label

Dragging a folder header moves the entire folder+members block as a unit, maintaining relative order. Hidden (collapsed) member cells are skipped in drop-target computation.

### Comment Cells

A cell morphs to a comment when its first character is `#`. Comment cells use a `_CommentEdit` (`QPlainTextEdit`) that auto-grows vertically. No execution, no namespace contribution. Morphing back from `#` restores the equation cell widget, preserving `cell_id`.

### Constraint and Recursion Sub-cells

Attached to equation cells via the **+** sub-cell button. Each sub-cell uses a `CellTextEdit` (auto-expanding `QPlainTextEdit`) so long constraint or recursion expressions wrap and grow rather than truncating. The Enter key in sub-cells inserts a newline rather than advancing to the next top-level cell.

---

## Slider Animation Evaluation Thread (PERF-015)

Cell evaluation during slider animation runs off the Qt main thread to keep camera interaction smooth. The main thread fires `_anim_tick` every 16 ms and immediately returns; the actual eval runs in a `QThread`-backed worker.

**Key components** (all in `cell_list.py`):

- **`_CellSpec`**: read-only snapshot of one cell's inputs (source, style, constraint/condition/recurrence exprs, visibility) — captured on the main thread before dispatch so the worker never touches Qt objects.
- **`_EvalWorker(QObject)`**: moved to a `QThread` via `moveToThread()`. Receives work via the `eval_requested` queued signal; calls `_eval_spec()` for each spec in dependency order; emits `results_ready` back to the main thread.
- **`_eval_spec()`**: pure function — thread-safe, no Qt access. Takes a `_CellSpec` + shared namespace snapshot → `_CellWorkerResult`.
- **`_dispatch_pending_eval()`**: builds the `_CellSpec` list on the main thread, then either emits to the worker (threaded) or runs inline (synchronous fallback).
- **`_on_eval_results()`**: runs on the main thread via queued connection; applies diagnostics and render callbacks; checks the generation counter before applying.

**Generation counter** (`_eval_generation`): incremented on every synchronous rebuild. If a result arrives from an older generation (e.g., slider changed again while the worker was busy), it is silently dropped.

**Coalescing**: `_pending_eval` stores only the latest `(name, value)` tick. If the worker is still busy when the next tick fires, only the most recent pending tick is dispatched when the worker becomes free. Animation frames are never queued.

**`eval_threaded` parameter** (default `False`): production code (`app.py`) passes `True`. Tests use the synchronous inline path to avoid QThread lifecycle crashes under Python 3.13's incremental GC.

---

## Axis Settings Dialog

The gear icon (⚙) in the top-right corner of the viewport opens a floating **non-modal** `Qt.Tool` dialog (`AxisSettingsDialog`) containing `ViewSettingsWidget`. It is not embedded in the left panel. Clicking ⚙ again or closing the dialog's title bar X hides it. Contains:

**Axis Bounds**
- X, Y, Z min/max numeric inputs
- **Apply Bounds** — rebuilds the grid and re-evaluates all cells; updates the wireframe/overlay extents
- **Equalize Axes** — sets X and Y to `[−z_span/2, +z_span/2]` so all three axes have equal length
- **Fit to Data** — unions the world bounding boxes of all scene objects and sets axis bounds to the result (5% padding, min half-span 0.5)

**Overlay toggles** (checkboxes, all default On):
- **Axes** — X (red), Y (green), Z (blue) lines through the origin
- **Wireframe** — 12-edge bounding box at axis extents
- **Crosshair** — small three-axis indicator at the orbit target, updated every frame
- **Shadow** — flat projection of each object's geometry onto the `z_min` floor plane (dark translucent, ~35% opacity)
- **Light bg** — toggles the viewport background between dark (`#111`) and light (`#f2f2f2`)

**Resolution** — grid resolution `n` (default 64; range 8–256, step 8). Shared by the (x,y) spatial grid.

**Camera presets** — Iso, Top, Front buttons snap to predefined positions; **Fit All** calls `fit_camera()` to frame all visible objects.

All overlay toggle states, background choice, camera position, and orbit target are persisted in the session `view` YAML block.

---

## Cell State

Each cell carries the following state, serialized to YAML:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Stable identifier for dependency graph edges |
| `type` | enum | `equation`, `slider`, `folder`, `comment` |
| `source` | str | The code/text content |
| `visible` | bool | Whether rendered output is shown |
| `folder_id` | UUID or None | Containing folder's cell ID; `None` = top-level |
| `style` | CellStyle | Color, opacity, line width, colormap, render mode, etc. — fully persisted |
| `error` | str or None | Last execution error message |
| `warning` | str or None | Shape mismatch or undefined variable warning |
| `rng_state` | uint32[624] or None | Pinned MT19937 state for cells with random draws; ensures reproducibility across rebuilds and session loads |
| `collapsed` | bool | Folder cells: collapse state |
