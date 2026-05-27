# Cell Types and Multi-line Blocks

## Block Structure

An equation **block** is one primary expression cell plus its typed sub-cells. Sub-cells are added via a "+" button on the primary cell and represent equation-specific metadata — not general computation. Allowed sub-cell types:

```
[Primary expression cell]      ← magic name, f(x,y) def, or bare auto-plot expression
  [Constraint sub-cell]        ← boolean expression; visual indicator (dashed border / filter icon)
  [Constraint sub-cell]        ← multiple constraints allowed
  [Color function sub-cell]    ← future: scalar → color mapping
```

**Sub-equations are not allowed within a block.** Helper functions (`f(x,y) = ...`) and intermediate computations are their own top-level cells. The dependency graph handles ordering regardless of visual position.

---

## Primary Expression Cell

### Magic Variable Names

Output type is determined by which magic name is assigned. These take priority over all other detection methods.

| Magic name | Render type | Expected shape | Example |
|---|---|---|---|
| `z` | Explicit surface | `(N, M)` float, matching `(x, y)` grid | `z = sin(x) * cos(y)` |
| `y` | Curve in 3D | `(N,)` float, matching `x` grid | `y = x**3` |
| `xyz` | Parametric surface or curve | `(3, N, M)` or `(3, N)` float | `xyz = array([cos(u), sin(u), v])` |
| `points` | Scatter plot | `(N, 3)` or `(N, 2)` float | `points = d` |
| `vectors` | Vector field | `(N, 6)` float — tail+head pairs | via shape inference (see below) |


The last dimension of an array determines what plotting options to use. The data in the last dimension is viewed as follows:

```
|  SHAPE: (N, 2)     |  SHAPE: (N, 3)      |  SHAPE: (N, 4)        |  SHAPE: (N, 6)          |
|             |      |             |       |             |         |             |           |
|             v      |             v       |             v         |             v           |
|           [0 1]    |         [0  1  2]   |       [0  1 | 2  3]   |    [0  1  2 | 3  4  5]  |
|            x y     |          x  y  z    |        x  y | x  y    |     x  y  z | x  y  z   |
|                    |                     |        tail | head    |       tail  |  head     |
|             •      |             •       |         ------->      |         ------->        |
|         2D POINTS  |         3D POINTS   |        2D VECTORS     |        3D VECTORS       |
```

---

## Function Cells  -  `f(x,y) = expr` 

A cell whose content matches `name(args) = expr` is a function definition cell. Preprocessing converts it to a lambda before AST parsing. After execution, the function is added to the shared namespace for all other cells.

**Auto-render rule:** if all arguments are spatial/reserved variables, the function also auto-renders:

| Signature | Auto-renders as | Shape |
|---|---|---|
| `f(x, y)` | Surface: evaluates `z = f(x, y)` over grid | `(N, M)` |
| `f(x)` | Curve: evaluates `y = f(x)` over x-grid | `(N,)` |
| `f(u, v)` | Parametric surface over (u,v) grid | `(3, N, M)` if result is 3D |
| Any other args | Namespace-only; no auto-render | — |

The visibility toggle controls the auto-rendered output. The function is always available in the shared namespace regardless of visibility.

**Preprocessing:**
```python
import re
FUNC_DEF = re.compile(r'^(\w+)\(([^)]*)\)\s*=\s*(.+)$')

def preprocess_func_def(line: str) -> str:
    m = FUNC_DEF.match(line.strip())
    if m:
        name, args, body = m.groups()
        return f"{name} = lambda {args}: {body}"
    return line
```

---

## Magic Variable Scoping

Magic variable names (`z`, `y`, `xyz`, `points`, `vectors`) are **local to the cell's execution and consumed by the renderer only**. They are never exported to the shared namespace.

This means:
- Two cells both writing `z = expr` produce two independent surfaces — no namespace collision
- The spatial `z` grid (if ever injected for implicit surfaces) is never shadowed by a surface expression
- To reference one cell's surface in another, use a lambda: define `f(x,y) = expr` in cell A, then write `z = a * f(x,y)` in cell B

Constraint sub-cells receive the computed magic variable in their local namespace — the post-evaluation surface array, not a spatial grid variable.

---

## Bare Expression Auto-Plot

A cell whose content is a bare expression (no assignment) is auto-detected and plotted based on return shape. Priority order for output detection:

1. **Magic name assignment** — takes absolute priority
2. **Function signature** — if the cell defines `f(spatial_args) = expr`, auto-render applies
3. **Return shape inference** — for bare expressions or function calls returning arrays

### Shape Inference Rules

