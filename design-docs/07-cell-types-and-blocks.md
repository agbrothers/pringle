# Cell Types and Multi-line Blocks

## Block Structure

An equation **block** is one primary expression cell plus its typed sub-cells. Sub-cells are added via a "+" button on the primary cell and represent equation-specific metadata — not general computation. The allowed sub-cell types are:

```
[Primary expression cell]      ← magic name assignment or bare auto-plot expression
  [Constraint sub-cell]        ← boolean expression; added via + button
  [Constraint sub-cell]        ← multiple constraints allowed
  [Color function sub-cell]    ← future: scalar → color mapping
```

**Sub-equations are not allowed within a block.** Helper functions (`f(x,y) = ...`) and intermediate computations are their own top-level cells. The dependency graph handles ordering — a cell that references `f` will automatically evaluate after the cell that defines `f`, regardless of visual position. See `06-panel-architecture.md` for the ordering model.

---

## Primary Expression Cell

The primary cell contains a single Python expression — either a magic name assignment or a bare expression. It does not contain multiple assignment lines. All computation beyond the magic name itself belongs in separate top-level cells (lambdas, sliders, data cells).

### Magic Variable Names

The output type is determined by which magic name is assigned:

| Magic name | Render type | Expected shape | Example |
|---|---|---|---|
| `z` | Explicit surface | `(N, M)` float, matching `(x, y)` grid | `z = sin(x) * cos(y)` |
| `y` | Curve in 3D | `(N,)` float, matching `x` grid | `y = x**3` |
| `x` | Curve (implicit role) | `(N,)` float, matching `y` grid | `x = sin(y)` |
| `xyz` | Parametric surface or curve | `(3, N, M)` or `(3, N)` float | `xyz = array([cos(u), sin(u), v])` |
| `points` | Scatter plot | `(N, 3)` float | `points = d` |
| `vectors` | Vector field | future | |

### Bare Expression Auto-Plot

A primary cell whose content is a bare expression — no assignment, just a name or expression that evaluates to an array — is auto-detected and plotted based on output shape:

| Output shape | Inferred type | Notes |
|---|---|---|
| `(N, 2)` | 2D scatter | Two-column array of (x, y) points |
| `(N, 3)` | 3D scatter | Three-column array of (x, y, z) points |
| `(N, M)` matching grid | Explicit surface | Rare for bare expressions; more common via `z =` |

**Rationale:** This mirrors Desmos's behavior (writing a list name plots it as points) and enables the most natural way to visualize data from the data panel — write the variable name and it appears. It also means scatter plots can be created without the ceremony of `points = d` when the shape is unambiguous.

**Previous assumption (revised):** The original design required all renderable output to come from explicit magic name assignments. The bare auto-plot feature is a deliberate extension of this to reduce friction for data visualization.

### `f(x,y) = expr` Function Definition Cells

A top-level cell whose content matches the pattern `name(args) = expr` is detected during preprocessing and converted to a lambda assignment before execution:

```
f(x,y) = x**2 + y**2
→ (preprocessed to) →
f = lambda x, y: x**2 + y**2
```

This is not a sub-cell; it is a standalone top-level cell. After preprocessing and execution, `f` is available in the shared namespace for any other cell that references it. The dependency graph tracks `f` as a defined name in this cell and a free variable in cells that call it.

**Rationale:** `f(x,y) = expr` is unambiguous (never valid Python syntax), closely matches mathematical notation, and is far more readable than the explicit lambda form. The preprocessing step is trivial. This is a direct Python analog to Desmos's `f(x,y) = ...` function definition.

**Detection pattern:**
```python
import re
FUNC_DEF = re.compile(r'^(\w+)\(([^)]*)\)\s*=\s*(.+)$')

def preprocess_func_def(line):
    m = FUNC_DEF.match(line.strip())
    if m:
        name, args, body = m.groups()
        return f"{name} = lambda {args}: {body}"
    return line
```

---

## Constraint Sub-cells

