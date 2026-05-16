# Expression Processing Pipeline

This document describes the full pipeline from raw cell content to rendered output. It covers preprocessing (syntax sugar → valid Python), AST analysis, execution, output detection, constraint application, and shape validation.

## Overview

```
Raw cell string (from UI) + constraint sub-cell strings (from UI)
    │
    ▼
[1] PREPROCESS
    • Detect f(args) = expr → lambda assignments
    • Detect bare string → comment cell (skip remaining stages)
    │
    ▼
[2] PARSE & VALIDATE
    • ast.parse() → AST
    • AST safety check (block dangerous node types)
    • Free variable extraction → dependency edges → undefined-variable warnings
    │
    ▼ (on slider/t change, or explicit run)
[3] EXECUTE
    • exec() in restricted namespace (numpy/scipy + shared ns + grid vars)
    • Capture bare expression values via AST transform
    │
    ▼
[4] OUTPUT DETECTION  (priority order)
    • (1) Check for magic name assignment
    • (2) Check for function signature auto-render
    • (3) Shape inference for bare expression values
    │
    ▼
[5] PIECEWISE DETECTION
    • If magic variable is a Python list → piecewise mode
    • Validate len(pieces) == len(conditions); warn and abort if not
    • Evaluate all pieces; apply np.select with implicit prior-negation
    │
    ▼
[6] CONSTRAINT APPLICATION
    • Evaluate each constraint sub-cell expression (z now available)
    • Combine masks with logical_and
    • Apply: np.where(mask, value, nan)  → z_masked (NaN outside constraint)
    • Preserve z_raw (pre-mask) and inside_mask (bool array) on CellResult
      — passed to renderer for smooth boundary clipping
    │
    ▼
[7] SHAPE VALIDATION
    • Check output shape against expected shape for render type
    • On mismatch: emit inline cell warning; skip renderer
    │
    ▼
[8] RENDERER SUBMISSION
    • Build vertex positions, indices, normals from (x, y, z_raw) grid
    • If constraint_mask provided: call _clip_mesh_to_mask()
      — Triangles fully inside → kept as-is
      — Triangles fully outside → discarded
      — Boundary triangles → clipped at edge using linear interpolation;
        midpoint vertex added at each boundary edge (cached per edge)
      — Produces smooth diagonal cuts instead of pixel-stepped staircases
    • Zero-triangle guard: if all triangles clipped away, return invisible
      placeholder mesh (opacity=0) rather than passing empty buffer to GPU
    • Apply CellStyle (color, display mode, etc.)
```

---

## Stage 1: Preprocessing

### 1a. Comment Cell Detection

Before any other processing, check if the entire cell content is a bare string literal:

```python
def is_comment_cell(code: str) -> bool:
    try:
        tree = ast.parse(code.strip(), mode="eval")
        return isinstance(tree.body, ast.Constant) and isinstance(tree.body.value, str)
    except SyntaxError:
        return False
```

If true, the cell renders as a text annotation. All remaining stages are skipped.

### 1b. Function Definition Detection

Detects `name(args) = expr` and converts to lambda assignment. Applied line-by-line.

```python
import re
FUNC_DEF = re.compile(r'^(\w+)\(([^)]*)\)\s*=\s*(.+)$')

def preprocess_func_def(line: str) -> str:
    m = FUNC_DEF.match(line.strip())
    if m:
        name, args, body = m.groups()
        return f"{name} = lambda {args}: {body}"
    return line

def preprocess_cell(code: str) -> str:
    return "\n".join(preprocess_func_def(line) for line in code.splitlines())
```

Constraint sub-cell expressions are preprocessed with the same function (a constraint could reference `f(x,y)` defined inline).

### 1c. Constraint and Condition Sub-cells

Constraint expressions come from the UI as separate strings — not parsed from the primary cell text. The pipeline receives:

```python
primary_code: str           # the main expression cell content
constraint_exprs: list[str] # from constraint sub-cells
condition_exprs: list[str]  # from piecewise condition sub-cells (if any)
```

---

## Stage 2: Parse and Validate

```python
import ast

BLOCKED_NODES = {
    ast.Import, ast.ImportFrom,
    ast.With, ast.AsyncWith,
    ast.Try, ast.TryStar,
    ast.Global, ast.Nonlocal,
    ast.Delete,
    ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
}
BLOCKED_ATTRS = {
    "__class__", "__bases__", "__subclasses__", "__globals__",
    "__builtins__", "__dict__", "__module__",
}

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

### Free Variable Extraction

```python
RESERVED = {"x", "y", "z", "u", "v", "t"}
BUILTINS_NS = set(EQUATION_NAMESPACE.keys())

def get_free_names(tree: ast.AST) -> set[str]:
    assigned, referenced = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (assigned if isinstance(node.ctx, ast.Store) else referenced).add(node.id)
    return referenced - assigned - RESERVED - BUILTINS_NS
```

Free names not defined in any other cell trigger an inline warning and "add slider" suggestion.

---

## Stage 3: Execute

### Bare Expression Capture

`ast.Expr` nodes are wrapped in auto-named assignments so their values survive into the local namespace:

```python
class CaptureExprs(ast.NodeTransformer):
    def __init__(self): self._count = 0
    def visit_Expr(self, node):
        name = f"_expr_{self._count}"; self._count += 1
        return ast.fix_missing_locations(ast.Assign(
            targets=[ast.Name(id=name, ctx=ast.Store())],
            value=node.value, lineno=node.lineno, col_offset=node.col_offset,
        ))
```

### Execution

```python
def execute_cell(code: str, shared_ns: dict, grid_vars: dict) -> dict:
    clean_code = preprocess_cell(code)
    tree = parse_and_validate(clean_code)
    tree = CaptureExprs().visit(tree)
    ast.fix_missing_locations(tree)

    local_ns = {
        **EQUATION_NAMESPACE,
        **shared_ns,
        **grid_vars,
        "__builtins__": {},
    }
    exec(compile(tree, "<cell>", "exec"), local_ns)
    return local_ns
```

---

## Stage 4: Output Detection

Detection runs in strict priority order:

```python
MAGIC_NAMES = ["z", "y", "x", "xyz", "points", "vectors"]
SPATIAL_ARGS = {"x", "y", "u", "v"}

def detect_output(local_ns: dict, source_code: str):
    clean = preprocess_cell(source_code)

    # Priority 1: magic name assignment — check source order
    for line in clean.splitlines():
        stripped = line.strip()
        for name in MAGIC_NAMES:
            if stripped.startswith(f"{name} =") and name in local_ns:
                return name, local_ns[name]

    # Priority 2: function auto-render — check for callable with spatial args
    for line in clean.splitlines():
        m = re.match(r'^(\w+)\s*=\s*lambda\s+([^:]+):', line.strip())
        if m:
            fname, args_str = m.group(1), m.group(2)
            args = {a.strip() for a in args_str.split(",")}
            if args == {"x", "y"} and fname in local_ns:
                fn = local_ns[fname]
                return "z", fn(local_ns["x"], local_ns["y"])
            if args == {"x"} and fname in local_ns:
                fn = local_ns[fname]
                return "y", fn(local_ns["x"])
            if args == {"u", "v"} and fname in local_ns:
                fn = local_ns[fname]
                return "xyz", fn(local_ns["u"], local_ns["v"])

    # Priority 3: shape inference from bare captured expressions
    for key in sorted(k for k in local_ns if k.startswith("_expr_")):
        val = local_ns[key]
        if not isinstance(val, np.ndarray):
            continue
        if val.ndim == 2 and val.shape[1] in (2, 3):
            return "points", val
        if val.shape == (2,) or val.shape == (3,):
            return "points", val.reshape(1, -1)

    return None, None
