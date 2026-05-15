# Expression Processing Pipeline

This document describes the full pipeline from raw cell content to rendered output. It covers preprocessing (syntax sugar → valid Python), AST analysis, execution, output detection, constraint application, and shape validation.

## Overview

```
Raw cell string (from UI)
    │
    ▼
[1] PREPROCESS
    • Detect and convert f(args) = expr → lambda assignments
    • Extract constraint sub-cell expressions (from UI, not parsed text)
    │
    ▼
[2] PARSE & VALIDATE
    • ast.parse() → AST
    • AST safety check (block dangerous node types)
    • Free variable extraction → dependency edges
    │
    ▼ (on slider/t change, or explicit run)
[3] EXECUTE
    • exec() in restricted namespace (numpy/scipy + shared ns + grid vars)
    • Capture bare expression values via AST transform
    │
    ▼
[4] OUTPUT DETECTION
    • Check namespace for magic variable names (z, y, xyz, points, ...)
    • Fall back to bare expression auto-plot (shape-based inference)
    │
    ▼
[5] CONSTRAINT APPLICATION
    • Evaluate constraint expressions in same namespace (z now available)
    • Combine masks with logical_and
    • Apply: np.where(mask, value, nan)
    │
    ▼
[6] SHAPE VALIDATION
    • Check output shape against expected shape for render type
    • On mismatch: emit inline cell warning; skip renderer
    │
    ▼
[7] RENDERER SUBMISSION
    • Upload / update geometry buffer
    • Apply CellStyle (color, opacity, display mode, etc.)
```

---

## Stage 1: Preprocessing

Preprocessing transforms syntax sugar into valid Python before `ast.parse()` sees it. It operates line-by-line on the primary expression cell content. Constraint expressions come from their own sub-cell UI inputs and are never mixed into the primary cell text.

### 1a. Function Definition Detection

Detects the pattern `name(args) = expr` — never valid Python — and converts it to a lambda assignment.

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

Examples:
```
f(x,y) = x**2 + y**2      →   f = lambda x, y: x**2 + y**2
g(x,y) = -x**2 - y**2     →   g = lambda x, y: -x**2 - y**2
h(t) = sin(t) * cos(t)    →   h = lambda t: sin(t) * cos(t)
```

This transformation is applied to every line of the primary cell content before AST parsing.

### 1b. Constraint Extraction

Constraint expressions come from the UI — each constraint sub-cell is a separate input box. The pipeline receives them as a list of strings, not extracted from the primary cell text. No text parsing is needed.

```python
# From UI layer:
primary_code: str       # the main expression cell content
constraints: list[str]  # one string per constraint sub-cell
```

### 1c. Full Preprocessing Function

```python
def preprocess_cell(primary_code: str) -> str:
    lines = primary_code.splitlines()
    return "\n".join(preprocess_func_def(line) for line in lines)
```

Constraint sub-cells are preprocessed identically (each is a single expression, but function definition detection is still applied in case a constraint calls `f(args)`).

---

## Stage 2: Parse and Validate

```python
import ast

BLOCKED_NODES = {
    ast.Import, ast.ImportFrom,
    ast.With, ast.AsyncWith,
    ast.Try,
    ast.Global, ast.Nonlocal,
    ast.Delete,
    ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
}

BLOCKED_ATTRS = {"__class__", "__bases__", "__subclasses__", "__globals__",
                 "__builtins__", "__dict__", "__module__"}

class SafetyChecker(ast.NodeVisitor):
    def generic_visit(self, node):
        if type(node) in BLOCKED_NODES:
            raise ValueError(f"Disallowed syntax: {type(node).__name__}")
        super().generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr in BLOCKED_ATTRS:
            raise ValueError(f"Disallowed attribute: {node.attr}")
        self.generic_visit(node)

def parse_and_validate(code: str) -> ast.AST:
    tree = ast.parse(code, mode="exec")
    SafetyChecker().visit(tree)
    return tree
```

### Free Variable Extraction (Dependency Analysis)

```python
RESERVED = {"x", "y", "z", "u", "v", "t"}  # spatial + time vars
BUILTINS_NS = set(EQUATION_NAMESPACE.keys())  # sin, cos, pi, ...

def get_free_names(tree: ast.AST) -> set[str]:
    assigned, referenced = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                assigned.add(node.id)
            elif isinstance(node.ctx, ast.Load):
                referenced.add(node.id)
    return referenced - assigned - RESERVED - BUILTINS_NS
```

Free names are compared against all other cells' defined names to build the dependency DAG. Any free name not defined anywhere triggers the "undefined variable" inline warning and "add slider" suggestion.

---

## Stage 3: Execute

### Bare Expression Capture via AST Transform

Bare expression statements (`ast.Expr` nodes) are wrapped in auto-named assignments so their values are captured after execution:

