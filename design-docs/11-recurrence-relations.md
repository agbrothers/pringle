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

Recurrence cells are **reactive**: they re-evaluate automatically whenever an upstream slider changes, identical to any other equation cell. The `execute_recurrence` function in `recurrence.py` runs inside `_eval_spec` on the background eval thread (PERF-015).

The execution sequence in `execute_recurrence`:

```python
# Step 1: primary expression already evaluated by run_cell — array is in result.exports.
#         execute_recurrence receives (array_name, array, initial_condition_exprs, rhs, namespace).

# Step 2: apply initial conditions
for ic_expr in initial_condition_exprs:
    exec(ic_expr, {**namespace, array_name: array})

# Step 3: compile RHS once (PERF-013)
code = compile(rhs, "<recurrence>", "eval")
glob = {**namespace, "__builtins__": {}, array_name: array}

# Step 4: run the loop; array is mutated in-place
with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
    for n in range(loop_start, array.shape[0]):
        val = eval(code, glob, {"n": n})
        array[n] = val

# Step 5: single post-loop NaN check
nan_found = not np.all(np.isfinite(array[loop_start:]))
```

**Compile-once (PERF-013):** The RHS string is compiled to a code object once before the loop via `compile(rhs, "<recurrence>", "eval")`. The code object is passed to `eval` each step instead of re-compiling the string. This reduced per-step eval cost from 56.9 µs to ~16.3 µs (3.5×) and total recurrence time from ~14 ms to ~3.35 ms for a 200-step path.

**Post-loop NaN check:** `np.all(np.isfinite(array[loop_start:]))` runs once after the loop instead of per-step. If NaN/Inf are detected, a warning is attached to the cell result.

## Shared Namespace Access in Recursion Rules

The recursion loop executes in the shared data namespace, which includes:
- All previously run data cell outputs
- All equation panel lambda/helper functions (from the shared namespace)
- Slider values

This means recursion rules can call equation panel functions and reference slider values:
```python
# Equation panel cell:
f(x,y) = x**2 + y**2   # → f = lambda x, y: x**2 + y**2 in shared namespace

# Recurrence cell — references slider η and lambda dE from shared namespace:
path_xy = zeros((200, 2))
# initial_condition: path_xy[0] = array([0.5, 0.5])
# recursion: path_xy[n] = path_xy[n-1] - η * dE(path_xy[n-1])
```

Upstream cells must appear earlier in the DAG. The recurrence re-evaluates reactively on every slider animation tick, so `η` above animates live.

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

After the recurrence cell evaluates, the array is in the shared namespace and can be referenced by any downstream equation cell:

```python
# Visualize the entire trajectory as a scatter/line
points = path               # bare auto-plot as scatter (N,2) or (N,3)

# Animate a point along a pre-computed path using a slider i
particle = path[int(clip(i, 0, len(path) - 1))]
```

Because the recurrence re-evaluates reactively on slider changes, you can use a slider directly in the recursion rule instead of indexing the output array:

## Performance Notes

With the compile-once optimization (PERF-013), typical timings at n=128:

| Array size | Steps | Loop time (measured) |
|---|---|---|
| (200, 2) | 200 | ~3.35 ms |
| (1000, 3) | 1000 | ~16 ms (est.) |
| (10000, 3) | 10000 | ~165 ms (est.) |

Per-step cost is ~16 µs with `eval(code_object, ...)`. For larger step counts, Numba JIT on the loop body is the correct path to near-C speed (PERF-012, deferred to v2).

Recurrences re-evaluate on every slider animation tick. At 200 steps this is 3.35 ms per frame running on the background eval thread, leaving the main thread free for camera interaction.

## Limitations

- The `recursion:` rule must be a single assignment statement `array[n] = expr`
- The index variable must index the first axis: `path[n]`, not `path[:, n]`
- Multi-step recurrences (depending on `n-2`, `n-3`, etc.) work as long as `n` starts from the appropriate offset
  - For `path[n] = path[n-1] + path[n-2]`: set both `path[0]` and `path[1]` in initial conditions; loop starts at `n=2` automatically
