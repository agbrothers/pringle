# Expression Evaluation: Design and Security

## How Desmos Handles Expressions

Desmos is structurally safe by design — their expression language is **not JavaScript**. It uses a custom math notation (LaTeX-adjacent) parsed by a hand-written parser into an AST. The AST node types are a closed set: arithmetic ops, built-in functions (`sin`, `log`, etc.), list operations, conditionals. There is no path from a Desmos expression to arbitrary code execution because the grammar simply doesn't include it. The AST is then walked to generate JavaScript that only ever calls Desmos's own math primitives.

## Security Model for Pringle

### The Strategy: Whitelisted Namespace + No Builtins

Rather than trying to sandbox arbitrary Python, Pringle restricts the execution namespace to explicitly imported numpy and scipy names. No builtins are exposed. This means:

- `import` statements fail — `__import__` is a builtin and is not in scope
- `open()`, `eval()`, `exec()` fail — not in namespace
- Only numpy/scipy callables are reachable

```python
from numpy import (
    sin, cos, tan, arcsin, arccos, arctan, arctan2,
    exp, log, log2, log10, sqrt, abs, sign, ceil, floor,
    pi, e, inf, nan,
    array, zeros, ones, full, eye, linspace, arange, meshgrid,
    where, clip, concatenate, stack, hstack, vstack,
    sum, prod, cumsum, min, max, argmin, argmax,
    dot, cross, outer, kron,
    real, imag, conj, angle,
    random,
)
from numpy.linalg import norm, inv, det, eig, svd, solve, lstsq
from scipy.special import gamma, erf, erfc, beta, factorial

EQUATION_NAMESPACE = {k: v for k, v in locals().items() if not k.startswith("_")}
```

### Remaining Exposure

The namespace restriction alone is not fully bulletproof. Without builtins, a user can still construct Python literals and access their class hierarchy:

```python
# This would still work even with no builtins:
x = (1, 2)
x.__class__.__bases__[0].__subclasses__()
```

The `.__class__` attribute chain traverses Python's object model independent of builtins. This is a known limitation of namespace-only sandboxing.

### Defense-in-Depth: AST Check

An AST pre-check closes most remaining vectors by blocking constructs that aren't needed for math expressions:

```python
import ast

BLOCKED_NODE_TYPES = {
    ast.Import, ast.ImportFrom,       # import statements
    ast.With,                          # with ... as ...:
    ast.Try,                           # try/except
    ast.Global, ast.Nonlocal,         # scope manipulation
    ast.Delete,                        # del x
    ast.ClassDef, ast.AsyncFunctionDef,
}

BLOCKED_ATTRIBUTE_TARGETS = {"__class__", "__bases__", "__subclasses__", "__globals__"}

class SafetyChecker(ast.NodeVisitor):
    def generic_visit(self, node):
        if type(node) in BLOCKED_NODE_TYPES:
            raise ValueError(f"Disallowed syntax: {type(node).__name__}")
        super().generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr in BLOCKED_ATTRIBUTE_TARGETS:
            raise ValueError(f"Disallowed attribute access: {node.attr}")
        self.generic_visit(node)
```

**Equation panel**: namespace restriction + AST check. This is a strong posture for a tool with a known/trusted user base.

**Data panel**: namespace restriction only (the data panel is intentionally more permissive — it's where the user writes setup code, samples from distributions, etc.). Document clearly that the data panel is not sandboxed.

### Comparison of Approaches

| Approach | Equation Panel | Data Panel | Notes |
|---|---|---|---|
| Namespace restriction + no builtins | ✓ Apply | ✓ Apply | Core layer for both panels |
| AST check (block dangerous syntax) | ✓ Apply | Optional | Closes class-traversal vector |
| Subprocess isolation | Overkill for v1 | Overkill for v1 | Only needed for fully public deployment |

### How `exec` vs `eval` Changes Under This Model

`eval()` accepts a single expression and returns its value. `exec()` runs a block of statements. For multi-line equation blocks, `exec()` is required.

The security posture is the same either way — both accept a globals dict and locals dict. The namespace restriction + AST check applies to both.

```python
def run_block(code_str, grid_vars, shared_namespace):
    # Parse and check
    tree = ast.parse(code_str, mode="exec")
    SafetyChecker().visit(tree)

    # Build execution namespace
    local_ns = {**EQUATION_NAMESPACE, **shared_namespace, **grid_vars}
    local_ns["__builtins__"] = {}

    # Execute
    exec(compile(tree, "<cell>", "exec"), local_ns)
    return local_ns  # caller inspects for magic variable names
```

The result namespace is then inspected for magic variable names (`z`, `y`, `x`, `xyz`, `points`, `vectors`) to determine what was produced. See `07-cell-types-and-blocks.md`.

## Expression Language Conventions

The expression language is Python math syntax. Conventions:

- **Spatial variables** (reserved): `x`, `y`, `z`, `u`, `v` — injected as numpy arrays (the evaluation grid)
- **Time** (reserved): `t` — the current animation time value; injected as a scalar
- **Slider parameters**: any other name defined in a slider cell — injected as scalars
- **Helper functions**: `f = lambda x, y: sin(x) * cos(y)` in any cell — available in the shared namespace
- **Data**: names from the data panel — available in the shared namespace
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