Constraint sub-cells are UI elements — they appear as distinct input boxes attached to the primary cell, not as text the user types in the main expression. The user adds them by clicking a "+" button. Each constraint sub-cell contains one boolean expression.

The cell visually distinguishes constraint sub-cells (e.g., shaded differently, labeled "where" or with a filter icon) so the user does not need to write any constraint syntax in the primary expression.

**Backend evaluation:**

1. Execute the primary expression to obtain the magic variable value (e.g., `z`)
2. For each constraint sub-cell expression, evaluate it in the same namespace with `z` available:
   ```python
   mask_i = eval(constraint_expr, {**namespace, "z": z})  # shape (N, M), dtype bool
   ```
3. Combine all masks:
   ```python
   mask = np.logical_and.reduce([mask_1, mask_2, ...])
   ```
4. Apply mask:
   ```python
   z_out = np.where(mask, z, np.nan)
   ```

NaN values cause the corresponding mesh triangles to be degenerate (collapsed) and are skipped by the renderer. This produces clean clipping without visual artifacts when the grid is sufficiently dense near the boundary.

**What constraints cover:**
- Spatial domain restriction: `x**2 + y**2 < 1` — clips the surface to a disk
- z-value filtering: `z > 0` — shows only the positive lobe (z must be evaluated first)
- Compound regions: multiple constraints → intersection (AND). Union requires either separate cells with complementary constraints or an OR expression within a single constraint box
- Arbitrary boundary shapes: any boolean-valued expression over the grid

**What constraints do NOT cover — use `where()` instead:**

True piecewise functions (different formulas in different regions, not just masking) are best expressed with `where()` directly in the primary expression:

```python
z = where(x > 0, x**2, -x**2)
```

`where` is in the numpy namespace. For complex piecewise logic, multiple `where` calls can be nested, or multiple equation cells with complementary constraint sub-cells can be used (each rendering a separate mesh that together appears as one surface).

**Constraint evaluation note:** if the primary expression produces `nan` at some grid points (e.g., `sqrt` of a negative number), those points evaluate as `nan < 1 → False`, so they are naturally excluded by any constraint. No special handling required.

---

## Slider Cells

A single scalar assignment: `a = 1.5`. The UI renders this as a drag handle with editable range and animation controls. The value is injected as a scalar into the shared namespace.

`t` is a reserved built-in slider controlling animation time. It is always present and cannot be redefined.

---

## Data Cells

See `06-panel-architecture.md` for the data panel. Data cells are in a separate panel section with their own per-cell ▶ Run button. They are not part of the equation block structure.

---

## Comment Cells

Plain text. No execution. No namespace contribution. Used for annotation and organization.

---

## Visibility Toggle

Each cell has a visibility toggle. When toggled off:
- The cell still executes (namespace contributions remain available to dependent cells)
- The rendered output is suppressed — nothing is submitted to the renderer

This allows:
- Building modular helper definitions (lambdas, sliders) that are never directly visible
- Composing multiple expressions and selectively rendering only the final result
- A/B comparisons by toggling cells on and off

---

## Shape Validation

Shape validation runs after every cell execution. Mismatches are displayed as inline warnings on the cell; the renderer is not invoked for that cell.

| Magic name | Expected shape | Common mistake |
|---|---|---|
| `z` | `(N, M)` matching `x.shape` | Scalar returned; forgot that x, y are 2D arrays |
| `y` / `x` | `(N,)` matching x/y grid size | 2D array returned instead of 1D |
| `xyz` | `(3, N)` or `(3, N, M)` | Wrong axis: `(N, 3)` instead of `(3, N)` |
| `points` (auto) | `(N, 2)` or `(N, 3)` | Wrong number of columns |

For `xyz`, both `(3, N, M)` and `(N, M, 3)` are accepted — Pringle checks which axis has size 3 and transposes if needed.

NaN and Inf values in the output are not errors — they are filtered at the renderer level (NaN vertices produce degenerate triangles that are skipped).