```python
class CaptureExprs(ast.NodeTransformer):
    def __init__(self):
        self._count = 0

    def visit_Expr(self, node):
        name = f"_expr_{self._count}"
        self._count += 1
        assign = ast.Assign(
            targets=[ast.Name(id=name, ctx=ast.Store())],
            value=node.value,
            lineno=node.lineno, col_offset=node.col_offset,
        )
        return ast.fix_missing_locations(assign)
```

After this transform, bare `d` becomes `_expr_0 = d` in the executed code, and the result can be inspected from the local namespace.

### Execution

```python
import numpy as np

def execute_cell(code: str, shared_ns: dict, grid_vars: dict) -> dict:
    tree = parse_and_validate(preprocess_cell(code))
    tree = CaptureExprs().visit(tree)
    ast.fix_missing_locations(tree)

    local_ns = {
        **EQUATION_NAMESPACE,   # numpy/scipy whitelist
        **shared_ns,            # sliders, lambdas, data panel outputs
        **grid_vars,            # x, y, u, v as meshgrid arrays; t as scalar
        "__builtins__": {},
    }

    exec(compile(tree, "<cell>", "exec"), local_ns)
    return local_ns
```

---

## Stage 4: Output Detection

```python
MAGIC_NAMES = ["z", "y", "x", "xyz", "points", "vectors"]
SCATTER_SHAPES = {2, 3}  # valid column counts for auto-scatter

def detect_output(local_ns: dict, code: str):
    # 1. Check for magic name assignment (first magic name found in source order)
    for line in code.splitlines():
        line = line.strip()
        for name in MAGIC_NAMES:
            if line.startswith(f"{name} =") and name in local_ns:
                return name, local_ns[name]

    # 2. Fall back to bare expression auto-plot
    for key in sorted(k for k in local_ns if k.startswith("_expr_")):
        val = local_ns[key]
        if isinstance(val, np.ndarray) and val.ndim == 2:
            if val.shape[1] in SCATTER_SHAPES:
                return "points", val

    return None, None
```

---

## Stage 5: Constraint Application

Constraints come from the UI as a list of expression strings. Each is evaluated in the same namespace with the magic variable available:

```python
def apply_constraints(value: np.ndarray, magic_name: str,
                       constraint_exprs: list[str], namespace: dict) -> np.ndarray:
    if not constraint_exprs:
        return value

    eval_ns = {**namespace, magic_name: value, "__builtins__": {}}
    masks = []
    for expr in constraint_exprs:
        tree = parse_and_validate(expr)
        result = eval(compile(tree, "<constraint>", "eval"), eval_ns)
        if isinstance(result, np.ndarray) and result.dtype == bool:
            masks.append(result)
        else:
            raise ValueError(f"Constraint did not produce a boolean array: {expr!r}")

    combined = np.logical_and.reduce(masks)
    return np.where(combined, value, np.nan)
```

The combined mask is applied with `np.where`. NaN values produce degenerate mesh triangles that the renderer skips.

**Piecewise note:** constraints produce a masked subset of the surface. For true piecewise functions (different formulas in different regions), use `where()` directly in the primary expression:
```python
z = where(x > 0, x**2, -x**2)
```
Or use two separate equation cells with complementary constraints.

---

## Stage 6: Shape Validation

```python
EXPECTED_SHAPES = {
    "z": lambda grid: grid["x"].shape,
    "y": lambda grid: (grid["x"].shape[0],),   # 1D if x is a 1D grid
    "x": lambda grid: (grid["y"].shape[0],),
    "xyz": lambda grid: None,  # checked by axis-3 heuristic
    "points": lambda grid: None,  # checked by column count
}

def validate_shape(magic_name: str, value: np.ndarray, grid_vars: dict) -> str | None:
    if magic_name == "xyz":
        if 3 not in value.shape:
            return f"'xyz' must have an axis of size 3; got shape {value.shape}"
        return None
    if magic_name == "points":
        if value.ndim != 2 or value.shape[1] not in (2, 3):
            return f"'points' must be (N,2) or (N,3); got shape {value.shape}"
        return None
    expected = EXPECTED_SHAPES[magic_name](grid_vars)
    if value.shape != expected:
        return f"Shape mismatch for '{magic_name}': expected {expected}, got {value.shape}"
    return None
```

Returns `None` if valid, or an error string that is displayed as an inline cell warning.

---

## Full Pipeline Function

```python
def run_cell(primary_code: str, constraint_exprs: list[str],
             shared_ns: dict, grid_vars: dict) -> CellResult:
    try:
        local_ns = execute_cell(primary_code, shared_ns, grid_vars)
        magic_name, value = detect_output(local_ns, preprocess_cell(primary_code))

        if magic_name is None:
            return CellResult(warning="No renderable output detected")

        warning = validate_shape(magic_name, value, grid_vars)
        if warning:
            return CellResult(warning=warning)

        value = apply_constraints(value, magic_name, constraint_exprs, local_ns)

        return CellResult(magic_name=magic_name, value=value)

    except Exception as e:
        return CellResult(error=str(e))
```

Errors from any stage are caught and returned as inline cell errors. The renderer is not invoked for cells in error or warning state.