| Return shape | Render type | Preview shown |
|---|---|---|
| `(N, 6)` | Vectors (3D tail+head pairs) | shape |
| `(N, 4)` | Vectors 2D (2D tail+head pairs, z=0) | shape |
| `(k, N, 6)` | Vectors (channels-last, flattened) | shape |
| `(k, N, 4)` | Vectors 2D (channels-last, flattened) | shape |
| `(6, N, M)` | Vectors (channels-first, flattened) | shape |
| `(4, N, M)` | Vectors 2D (channels-first, flattened) | shape |
| `(k, N, 3)` | Batch 3D scatter (`k` lines of `N` points) | shape |
| `(k, N, 2)` | Batch 2D scatter (`k` lines of `N` points) | shape |
| `(N, 3)` | 3D scatter | shape e.g. `(100, 3)` |
| `(N, 2)` | 2D scatter | shape |
| `(3,)` | Single 3D point (scatter) | element values + shape `(1, 3)` |
| `(2,)` | Single 2D point | element values + shape |
| Scalar | No render | value |
| `(N,)` | No render | first k element values |
| `(N, M)` not matching grid | No render | — |
| Python list | No render | — |

Vector arrays are detected before scatter so `(N, 6)` is never misread as `(N, 3)`. `(N, 6)` arrays render as 3D arrows (tail and head in columns 0–2 and 3–5). `(N, 4)` arrays render as 2D arrows in the z=0 plane. Setting `scatter_render_mode = "arrows"` on a scatter cell converts N consecutive scatter points into N−1 flow arrows (each point → next).

This applies to cells like `dx(p)` (bare function call returning a scalar) or `array([dx(p), dy(p), dz(p)])` (bare expression returning a 1D array). The return value is captured via `eval` after `exec` and formatted for the preview label.

### Value Preview

Every equation cell shows small gray text below the cell body:
- **Left-aligned**: scalar value or 1D array elements (e.g. `[0, 26, -1.667]`), truncated with `...` if too wide
- **Right-aligned**: array shape for rendered outputs (e.g. `(64, 64)`)

Both can appear simultaneously (e.g. `p = array([1,1,1])` shows `[1, 1, 1]` left and `(1, 3)` right). Integers are shown without decimal points. The preview updates on every evaluation.

---

## Piecewise Expression Cells

A primary cell that assigns a magic name to a **Python list of callables or arrays** is treated as a piecewise function when condition sub-cells are present.

```
z = [f, g, h]
  [condition sub-cell]: x**2 + y**2 < 1
  [condition sub-cell]: x**2 + y**2 < 2
  [condition sub-cell]: x**2 + y**2 >= 2
```

**UI behavior:** when a piecewise definition with N pieces is detected, the UI automatically creates N empty condition sub-cells. A warning is shown (and rendering is suppressed) if the number of non-empty conditions ≠ number of pieces.

**Backend evaluation:**
```python
# Evaluate all pieces over the grid
pieces = [p(x, y) if callable(p) else p for p in piece_list]

# Build exclusive conditions (each implicitly negates all prior)
exclusive_conditions = []
accumulated = np.zeros_like(x, dtype=bool)
for raw_cond in raw_conditions:
    exclusive = raw_cond & ~accumulated
    exclusive_conditions.append(exclusive)
    accumulated |= raw_cond

z = np.select(exclusive_conditions, pieces, default=np.nan)
```

The implicit prior-negation ensures conditions are mutually exclusive — the first matching condition wins, matching standard piecewise convention and Desmos behavior.

**Detection:** after execution, if the magic variable is a Python list (not a numpy array) and condition sub-cells are present → piecewise mode. If it's a list with no condition sub-cells → warn.

---

## Constraint Sub-cells

Constraint sub-cells are UI elements — separate input boxes with a visual indicator (dashed border, filter icon). Users add them via a "+" dropdown, not by typing syntax in the primary cell.

**Backend:**
1. Execute the primary expression → obtain magic variable value (e.g., `z`)
2. For each constraint sub-cell, evaluate the boolean expression with `z` available:
   ```python
   mask_i = eval(constraint_expr, {**namespace, "z": z})
   ```
3. Combine: `mask = np.logical_and.reduce([mask_1, mask_2, ...])`
4. Apply: `z_out = np.where(mask, z, np.nan)`

Constraints can reference the computed `z` value (useful for `z > 0` type filtering). NaN values cause degenerate mesh triangles to be skipped by the renderer. Constraint expressions that produce NaN (e.g., `sqrt` of a negative) naturally evaluate as False.

**True piecewise vs constraints:** constraints mask a surface (hide regions). True piecewise (different formulas in different regions) uses either `z = [f, g, h]` with conditions, or `where()` directly in the primary expression:
```python
z = where(x > 0, x**2, -x**2)
```

---

## Comment Cells

A cell whose first character is `#` is treated as a comment cell — free text, never evaluated, no namespace contribution.

```
# This is a note about the equations below.
```

