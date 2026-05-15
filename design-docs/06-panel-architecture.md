# Panel Architecture

## Overview

The Pringle UI is split into two primary areas:

```
┌─────────────────────┬────────────────────────────────────────┐
│   LEFT PANEL        │                                        │
│                     │                                        │
│  ┌───────────────┐  │                                        │
│  │  EQUATION     │  │           3D VIEWPORT                  │
│  │  PANEL        │  │                                        │
│  │               │  │        (GPU canvas)                    │
│  │  [cells]      │  │                                        │
│  │               │  │                                        │
│  └───────────────┘  │                                        │
│  ┌───────────────┐  │                                        │
│  │  DATA         │  │                                        │
│  │  PANEL        │  │                                        │
│  │               │  ├────────────────────────────────────────┤
│  │  [cells]      │  │   VIEW SETTINGS (axis bounds, grid...) │
│  └───────────────┘  │                                        │
└─────────────────────┴────────────────────────────────────────┘
```

The left panel is vertically divided into the **Equation Panel** (top) and the **Data Panel** (bottom). The divider is draggable. Both panels operate on the **same dependency graph** — the panel separation is a UI and cell-type distinction only.

---

## The Unified Dependency Graph

All cells — equation and data — live on a single directed acyclic graph (DAG). The graph determines evaluation order. Visual order within each panel is cosmetic; cells can be freely dragged and reordered in either panel.

Edges in the DAG: cell A → cell B if A defines a name that B references (determined by AST free-variable analysis).

**The key axis is reactivity, not panel membership:**

| Cell type | Panel | Re-evaluates when... |
|---|---|---|
| Slider | Equation | User drags or animation ticks |
| Lambda / helper | Equation | Any upstream cell changes |
| Surface / curve / scatter | Equation | Any upstream dependency changes |
| Data cell | Data | User clicks ▶ Run only |
| Recurrence cell | Data | User clicks ▶ Run only |

Non-reactive cells (data, recurrence) show a **stale indicator** (visual badge) when any upstream dependency has changed since their last run. The user chooses when to re-run them. They do not auto-run — not on slider changes, not on lambda edits, not on animation ticks. This prevents chaotic re-sampling of stochastic data.

When the user clicks ▶ Run on a data cell:
1. All upstream reactive cells (sliders, lambdas) are already current — they evaluate continuously
2. Any upstream data cells that are stale are also run first (in dependency order)
3. The target cell runs
4. Downstream cells that have already been run are marked stale

A **▶▶ Run All** button at the top of the data panel re-runs all data cells in dependency order. This is the recommended way to initialize a session on load.

### Why Unified?

A data cell referencing a lambda from the equation panel is handled correctly by the graph — the lambda cell is guaranteed to have evaluated before the data cell runs. No manual boot sequencing required. The separation into two visual panels is purely organizational; it does not affect graph topology.

### Cycle Detection

If a cycle is detected (e.g., data cell A references name `g` from lambda cell B, and lambda cell B references output from data cell A), both cells are flagged with a cycle error. Cycles cannot be resolved automatically and require the user to break the dependency chain.

---

## Session Initialization (Boot Sequence)

When Pringle opens a saved YAML session:

1. **Load YAML** — restore all cell content, style, slider values, and viewport state from file
2. **Build dependency graph** — parse all cells, extract free variables, construct DAG
3. **Evaluate reactive cells** — run all slider and lambda cells in dependency order (no renders yet)
4. **Run data panel** — ▶▶ Run All in dependency order — data cells now have slider values and lambdas available
5. **Evaluate render cells** — run all equation surface/curve/scatter cells in dependency order
6. **First render** — renderer draws the scene

This sequence ensures that data cells which call equation-panel lambdas always have those lambdas available at run time.

---

## Shared Namespace

The shared namespace is the communication channel between all cells. It has layers:

```
Layer 1 (lowest):  numpy/scipy whitelist (always present)
Layer 2:           slider values (reactive; updated on drag/animation)
Layer 3:           equation panel lambda / helper definitions (reactive)
Layer 4:           data panel outputs (updated on explicit ▶ Run)
Layer 5:           grid vars injected per-execution (x, y, u, v, t, etc.)
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

**Mouse (default orbit mode):**
- Left-drag: orbit (rotate around scene center)
- Right-drag / middle-drag: pan
- Scroll: zoom

**Keyboard (WASD + Space/Shift):**
- `W` / `S`: zoom in / out (move camera toward/away from center)
- `A` / `D`: orbit left / right
- `Space` / `Shift`: orbit up / down (traverse z axis)
- Speed is configurable; holding Shift while using mouse panning accelerates movement

Both modes operate on the same orbit camera model — the camera always orbits a center point ("up" is always up). A first-person fly mode (`FlyController` in pygfx / `FlyCamera` in Vispy) is available as a toggle for exploring vector fields or enclosed regions from inside.

Keyboard events are handled by the GPU canvas widget. In PyQt6, these are connected to the camera controller's `pan()`, `zoom()`, and `rotate()` methods. No additional library support is required — both Vispy and pygfx support this natively via key press event callbacks.

---

## Equation Panel

Contains cells that define what is rendered. Cells are reactive: they re-evaluate when their slider or animation dependencies change.

### Ordering and the Dependency Graph

Evaluation order is determined by the unified DAG, not visual position. When a slider value changes, only the topological subgraph downstream of that slider is re-evaluated.

### Undefined Variable Suggestion

When a cell references a name not defined in any other cell:

```
⚠ 'a' is not defined   [+ Add slider for 'a']
```

Clicking inserts a new slider cell with name `a`, default value `1`, range `[0, 10]`, static mode.

### Folders

Collapsible groups of cells. Purely organizational — no effect on evaluation order or namespacing. Folder visibility toggle treats all contained cells as invisible.

### Comment Cells

Detected automatically. A cell is a comment if its content is:
- Entirely `#`-prefixed lines
- A bare string literal: `"""..."""`, `'''...'''`, `"..."`, or `'...'`

No execution; no namespace contribution.

---

## Data Panel

Contains cells for setup computation — sampling distributions, loading data, running algorithms. Cells are **non-reactive**: they only run when explicitly triggered.

### Per-Cell Run Button

Each data cell has a ▶ Run button. Clicking it runs the cell and all upstream stale data dependencies in dependency order. Downstream cells are marked stale.

### Stale Indicator

When any upstream dependency of a data cell has changed since the cell's last run, the cell displays a stale badge (e.g., a small orange dot or "↻ stale" label). The user re-runs manually.

Data cells do NOT auto-update when:
- A slider value changes
- A lambda cell is edited
- Another data cell is re-run

This prevents chaotic re-sampling of stochastic data and avoids triggering expensive computation on every keystroke.

### Security Note

Data cells run more permissive code than equation cells. `__builtins__` is removed but no AST check is applied. The numpy/scipy namespace restriction is the primary security boundary. Before public deployment, data cells should run in a subprocess or container.

---

## View Settings Panel

Collapsible panel (right side or bottom of viewport):
- `(x, y, z)` axis bounds (min, max)
- `(u, v)` parametric grid range (min, max)
- Grid visibility and density
- Axis labels
- Background color
- Camera preset buttons (top, front, isometric, reset)
- Animation controls (global play/pause, speed multiplier)

---

## Cell State

Each cell carries the following state, serialized to YAML:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Stable identifier for dependency graph edges |
| `type` | enum | See `07-cell-types-and-blocks.md` |
| `content` | str | The code/text content |
| `visible` | bool | Whether rendered output is shown |
| `style` | CellStyle | Color, opacity, line width, display mode, etc. |
| `error` | str or None | Last execution error message |
| `warning` | str or None | Shape mismatch or undefined variable warning |
| `stale` | bool | Data cells: true if upstream deps changed since last run |
| `last_run` | timestamp | When data cells were last explicitly run |
| `collapsed` | bool | For folder cells |
| `panel` | enum | `equation` or `data` — UI placement only |
