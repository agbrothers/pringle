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

The left panel is vertically divided into the **Equation Panel** (top) and the **Data Panel** (bottom). The divider is draggable. Both panels share a common namespace — data panel names are visible to equation panel cells.

---

## Equation Panel

The equation panel contains cells that define what is rendered. Cells are **reactive**: they re-evaluate automatically when their slider or animation dependencies change. They do **not** re-evaluate when data panel cells change (only when the user explicitly re-runs a data cell).

### Execution Model

- **Namespace**: numpy/scipy whitelist + no builtins + spatial grid variables (`x`, `y`, `u`, `v`) + shared namespace (slider values, lambda helpers, data panel outputs)
- **Order**: determined by the dependency graph, not visual order. Visual order is for the user's organizational benefit only.
- **Error handling**: errors are caught per-cell and displayed as inline warnings. The rest of the scene continues rendering.
- **Visibility**: each cell has a toggle. When off, the cell still runs (so its namespace contributions remain available), but its rendered output is suppressed.

### Ordering and the Dependency Graph

Desmos evaluates expressions in dependency order, not visual order. This is the correct model and Pringle adopts it:

1. At parse time, each cell's **free variables** are extracted from the AST — names that are referenced but not defined within the cell itself.
2. These free variables are matched against names defined in other cells (slider cells, lambda/helper cells, data panel cells).
3. A directed acyclic graph (DAG) is built: cell A → cell B means A's output is needed before B can run.
4. A topological sort gives the evaluation order.
5. If a cycle is detected (A depends on B depends on A), both cells are flagged with an error.
6. If a free variable is not defined anywhere, the cell shows a warning and a **"suggest" button** (see below).

When a slider value changes, only the topological subgraph downstream of that slider is re-evaluated.

### Undefined Variable Suggestion

When a cell references a name not defined in any other cell, Pringle displays an inline suggestion:

```
⚠ 'a' is not defined   [+ Add slider for 'a']
```

Clicking the button inserts a new slider cell with:
- Name: `a`
- Default value: `1`
- Range: `[0, 10]`
- Animation mode: static

This mirrors Desmos's UX and guides users toward completing their expression. The suggestion is non-blocking — the cell can still attempt to evaluate; the warning is informational.

### Dragging and Reordering

Visual order is cosmetic. Cells can be freely dragged to any position in the panel. Evaluation order is always determined by the dependency graph, never by visual position. This matches Desmos behavior exactly.

### Folders

Cells can be grouped into **folders** — collapsible sections in the equation panel. Folders:
- Are purely organizational; they have no effect on evaluation order or namespacing
- Can be collapsed to hide their contents from view
- Have a name/label editable by the user
- Can be toggled (all cells within are treated as invisible when folder is toggled off)

### Comment Cells

Any cell whose content begins with `#` (or is explicitly set to comment type) is treated as a comment — a text annotation with no code execution. Markdown rendering is a stretch goal.

---

## Data Panel

The data panel is a **Python execution context for setup code**. It is designed for:
- Sampling from distributions: `d = random.normal(0, 1, (200, 3))`
- Loading data from files
- Running algorithms (sklearn, scipy) whose output is visualized
- Any computation that should run once, not reactively

### Execution Model

- **Namespace**: same numpy/scipy whitelist + no builtins, but no AST safety check (more permissive by design — document this clearly)
- **Order**: cells run top-to-bottom within the data panel (linear execution, like a notebook)
- **Triggering**: cells run **only when explicitly triggered** by the user via a per-cell run button. They do not re-evaluate when sliders change or `t` ticks.
- **Output**: names assigned in a data cell are exported into the shared namespace, where equation panel cells can reference them by name

### Per-Cell Run Button

Each data cell has a **▶ Run** button. Clicking it:
1. Executes that cell's code in the shared data namespace (all previously run cells' outputs are visible)
2. Updates the shared namespace with any new or changed names
3. Triggers re-evaluation of any equation panel cells that reference the changed names

A **▶▶ Run All** button at the top of the data panel re-runs all data cells top-to-bottom. This is the typical starting point when opening a saved session.

This design prevents stochastic operations (random sampling) from being accidentally triggered by slider changes or animation ticks.

### Data Panel Security Note

The data panel runs more permissive code than the equation panel. While `__builtins__` is still removed, no AST check is applied, allowing things like attribute access, comprehensions, and multi-statement logic. The design relies on the numpy/scipy namespace restriction as the primary security boundary. Before any public deployment, the data panel should run in a subprocess or container.

---

## Shared Namespace

The shared namespace is the communication channel between panels. It has layers:

```
Layer 1 (lowest):  numpy/scipy whitelist (always present)
Layer 2:           spatial grid vars injected per-execution (x, y, u, v, t, etc.)
Layer 3:           slider values (updated reactively)
Layer 4:           data panel outputs (updated on explicit run)
Layer 5:           equation panel helper functions / lambdas (updated on cell change)
```

Higher layers can shadow lower layers. Slider names cannot shadow spatial reserved names (`x`, `y`, `z`, `u`, `v`, `t`). The UI should warn if a slider is given a reserved name.

---

## View Settings Panel

A collapsible panel (right side or bottom of viewport) for viewport configuration:
- Axis bounds (x/y/z min, max)
- Grid visibility and density
- Axis labels
- Background color
- Surface default opacity
- Camera preset buttons (top, front, isometric, reset)
- Animation controls (global play/pause, speed multiplier)

These settings do not interact with the expression evaluation system.

---

## Cell State

Each cell (equation or data) carries the following state:

| Field | Type | Description |
|---|---|---|
| `id` | UUID | Stable identifier (used in dependency graph) |
| `type` | enum | `surface`, `curve`, `scatter`, `slider`, `lambda`, `data`, `comment`, `folder` |
| `content` | str | The code/text content |
| `visible` | bool | Whether rendered output is shown |
| `color` | RGB | Per-expression render color |
| `error` | str or None | Last execution error message |
| `warning` | str or None | Shape mismatch or undefined variable warning |
| `last_run` | timestamp | When data cells were last explicitly run |
| `collapsed` | bool | For folder cells |

Cell state is serialized to disk for session persistence (JSON or similar).
