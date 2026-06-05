# Expression Evaluation: Design and Execution Model

## How Desmos Handles Expressions

Desmos is structurally safe by design — their expression language is **not JavaScript**. It uses a custom math notation (LaTeX-adjacent) parsed by a hand-written parser into an AST. The AST node types are a closed set: arithmetic ops, built-in functions (`sin`, `log`, etc.), list operations, conditionals. There is no path from a Desmos expression to arbitrary code execution because the grammar simply doesn't include it.

## Pringle's Execution Model

Pringle executes cell source with Python's `exec()` in a shared namespace. There is no sandbox — cells can import modules, call any function, and do anything valid Python can do.

### Trust Model: Play Button on Load

Safety is provided by the **session trust model** rather than a sandbox:

- Sessions loaded from a `.yml` file start in **unexecuted state**: cells are displayed but nothing evaluates, the 3D viewport shows empty axes.
- A **play button** is shown centered in the viewport with the copy: *"Trust and verify this code before running it."*
- Clicking the play button sets `_session_trusted = True` on the `CellListWidget`, calls `_rebuild_namespace()`, then hides the overlay.
- The approval is **per-session only** (in-memory); there is no persistent per-file trust database.
- **New sessions** (Ctrl+N, default startup) and cells the user writes interactively start as trusted — no play button is shown.

This is the same model used by Jupyter notebooks and VS Code.

### Namespace

All cells share a single cumulative namespace built by `build_equation_namespace()` in `namespace.py`. The namespace is populated with:

- `np = numpy` — the full numpy module, for `np.sin`, `np.array`, etc.
- `math` — the stdlib math module
- Individual numpy/scipy convenience names (`sin`, `cos`, `pi`, `gamma`, etc.) — for backward compatibility with existing `.yml` files
- Standard Python builtins — available normally (no `__builtins__` restriction)

The complete list is in `14-namespace-reference.md`.

### `exec` vs `eval`

`eval()` accepts a single expression and returns its value. `exec()` runs a block of statements. For multi-line cells, `exec()` is required.

```python
def run_cell(source, shared_namespace, grid):
    # Build execution namespace
    local_ns = build_equation_namespace()
    local_ns.update(shared_namespace)
    local_ns.update(grid_vars(grid))

    # Execute
    exec(source, local_ns)
    return local_ns  # caller inspects for magic variable names
```

The result namespace is then inspected for magic variable names (`z`, `y`, `x`, `xyz`, `points`, `vectors`) to determine what was produced. See `07-cell-types-and-blocks.md`.

## Expression Language Conventions

The expression language is Python math syntax. Conventions:

- **Spatial variables** (reserved): `x`, `y`, `u`, `v` — injected as numpy arrays (the evaluation grid); `z` is a magic output name, not an input
- **Slider parameters**: any name defined in a slider cell (e.g. `time = 0`) — injected as scalars; whole-number floats are automatically promoted to Python `int` so they can be used directly as array indices (`path[:time]`)
- **`t` is not a built-in**: unlike Desmos, Pringle has no implicit animation-time variable. For a frame counter, create a slider (e.g. `time = 0` with step 1). Use `int(round(t))` rather than `int(t)` when coercing a non-integer slider to an index to avoid floating-point off-by-one errors.
- **Integer casting for array indices**: Use `int_(expr)` to cast a float scalar or array to integer type for use as an array index. For scalars, `int(expr)` also works. Prefer `int_(round(expr))` over `int_(floor(expr))` to avoid floating-point off-by-one errors at whole numbers.
- **Helper functions**: `f = lambda x, y: sin(x) * cos(y)` in any cell — available in the shared namespace
- **`def` vs `lambda` — evaluation timing**: cells whose stripped source begins with `def ` are evaluated on **focus-out only** (deferred mode); `lambda` cells stay on the standard 300 ms debounce (eager mode). Users choose the behavior by choosing the syntax.
- **Math builtins**: `sin`, `cos`, `pi`, etc. available without a prefix (`np.sin` also works)
- **No `numpy.` prefix required** for convenience names: functions are imported directly into the namespace
- **Power**: `**` (not `^`)
- **Conditional**: Python ternary `a if condition else b`, or `where(condition, a, b)`
- **Imports**: `import scipy.optimize; result = scipy.optimize.minimize(...)` works — sessions execute with full Python access after trust approval

## Dependency Analysis and Undefined Variable Detection

To support order-independent evaluation and the "suggest undefined variable" feature, Pringle statically analyzes each cell's free variables at parse time using two functions in `ast_utils.py`:

- **`get_free_names(source)`** — names referenced but not defined within this cell (its upstream dependencies).
- **`get_store_names(source)`** — names this cell writes into the shared namespace (its downstream-visible exports).

Both functions handle assignments, function definitions, lambda parameters, for-loop targets, and **import statements**. `import scipy as sc` is recognized as storing `sc`; `from scipy import norm, erf` stores `norm` and `erf`. This ensures the DAG correctly tracks cross-cell dependencies even when cells use imports.

Names returned by `get_free_names` that are not defined in any other cell's `get_store_names` are flagged as undefined, triggering the "suggest slider" behavior in the UI.

`ast_utils.get_param_names(source)` returns only parameter names declared by `def`/lambda signatures. Used by `PringleHighlighter` to color function arguments throughout a cell (FEAT-147).

## Parsing Workflow

```
User edits cell content
        ↓
Parse to AST (ast.parse)
        ↓
Extract free variable names → check against global namespace
        ↓ (if undefined names found)
Show "undefined variable" warning + "add slider" suggestion button
        ↓ (when slider values or t change, and _session_trusted is True)
exec() block in namespace (grid vars + shared namespace injected)
        ↓
Inspect result namespace for magic variable names
        ↓
Apply constraints (boolean arrays → np.where mask)
        ↓
Upload result as surface / curve / scatter mesh
```

AST analysis (free-name extraction) runs each time cell content changes. The `exec` step runs only when `_session_trusted` is `True`.
