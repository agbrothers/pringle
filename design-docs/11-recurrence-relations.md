# Recurrence Relations

## Design

Recurrence relations in Pringle are a specialized data cell type — not a function or equation construct. They live in the data panel and produce a precomputed array that the equation panel can reference and index.

This sidesteps the problems with general programming recursion (stack limits, non-vectorizable, circular dependency detection) by treating recurrences explicitly as what they are: **iterative rules for building arrays from prior values**.

## Cell Structure

A recurrence data cell has:
1. **Primary expression**: allocates the output array — e.g., `path = zeros((10, 2))`
2. **`initial_condition:` sub-cell**: an expression that evaluates to the value of `array[0]`
3. **`recursion:` sub-cell**: a statement of the form `array[n] = expr(array[n-1], ...)` defining the update rule

```
[Data cell]  path = zeros((10, 2))
  [initial_condition]  array([1.0, 0.1])
  [recursion]          path[n] = 2 * path[n-1]
```

In the YAML session format:
```yaml
- id: "data-002"
  type: recurrence
  expression: "path = zeros((10, 2))"
  initial_condition: "array([1.0, 0.1])"
  recursion: "path[n] = 2 * path[n-1]"
```

## Execution Model

The recurrence cell is executed when the user clicks ▶ Run (same as any data cell). The execution sequence:

```python
# Step 1: execute the primary expression to allocate the array
exec(primary_code, data_namespace)
# → path = zeros((10, 2)) is now in data_namespace

# Step 2: evaluate the initial condition and set index 0
init_val = eval(initial_condition_expr, data_namespace)
array_name = extract_array_name(recursion_rule)   # "path"
data_namespace[array_name][0] = init_val

# Step 3: run the recursion rule as a generated for loop
array_name, index_var, rule_stmt = parse_recursion_rule(recursion_rule)
loop_code = f"for {index_var} in range(1, len({array_name})):\n    {rule_stmt}"
exec(loop_code, data_namespace)

# Result: data_namespace["path"] is now a fully populated (10, 2) array
```

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
