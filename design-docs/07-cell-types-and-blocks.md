# Cell Types and Multi-line Blocks

## Cell Types

### 1. Equation Cells (Equation Panel)

Equation cells are multi-line Python blocks that produce something renderable. The cell's **output type** is determined by which magic variable name was assigned during execution. Magic names are checked after `exec()` by inspecting the cell's local namespace.

#### Magic Variable Names

| Magic name | Render type | Expected shape | Example |
|---|---|---|---|
| `z` | Explicit surface | `(N, M)` float array matching `(x, y)` grid | `z = sin(x) * cos(y)` |
| `y` | Curve / line | `(N,)` float array matching `x` grid | `y = x**2` |
| `x` | Curve (implicit role) | `(N,)` float array matching `y` grid | `x = sin(y)` |
| `xyz` | Parametric surface or curve | `(3, N, M)` or `(3, N)` float array | `xyz = array([cos(u), sin(u), v])` |
| `points` | Scatter plot | `(N, 3)` float array | `points = random.normal(0,1,(100,3))` |
| `vectors` | Vector field | `(N, M, 6)` — origin xyz + direction xyz | `vectors = ...` |

If multiple magic names are assigned in a single block, the one appearing on the **first line** (the topmost magic assignment) is used as the primary render output. The others become namespace contributions only.

The **first line** convention is cosmetic: it visually declares what the block is for. Evaluation order within the block is still top-to-bottom as Python executes it. The first line is checked for the primary magic name to determine render type.

#### Constraint Lines

Any line in an equation cell that is a **bare boolean expression** (not an assignment) is treated as a constraint:

```python
z = y**2 - x**2            # magic name — the surface
x**2 + y**2 < 1            # constraint — a boolean array over the grid
z > -0.5                   # second constraint
```

After execution:
1. The magic variable value is extracted
2. All bare expression values that are boolean arrays are collected as constraints
3. `mask = constraint_1 & constraint_2 & ...`
4. Final render value: `where(mask, z, nan)` — NaN regions are not rendered

Constraints are detected by inspecting the local namespace after `exec()`: any name auto-assigned to boolean-typed numpy arrays that were not explicitly named by the user. More precisely: the `exec()` runs against a wrapper that intercepts bare expression statements and records their values.

Implementing bare expression capture requires a small AST transform: wrap bare `ast.Expr` nodes in an assignment to a generated name (e.g., `_constraint_0 = expr`), then collect all `_constraint_*` names from the namespace after execution.

#### Helper / Intermediate Lines

Assignment lines that don't assign to magic names are helpers — intermediate computations:

```python
r = sqrt(x**2 + y**2)     # helper
theta = arctan2(y, x)      # helper
z = sin(r) * cos(theta)    # magic name
r < 4                      # constraint
```

Helpers are local to the block and do not leak into the shared namespace unless the block defines a lambda (see below).

### 2. Lambda / Helper Cells

A cell whose top-level assignment is a callable (lambda or defined via `f = lambda ...`) contributes that name to the shared namespace, making it available to all other equation cells:

```python
# Standalone helper cell
f = lambda x, y: sin(sqrt(x**2 + y**2)) / sqrt(x**2 + y**2)
```

