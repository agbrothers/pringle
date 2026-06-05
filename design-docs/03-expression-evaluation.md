# Expression Evaluation: Design and Security

## How Desmos Handles Expressions

Desmos is structurally safe by design — their expression language is **not JavaScript**. It uses a custom math notation (LaTeX-adjacent) parsed by a hand-written parser into an AST. The AST node types are a closed set: arithmetic ops, built-in functions (`sin`, `log`, etc.), list operations, conditionals. There is no path from a Desmos expression to arbitrary code execution because the grammar simply doesn't include it. The AST is then walked to generate JavaScript that only ever calls Desmos's own math primitives.

## Security Model for Pringle

### Threat Model

Pringle runs locally on the user's machine. The primary threat is **not** users harming themselves — if someone writes arbitrary Python in their own session, that is their Python environment. The real threat is **malicious shared sessions**: a `.yml` file distributed via GitHub, a blog post, or a colleague that silently executes harmful code when loaded. Sessions are designed to be shared and are human-readable, which makes them a plausible social-engineering vector.

The security posture is calibrated for this: strong enough that a malicious shared session cannot escape to the filesystem or network, lightweight enough that it does not block legitimate scientific expressions.

### The Strategy: Whitelisted Namespace + No Builtins + AST Check

All cells (equation, data-mode, recurrence) use the same execution model: a whitelisted namespace of explicitly imported numpy/scipy names, no Python builtins, and an AST safety check before execution.

- `import` statements fail — blocked at AST check
- `open()`, `eval()`, `exec()` fail — both blocked by name in AST check and absent from namespace
- All dunder attribute access (`.__class__`, `.__builtins__`, etc.) blocked by AST check
- Only numpy/scipy callables are reachable

The whitelisted namespace is defined in `namespace.py` (`build_equation_namespace()`). Adding a new function requires an explicit line there — not just `import numpy as np`.

### Defense-in-Depth: AST Check

The AST pre-check in `safety.py` (`SafetyChecker`) enforces the following before any `exec()`:

- **Blocks `import` / `from-import`** — `visit_Import`, `visit_ImportFrom`
- **Blocks named calls** to `exec`, `eval`, `compile`, `open`, `breakpoint` — `visit_Call` on `ast.Name`
- **Blocks dunder calls** — any call to a name or attribute starting with `__` (e.g. `__import__()`)
- **Blocks all dunder attribute access** — any `obj.attr` where `attr` starts with `__`; this covers `.__class__`, `.__builtins__`, `.__subclasses__`, `.__globals__`, etc. on any object including module-level names like `random`

The dunder block is the key layer: even though module objects like `random = numpy.random` are in scope and technically have `.__builtins__`, the AST check prevents any expression from reaching them.

### Remaining Exposure

The class-traversal attack (`x.__class__.__bases__[0].__subclasses__()`) is caught by the dunder block. The remaining surface is narrow:

- `for` loops, list comprehensions, `with` statements, `try/except`, `class` definitions, and `def` are syntactically permitted but cannot escape the restricted namespace — they have no access to builtins or dunder attributes
- `int` (the Python builtin type) is explicitly in scope because it is needed for array indexing (`path[int(t)]`). It is a live Python type, but dunder attribute access on it is blocked, so the class hierarchy is not reachable
- A cell can delete names from `local_ns` via `del` — this is harmless since the namespace is rebuilt fresh before each execution

The practical risk from these is negligible for the shared-session threat model.

### How `exec` vs `eval` Changes Under This Model

`eval()` accepts a single expression and returns its value. `exec()` runs a block of statements. For multi-line cells, `exec()` is required.

The security posture is the same either way — both accept a globals dict. The namespace restriction + AST check applies to both.

```python
def run_cell(source, shared_namespace, grid):
    # Parse and check
    tree = check_ast(source)  # raises SecurityError or SyntaxError

    # Build execution namespace
    local_ns = build_equation_namespace()
    local_ns.update(shared_namespace)
    local_ns.update(grid_vars(grid))

    # Execute
    exec(compile(tree, "<cell>", "exec"), local_ns)
    return local_ns  # caller inspects for magic variable names
```