**Layout:** `[drag handle] [auto-grow QPlainTextEdit] [✕]`. The `# ` prefix is stored as literal text inside the edit field — there is no separate margin decoration. New comment cells are created with `source="# "` so the cursor lands after the hash-space.

**Detection and morphing:**
- *Equation → comment:* on focus-out, if an equation cell's source starts with `#`, it morphs to `CommentCellWidget` in place (preserving `cell_id` and style). The full source string (including `# `) is passed to `set_source`, which sets it verbatim into the edit field.
- *Comment → equation (manual):* `Ctrl+/` / `Cmd+/` strips the leading `# ` and morphs back.
- *Comment → equation (auto):* editing the comment text so it no longer starts with `#` triggers an immediate morph back to `CellWidget` via `_on_comment_changed`. This fires on every keystroke; the morph only fires once the first character is no longer `#` (e.g. deleting `# foo` to `foo`, not mid-deletion after only the space is removed).

**`source()` / `set_source()`:** both are pass-through — `source()` returns `_edit.toPlainText()` and `set_source(text)` calls `_edit.setPlainText(text)`. The caller (`_morph_equation_to_comment`) is responsible for constructing the `"# "` prefix; `_morph_comment_to_equation` uses `_HASH_RE` to strip it.

**Previous design (superseded):** an earlier version triggered on Python docstrings (`"""..."""`) detected via `ast.Constant`. This is replaced by the `#` trigger only. Single/double-quoted strings are treated as equation cell content (they evaluate as string literals), not as comments.

---

## Data Mode (Equation Cells with Scatter Output)

Equation cells that produce an `(N, 2)` or `(N, 3)` array (detected by shape inference) automatically enter **data mode**. This is not a separate cell type — it is a UI state of an equation cell. Data mode cells:

- Show a `→` run button and a stale indicator (orange dot) in a second row below the expression
- Auto-evaluate reactively like any equation cell (slider changes, upstream edits, `_rebuild_namespace`)
- Pin their MT19937 RNG state on first evaluation so random draws are stable across passive rebuilds
- Clear the pinned state when the user clicks `→`, producing a fresh random sample

Sub-cells (constraint, condition, initial_condition, recursion) are available regardless of data mode. Recurrence patterns (`path[n] = path[n-1] + ...`) work the same way in equation cells as they did in the old DataCellWidget.

The `→` button is distinct from a re-run: it is a **resample** — it requests new random draws. Passive rebuilds (slider changes, upstream edits) always reproduce the same random output that was pinned at the most recent explicit `→` click or first evaluation.

---

## Slider Cells

A scalar assignment: `a = 0.6`. Typing a bare scalar assignment (including negative literals like `a = -3`) in any equation cell morphs it into a `SliderWidget` in-place on focus-out (preserving `cell_id` and style).

**Layout** (2 rows):
```
Row 1: [●] [name]  [value spinbox ──────────────────────────]  [✕]
Row 2:  [▷]  [min] [──●────────────────] [max]  · step [step]
```

- Up/down ticker buttons are hidden (`NoButtons`)
- Integers display without decimal points; trailing zeros stripped
- Range auto-expands on creation if the initial value falls outside `[0, 10]`
- Values typed into the value field are stored as-is (no clamping); a red border appears on the `min` or `max` field if the value exceeds it, clearing once the bound is widened
- Dragging the slider snaps to exact multiples of the step value; the handle pegs to the nearest end when the stored value is outside the range
- ▷ button animates the slider bouncing between min and max at ~60fps

All slider configuration (min, max, step) is set via the row 2 spinboxes. The current value is preserved in the YAML session file — see `10-session-format.md`.

---

## Visibility Toggle

Each cell has a visibility toggle (controlled via UI; serialized in YAML session). When off:
- Cell still executes and contributes to the shared namespace
- Rendered output is suppressed

This allows building modular helpers (lambdas, intermediate definitions) that are never directly visible, and composing multiple expressions while selectively rendering only the final result.

---

## Shape Validation

Shape validation runs after every cell execution. Mismatches display as yellow inline warnings; the renderer is not invoked for that cell.

| Magic name | Expected | Common mistake |
|---|---|---|
| `z` | `(N, M)` matching x.shape | Scalar returned; forgot that x, y are 2D grids |
| `y` | `(N,)` matching grid | 2D array returned instead of 1D |
| `xyz` | `(3, N)` or `(3, N, M)` | Wrong axis: `(N, 3)` instead of `(3, N)` — Pringle transposes if unambiguous |
| `points` | `(N, 2)`, `(N, 3)`, `(k, N, 2)`, or `(k, N, 3)` | Wrong column count or wrong ndim |

NaN and Inf are not errors — they are filtered at the renderer (degenerate triangles skipped).
