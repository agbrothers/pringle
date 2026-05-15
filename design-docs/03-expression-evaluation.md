# Expression Evaluation: Design and Security

## How Desmos Handles Expressions

Desmos is structurally safe by design — their expression language is **not JavaScript**. It uses a custom math notation (LaTeX-adjacent) parsed by a hand-written parser into an AST. The AST node types are a closed set: arithmetic ops, built-in functions (`sin`, `log`, etc.), list operations, conditionals. There is no path from a Desmos expression to arbitrary code execution because the grammar simply doesn't include it. The AST is then walked to generate JavaScript that only ever calls Desmos's own math primitives.

## The Python `eval()` Problem

Raw `eval()` cannot be safely sandboxed in Python. Even with `{"__builtins__": {}}`:

```python
eval("().__class__.__bases__[0].__subclasses__()")  # traverses the entire class hierarchy
```

Python's object model leaks through in many ways. There is no reliable way to make raw `eval()` safe against a determined attacker.

## Options for Safe Expression Evaluation

### 1. AST Whitelist (recommended for public deployment)

Parse the expression string with Python's `ast` module, walk the AST with a custom `NodeVisitor` that raises on any disallowed node type, then compile and eval the sanitized AST.

```python
import ast
import numpy as np

ALLOWED_NODES = {
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name,
    ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
    ast.USub, ast.UAdd, ast.IfExp, ast.Compare, ast.BoolOp,
    ast.And, ast.Or, ast.Lt, ast.Gt, ast.LtE, ast.GtE, ast.Eq,
}

SAFE_NAMES = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan,
    "exp": np.exp, "log": np.log, "sqrt": np.sqrt,
    "abs": np.abs, "pi": np.pi, "e": np.e,
    # ... extend as needed
}

class SafeVisitor(ast.NodeVisitor):
    def visit(self, node):
        if type(node) not in ALLOWED_NODES:
            raise ValueError(f"Disallowed expression node: {type(node).__name__}")
        self.generic_visit(node)

def make_surface_fn(expr_str):
    tree = ast.parse(expr_str, mode="eval")
    SafeVisitor().visit(tree)
    code = compile(tree, "<expr>", "eval")
    def fn(x, y, **params):
        return eval(code, {"__builtins__": {}}, {**SAFE_NAMES, "x": x, "y": y, **params})
    return fn
```

This is roughly 100–150 lines for a solid implementation. Suitable for public deployment.

### 2. SymPy `lambdify` (symbolic + safe, with extra benefits)

Parse with SymPy's expression parser (which is already restricted to math), then `lambdify` to a numpy-vectorized function.

```python
from sympy import sympify, lambdify, symbols

x, y = symbols("x y")
expr = sympify("sin(x) * cos(y)")
fn = lambdify([x, y], expr, modules="numpy")
# fn is now a fast numpy-vectorized function
```

Benefits:
- Free symbolic differentiation (gradients, Jacobians, curvature) — very useful for vector fields
- SymPy's parser is already a whitelist of math operations
- `lambdify` output is fast numpy code

Limitations:
- SymPy syntax differs from Python in subtle ways (e.g., `x**2` works, `x^2` does not)
- SymPy parse is slower than a raw AST check (matters for real-time keystroke parsing)
- Named user parameters need to be pre-declared as `symbols`

### 3. `numexpr` (fast, limited)

Evaluates expressions like `"sin(x) * cos(y)"` using its own JIT compiler. Safe (whitelist of ops), fast (SIMD vectorization), simple.

```python
import numexpr as ne
import numpy as np

x, y = np.meshgrid(np.linspace(-3, 3, 256), np.linspace(-3, 3, 256))
z = ne.evaluate("sin(x) * cos(y)")
```

Limitations: no function definitions, no conditionals, no user-defined parameters beyond numpy arrays.

### 4. `asteval`

A library that wraps the AST approach into a ready-made restricted evaluator. Gives a Python-like expression language with a user-defined symbol table.

```python
from asteval import Interpreter
aeval = Interpreter()
aeval.symtable.update({"x": x_grid, "y": y_grid})
z = aeval("sin(x) * cos(y)")
```

Reasonably safe, easy to use, not as flexible as a custom AST whitelist.

### 5. Raw `eval()` with restricted namespace

Fine for personal use. Not suitable for public deployment.

## Recommendation

| Use case | Approach |
|---|---|
| Personal / local tool | Raw `eval()` with a math-only namespace |
| Public tool, v1 | `asteval` or AST whitelist |
| Public tool, with vector field / gradient features | SymPy `lambdify` |
| Maximum eval performance on large grids | `numexpr` (or combine: SymPy parse → numexpr backend) |

**For Pringle**: start with raw `eval()` using a restricted namespace during prototyping. Switch to the AST whitelist approach before any public deployment. SymPy integration is worth considering if gradient/curl/divergence features are desired.

## Expression Language Design

The expression language should feel like Python math syntax, with these conventions:

- Variables `x`, `y`, `z`, `u`, `v` are reserved spatial coordinates
- `t` is reserved for the animation time parameter
- Named parameters (sliders) are any other single-letter or short names: `a`, `b`, `n`, etc.
- Built-in functions: `sin`, `cos`, `tan`, `exp`, `log`, `log10`, `sqrt`, `abs`, `ceil`, `floor`, `sign`
- Constants: `pi`, `e`, `inf`
- Conditional: Python ternary syntax `expr_if_true if condition else expr_if_false`
- Operators: `**` for power (not `^`), standard arithmetic

### Parsing Workflow

```
User types expression string
        ↓
Parse to AST (ast.parse or sympy.sympify)
        ↓
Validate AST against whitelist
        ↓
Compile to numpy-vectorized function
        ↓
Evaluate over (x, y) grid with current parameter values
        ↓
Upload result as surface mesh
```

The compile step should be cached — only re-run when the expression string changes, not on every slider tick.