```

---

## Stage 5: Piecewise Detection

Runs after output detection if the raw magic variable value is a Python list:

```python
def handle_piecewise(piece_list, condition_exprs, namespace, grid_vars):
    if not isinstance(piece_list, list):
        return piece_list, None  # not piecewise; pass through

    if len(piece_list) != len(condition_exprs):
        return None, f"Piecewise has {len(piece_list)} pieces but {len(condition_exprs)} conditions"

    # Evaluate pieces (callable → call with grid; array → use as-is)
    x, y = grid_vars.get("x"), grid_vars.get("y")
    pieces = []
    for p in piece_list:
        if callable(p):
            # Try to infer the call signature
            import inspect
            sig = inspect.signature(p)
            param_names = list(sig.parameters.keys())
            args = [grid_vars[n] for n in param_names if n in grid_vars]
            pieces.append(p(*args))
        else:
            pieces.append(np.asarray(p))

    # Evaluate conditions with implicit prior-negation
    exclusive, accumulated = [], np.zeros_like(x, dtype=bool)
    for cexpr in condition_exprs:
        raw = eval(cexpr, {**namespace, **grid_vars, "__builtins__": {}})
        excl = raw & ~accumulated
        exclusive.append(excl)
        accumulated |= raw

    return np.select(exclusive, pieces, default=np.nan), None
```

---

## Stage 6: Constraint Application

```python
def apply_constraints(value, magic_name, constraint_exprs, namespace, grid_vars):
    if not constraint_exprs:
        return value

    eval_ns = {**namespace, **grid_vars, magic_name: value, "__builtins__": {}}
    masks = []
    for expr in constraint_exprs:
        tree = parse_and_validate(expr)
        result = eval(compile(tree, "<constraint>", "eval"), eval_ns)
        if not (isinstance(result, np.ndarray) and result.dtype == bool):
            raise ValueError(f"Constraint did not return a boolean array: {expr!r}")
        masks.append(result)

    return np.where(np.logical_and.reduce(masks), value, np.nan)
```

---

## Stage 7: Shape Validation

```python
def validate_shape(magic_name, value, grid_vars):
    if magic_name == "xyz":
        if 3 not in value.shape:
            return f"'xyz' must have an axis of size 3; got {value.shape}"
    elif magic_name == "points":
        if value.ndim != 2 or value.shape[1] not in (2, 3):
            return f"'points' must be (N,2) or (N,3); got {value.shape}"
    elif magic_name == "z":
        expected = grid_vars["x"].shape
        if value.shape != expected:
            return f"Shape mismatch: expected {expected}, got {value.shape}"
    elif magic_name in ("y", "x"):
        expected = (grid_vars["x"].shape[0],)
        if value.shape != expected:
            return f"Shape mismatch: expected {expected}, got {value.shape}"
    return None
```

---

## Full Pipeline Function

```python
def run_cell(primary_code, constraint_exprs, condition_exprs,
             shared_ns, grid_vars):
    try:
        if is_comment_cell(primary_code):
            return CellResult(comment=primary_code)

        local_ns = execute_cell(primary_code, shared_ns, grid_vars)
        magic_name, raw_value = detect_output(local_ns, primary_code)

        if magic_name is None:
            return CellResult(warning="No renderable output detected")

        # Piecewise check
        value, pw_error = handle_piecewise(raw_value, condition_exprs,
                                           local_ns, grid_vars)
        if pw_error:
            return CellResult(warning=pw_error)

        # Constraints
        value = apply_constraints(value, magic_name, constraint_exprs,
                                  local_ns, grid_vars)

        # Shape validation
        warning = validate_shape(magic_name, value, grid_vars)
        if warning:
            return CellResult(warning=warning)

        return CellResult(magic_name=magic_name, value=value,
                          namespace_contributions=local_ns)

    except Exception as e:
        return CellResult(error=str(e))
```

Namespace contributions from a successful cell are merged into `shared_ns` before dependent cells execute.