Or within an equation cell, a lambda defined before the magic name is available to the block but does not automatically become shared (unless it's a top-level assignment in a dedicated helper cell).

This mirrors Desmos's `f(x,y) = ...` pattern. Lambda names should not conflict with magic names or reserved spatial variables.

### 3. Slider Cells

A slider cell is a single assignment of a scalar:

```
a = 1.5   ──●────────────  [0.0 ............. 5.0]   ▷ loop
```

Controls per slider:
- **Value display**: editable text field showing current value
- **Range inputs**: editable min / max
- **Drag handle**: continuous drag updates value reactively
- **Animation mode button**: cycles through `static → loop → bounce → once`
- **Rate input** (when animating): units per second

Sliders inject their current value as a scalar into the shared namespace. When the value changes (drag or animation tick), all equation cells that reference the slider name are re-evaluated.

`t` is a special built-in slider: always present, controls animation time. Its rate and range are controlled from the View Settings panel.

### 4. Data Cells (Data Panel)

Multi-line Python blocks in the data panel. Executed manually via a ▶ Run button. Results exported into the shared namespace.

```python
# Data cell: sample Gaussian clusters
from numpy import random
centers = array([[0,0,0], [3,0,0], [0,3,0]])
d = vstack([random.normal(c, 0.5, (50, 3)) for c in centers])
labels = repeat([0,1,2], 50)
```

After running, `d` and `labels` are available in the equation panel:

```python
# Equation cell using data
points = d          # scatter plot of all points
```

Or with color mapped to labels (future feature).

### 5. Comment Cells

Plain text cells. Content is displayed as-is (markdown in v2). No execution. No namespace contribution.

### 6. Folder Cells

A collapsible container for other cells. Folders:
- Have a user-editable label
- Can be collapsed (contents hidden in panel, still evaluated unless folder is toggled off)
- Have their own visibility toggle (when off, all contained cells are treated as invisible)
- Do not affect namespacing or evaluation order

---

## Multi-line Block Execution in Detail

```python
def execute_equation_cell(code_str, shared_ns, grid_vars):
    # Step 1: AST safety check
    tree = ast.parse(code_str, mode="exec")
    SafetyChecker().visit(tree)

    # Step 2: transform bare expressions into named assignments for constraint capture
    tree = ConstraintCapture().visit(tree)  # wraps Expr nodes: _c0 = expr, _c1 = expr, ...

    # Step 3: build execution namespace
    local_ns = {**EQUATION_NAMESPACE, **shared_ns, **grid_vars, "__builtins__": {}}

    # Step 4: execute
    exec(compile(tree, "<cell>", "exec"), local_ns)

    # Step 5: extract magic variable
    magic_name, render_type = detect_magic(local_ns, code_str)
    if magic_name is None:
        return CellResult(error="No renderable output found")

    magic_value = local_ns[magic_name]

    # Step 6: validate shape
    expected = expected_shape(render_type, grid_vars)
    if magic_value.shape != expected:
        return CellResult(warning=f"Shape mismatch: got {magic_value.shape}, expected {expected}")

    # Step 7: collect constraints
    constraints = [v for k, v in local_ns.items()
                   if k.startswith("_c") and isinstance(v, np.ndarray) and v.dtype == bool]
    if constraints:
        mask = constraints[0]
        for c in constraints[1:]:
            mask = mask & c
        magic_value = np.where(mask, magic_value, np.nan)

    return CellResult(value=magic_value, type=render_type)
```

`detect_magic` checks the first assignment line in the source for a magic name, then falls back to scanning all assignments in the result namespace.

---

## Visibility Toggle Semantics

| State | Evaluates? | Renders? | Namespace contribution? |
|---|---|---|---|
| Visible | Yes | Yes | Yes |
| Hidden (toggle off) | Yes | No | Yes |
| Folder hidden | Yes | No | Yes |
| Error | Yes (failed) | No | Partial |

Cells always evaluate (so lambda helpers and intermediate names remain available to dependent cells). Only the renderer submission is gated by visibility. This lets you build modular expressions where `f` is defined in a hidden helper cell, and a visible surface cell uses `f`.

---

## Shape Validation

Shape validation runs after every cell execution. Errors are displayed inline on the cell, never propagated as exceptions to the renderer.

| Render type | Expected shape | Common mistake |
|---|---|---|
| Surface (`z`) | `(N, M)` matching `x.shape` | Scalar returned instead of array |
| Curve (`y` or `x`) | `(N,)` matching x/y grid | 2D array returned |
| Parametric (`xyz`) | `(3, N)` or `(3, N, M)` | Wrong axis order; `(N, 3)` instead of `(3, N)` |
| Scatter (`points`) | `(N, 3)` | Wrong number of columns |

For `xyz`, both `(3, N, M)` and `(N, M, 3)` are common; Pringle should accept both by checking which axis has size 3.

Shape warnings are displayed as yellow inline banners on the cell. Shape errors that produce NaN or Inf are silently filtered at the renderer level (NaN vertices are skipped).
