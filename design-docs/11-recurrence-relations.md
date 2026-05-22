# Recurrence Relations

## Design

Recurrence relations in Pringle are expressed inside equation cells using `initial_condition` and `recursion` sub-cells. They produce a precomputed array that other equation cells can reference and index.

This sidesteps the problems with general programming recursion (stack limits, non-vectorizable, circular dependency detection) by treating recurrences explicitly as what they are: **iterative rules for building arrays from prior values**.

## Cell Structure

A recurrence equation cell has:
1. **Primary expression**: allocates the output array — e.g., `path = zeros((10, 2))`
2. **One or more `initial_condition:` sub-cells**: each is a statement `array[index] = expr` that explicitly sets a specific index
3. **`recursion:` sub-cell**: a statement of the form `array[n] = expr(array[n-1], ...)` defining the update rule

```
[Equation cell]  path = zeros((10, 2))
  [initial_condition]  path[0] = array([1.0, 0.1])
  [initial_condition]  path[1] = array([2.0, 0.2])   ← optional; for multi-step recurrences
  [recursion]          path[n] = 2 * path[n-1]
```

Multiple initial conditions allow multi-step recurrences (Fibonacci-style: `path[n] = path[n-1] + path[n-2]` requires both `path[0]` and `path[1]` to be set).

In the YAML session format:
```yaml
- id: "cell-002"
  type: equation
  source: "path = zeros((10, 2))"
  sub_cells:
    - type: initial_condition
      source: "path[0] = array([1.0, 0.1])"
    - type: initial_condition
      source: "path[1] = array([2.0, 0.2])"
    - type: recursion
      source: "path[n] = 2 * path[n-1]"
```

## Execution Model

The recurrence cell is executed when the user clicks ▶ Run. The execution sequence:

```python
# Step 1: allocate the array filled with NaN (not zeros) for error detection
exec(primary_code, data_namespace)
# Immediately overwrite with NaN so unset indices are detectable:
array_name = extract_array_name(recursion_rule)
data_namespace[array_name][:] = nan

# Step 2: apply all initial conditions (explicit index assignments)
for ic_expr in initial_condition_exprs:
    exec(ic_expr, data_namespace)   # e.g., exec("path[0] = array([1.0, 0.1])", ...)

# Step 3: determine loop start from the highest set initial condition index + 1
# (parsed from the initial condition LHS subscripts)
loop_start = max_initial_index + 1

# Step 4: run the recursion rule as a generated for loop
array_name, index_var, rule_stmt = parse_recursion_rule(recursion_rule)
loop_code = (
    f"for {index_var} in range({loop_start}, len({array_name})):\n"
    f"    if any(isnan({array_name}[{index_var}-1])):\n"
    f"        break\n"
    f"    {rule_stmt}"
)
exec(loop_code, data_namespace)
```

**NaN-fill error detection:** the array is pre-filled with NaN before initial conditions are applied. If the recursion rule ever reads a NaN value (because a required prior index was not set), the loop detects this, stops, and reports a warning: `"Recurrence halted at index N: prior value was NaN — check initial conditions."` This catches missing initial conditions (e.g., setting only `path[0]` for a two-step recurrence that reads `path[n-2]`).

The `isnan` check is applied to the prior element before each iteration. For scalar arrays, it's `isnan(array[n-1])`; for vector arrays, `any(isnan(array[n-1]))`. The `isnan` function is in the numpy whitelist namespace.

## Shared Namespace Access in Recursion Rules

The recursion loop executes in the shared data namespace, which includes:
- All previously run data cell outputs
- All equation panel lambda/helper functions (from the shared namespace)
- Slider values

This means recursion rules can call equation panel functions:
```python
# Equation panel cell:
f(x,y) = x**2 + y**2   # → f = lambda x, y: x**2 + y**2 in shared namespace

# Data recurrence cell:
path = zeros((50, 2))
# initial_condition: path[0] = array([1.0, 0.5])
# recursion: path[n] = path[n-1] + 0.01 * custom_step(path[n-1])
```

Functions must be defined (equation panel cells evaluated, or prior data cells run) before the recurrence cell is run. The ▶ Run button triggers evaluation at that moment in time.

## Loop Index Variable: `n` → `_pringle_loop_n`

The user writes `n` as the loop index in the recursion sub-cell for readability. Internally, the parser renames all occurrences of `n` to `_pringle_loop_n` using an AST name-substitution pass before the loop is executed. This prevents any collision with a slider or data variable also named `n`.