The result namespace is then inspected for magic variable names (`z`, `y`, `x`, `xyz`, `points`, `vectors`) to determine what was produced. See `07-cell-types-and-blocks.md`.

## Expression Language Conventions

The expression language is Python math syntax. Conventions:

- **Spatial variables** (reserved): `x`, `y`, `u`, `v` — injected as numpy arrays (the evaluation grid); `z` is a magic output name, not an input
- **Slider parameters**: any name defined in a slider cell (e.g. `time = 0`) — injected as scalars; whole-number floats are automatically promoted to Python `int` so they can be used directly as array indices (`path[:time]`)
- **`t` is not a built-in**: unlike Desmos, Pringle has no implicit animation-time variable. For a frame counter, create a slider (e.g. `time = 0` with step 1). Use `int(round(t))` rather than `int(t)` when coercing a non-integer slider to an index to avoid floating-point off-by-one errors.
- **Integer casting for array indices**: Use `int_(expr)` to cast a float scalar or array to integer type for use as an array index. For scalars, `int(expr)` also works (Python builtin, already in namespace). Prefer `int_(round(expr))` over `int_(floor(expr))` to avoid floating-point off-by-one errors at whole numbers. The `intp` type is equivalent but sized for indexing on the current platform — either is acceptable. This fills the gap between slider auto-promotion (which converts whole-number slider floats to Python `int` automatically) and equation-cell outputs, which remain numpy floats and cannot be used as array indices without explicit casting.
- **Helper functions**: `f = lambda x, y: sin(x) * cos(y)` in any cell — available in the shared namespace
- **`def` vs `lambda` — evaluation timing control knob**: cells whose stripped source begins with `def ` are evaluated on **focus-out only** (deferred mode); `lambda` cells stay on the standard 300 ms debounce (eager mode). This is an intentional UX asymmetry: `lambda` gives live visual feedback for simple fast expressions; `def` avoids triggering an expensive downstream re-evaluation chain on every keystroke while editing a multi-line function body. Users choose the behavior by choosing the syntax. See `07-cell-types-and-blocks.md`.
- **Math builtins**: `sin`, `cos`, `pi`, etc. from the whitelisted namespace — no prefix needed
- **No `numpy.` prefix required**: functions are imported directly into the namespace
- **Power**: `**` (not `^`)
- **Conditional**: Python ternary `a if condition else b`, or `where(condition, a, b)`

## Dependency Analysis and Undefined Variable Detection

To support order-independent evaluation and the "suggest undefined variable" feature, Pringle statically analyzes each cell's free variables at parse time:

```python
def get_free_names(code_str):
    tree = ast.parse(code_str, mode="exec")
    assigned = set()
    referenced = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                assigned.add(node.id)
            elif isinstance(node.ctx, ast.Load):
                referenced.add(node.id)
    # Free variables: referenced but not assigned within this block
    free = referenced - assigned - set(EQUATION_NAMESPACE) - SPATIAL_VARS
    return free
```

Names in `free` that are not defined in any other cell are flagged as undefined, triggering the "suggest slider" behavior in the UI.

`safety.get_param_names(source)` is a companion function that returns only the parameter names declared by `def`/lambda signatures in the source (using the same AST walk). Returns an empty set for syntactically-incomplete source. Used by `PringleHighlighter` to color function arguments throughout a cell (FEAT-147).

## Parsing Workflow

```
User edits cell content
        ↓
Parse to AST (ast.parse)
        ↓
AST safety check (block dangerous nodes)
        ↓
Extract free variable names → check against global namespace
        ↓ (if undefined names found)
Show "undefined variable" warning + "add slider" suggestion button
        ↓ (when slider values or t change)
exec() block in restricted namespace (grid vars + shared namespace injected)
        ↓
Inspect result namespace for magic variable names
        ↓
Apply constraints (boolean arrays → np.where mask)
        ↓
Upload result as surface / curve / scatter mesh
```

The compile step (AST parse + safety check) is cached and only re-runs when the cell content changes. The exec step re-runs on every slider tick or animation frame, for cells that depend on changed parameters.