```python
class RenameLoopVar(ast.NodeTransformer):
    def __init__(self, old, new): self.old, self.new = old, new
    def visit_Name(self, node):
        if node.id == self.old:
            return ast.copy_location(ast.Name(id=self.new, ctx=node.ctx), node)
        return node

def rename_index_var(tree, user_name="_pringle_loop_n"):
    # Detect the index variable from the LHS subscript
    assign = tree.body[0]
    index_var = assign.targets[0].slice.id   # e.g., "n"
    renamed = RenameLoopVar(index_var, user_name).visit(tree)
    return renamed, index_var, user_name
```

The user-visible name (`n`) is only used in the sub-cell text editor. The loop variable `_pringle_loop_n` is transient and scoped to the loop — it is not present in the shared namespace before or after execution.

## Parsing the Recursion Rule

The recursion rule `path[n] = 2 * path[n-1]` is valid Python syntax — an assignment where the LHS is a subscript. It is parsed with `ast.parse` to extract components:

```python
def parse_recursion_rule(rule_str: str):
    tree = ast.parse(rule_str, mode="exec")
    assign = tree.body[0]  # ast.Assign

    # LHS: path[n]
    target = assign.targets[0]  # ast.Subscript
    array_name = target.value.id          # "path"
    index_var = target.slice.id           # "n"

    # RHS: the full rule statement as written (used as loop body)
    return array_name, index_var, rule_str
```

The generated loop body is the original rule string verbatim — no transformation needed. The index variable `n` is the loop counter.

## Multi-dimensional Recurrences

The model handles multi-dimensional arrays naturally because `path[n]` for a 2D array returns a row slice, and assignment to a row slice is standard numpy:

```python
# path = zeros((10, 2))  → path[n] is shape (2,)
# path[n] = 2 * path[n-1]  works for any row-compatible RHS
```

More complex rules work as long as the RHS has the right shape:
```python
# Matrix recurrence: A @ path[n-1]
# path[n] = A @ path[n-1]
# where A is a (2,2) matrix defined elsewhere in the data namespace
```

## Examples

### Geometric growth (scalar)
```python
values = zeros(20)
# initial_condition: 1.0
# recursion: values[n] = 2 * values[n-1]
```

### 2D particle path
```python
path = zeros((50, 2))
# initial_condition: array([1.0, 0.0])
# recursion: path[n] = path[n-1] @ rotation_matrix(0.1)
```

### Lorenz attractor (discrete approximation)
```python
lorenz = zeros((1000, 3))
# initial_condition: array([1.0, 1.0, 1.0])
# recursion: lorenz[n] = lorenz[n-1] + dt * lorenz_deriv(lorenz[n-1], sigma, rho, beta)
# where lorenz_deriv is a lambda defined elsewhere in the data namespace
```

## Using the Result in the Equation Panel

After the recurrence cell is run, the array is in the shared namespace and can be referenced by any equation cell:

```python
# Equation panel — animate a point along the path
particle = points[int(t)]   # t is the animation slider; points is the recurrence result

# Or visualize the entire trajectory
points = path               # bare auto-plot as scatter (N,2) or (N,3)
```

Indexing with `int(t)` handles the float→int conversion when `t` is the continuous animation slider. A `round()` or `clip()` wrapper prevents out-of-bounds:
```python
idx = int(clip(round(t), 0, len(path) - 1))
particle = path[idx]
```

## Performance Notes

For recurrences with a few hundred to a few thousand steps, the Python for loop is fast enough — each iteration is a numpy array operation (vectorized over the array dimensions). Typical timings at interactive resolution:

| Array size | Steps | Loop time (approx) |
|---|---|---|
| (100, 2) | 100 | < 1ms |
| (1000, 3) | 1000 | ~5ms |
| (10000, 3) | 10000 | ~50ms |

For large recurrences, a Numba JIT-compiled loop (`@numba.jit`) can provide 10-100x speedup. This is a straightforward optimization if needed — the code structure is the same; just annotate the loop function. Deferred to v2.

**Note:** recurrences are evaluated once (on ▶ Run), not per animation frame. The result is a static precomputed array. Animating over it uses the slider-indexing pattern (`path[int(t)]`), not re-evaluation of the loop.

## Limitations

- The `recursion:` rule must be a single assignment statement `array[n] = expr`
- The index variable must index the first axis: `path[n]`, not `path[:, n]`
- Multi-step recurrences (depending on `n-2`, `n-3`, etc.) work as long as `n` starts from the appropriate offset
  - For `path[n] = path[n-1] + path[n-2]`: change the loop to `range(2, len(path))` and set both `path[0]` and `path[1]` in the initial condition
  - Multi-step initial conditions are a v2 UI feature; for now, set them manually in the primary expression
- The recurrence rule cannot reference slider values or `t` — it runs once at ▶ Run time, not reactively. To make a recurrence parameter-dependent, re-run the data cell when the parameter changes (manual trigger).
