"""
AST safety checker for all cells.

Walks the parsed AST and raises SecurityError if any dangerous construct
is found.  Protects against malicious shared sessions (.yml files) executing
harmful code when loaded.

Blocked constructs:
- import / from-import statements
- Calls to __dunder__ names (e.g. __import__, __class__)
- Attribute access on any double-underscore name
- Calls to exec(), eval(), compile(), open(), breakpoint() by name
"""

from __future__ import annotations
import ast


class SecurityError(ValueError):
    pass


_BLOCKED_CALLS = frozenset({"exec", "eval", "compile", "open", "breakpoint"})


class SafetyChecker(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import):
        raise SecurityError("import statements are not allowed in equation cells")

    def visit_ImportFrom(self, node: ast.ImportFrom):
        raise SecurityError("import statements are not allowed in equation cells")

    def visit_Call(self, node: ast.Call):
        # Block calls to plain names like exec(), eval()
        if isinstance(node.func, ast.Name):
            if node.func.id in _BLOCKED_CALLS:
                raise SecurityError(f"'{node.func.id}' is not allowed")
            if node.func.id.startswith("__"):
                raise SecurityError(f"dunder calls are not allowed: {node.func.id}")
        # Block calls on dunder attributes like obj.__class__()
        if isinstance(node.func, ast.Attribute):
            if node.func.attr.startswith("__"):
                raise SecurityError(f"dunder attribute calls are not allowed: {node.func.attr}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr.startswith("__"):
            raise SecurityError(f"dunder attribute access is not allowed: {node.attr}")
        self.generic_visit(node)


def check_ast(source: str) -> ast.Module:
    """
    Parse source and run the safety checker.

    Returns the parsed AST on success; raises SecurityError or SyntaxError.
    """
    tree = ast.parse(source, mode="exec")
    SafetyChecker().visit(tree)
    return tree


def get_store_names(source: str) -> set[str]:
    """
    Return the set of names that source *assigns to* (Store targets).

    Used to determine which magic variable names the user actually wrote,
    vs those that were pre-injected into the namespace by the grid.
    """
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return set()

    stores: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            stores.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stores.add(node.name)
    return stores


def get_cfg_writes(source: str) -> set[str]:
    """Return cfg attribute names that source assigns to (e.g. 'cfg.x_max = t' → {'x_max'})."""
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return set()
    writes: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Attribute)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "cfg"
        ):
            writes.add(node.targets[0].attr)
    return writes


def get_camera_writes(source: str) -> set[str]:
    """Return camera attribute names that source assigns to (e.g. 'camera.x = 5' → {'x'})."""
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return set()
    writes: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Attribute)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "camera"
        ):
            writes.add(node.targets[0].attr)
    return writes


def get_param_names(source: str) -> set[str]:
    """Return all parameter names declared by def/lambda signatures in source.

    Used by the syntax highlighter to color arguments throughout a cell.
    Returns an empty set for syntactically-incomplete source (e.g. mid-typing).
    """
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = node.args
            for arg in a.args + a.posonlyargs + a.kwonlyargs:
                names.add(arg.arg)
            if a.vararg:
                names.add(a.vararg.arg)
            if a.kwarg:
                names.add(a.kwarg.arg)
    return names


def get_free_names(source: str) -> set[str]:
    """
    Return the set of unbound names referenced in source.

    Used by the dependency graph to determine which names a cell reads
    (and therefore which cells must evaluate before it).

    Implementation: collects all Name loads and subtracts all Name stores
    (assignments, for-loop targets, function parameters, etc.).
    """
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError:
        return set()

    loads: set[str] = set()
    stores: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                loads.add(node.id)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                stores.add(node.id)
        # Function definitions store the function name + parameter names
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stores.add(node.name)
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                stores.add(arg.arg)
            if node.args.vararg:
                stores.add(node.args.vararg.arg)
            if node.args.kwarg:
                stores.add(node.args.kwarg.arg)
        # Lambda: params are locally bound — NOT free even if they appear in body
        elif isinstance(node, ast.Lambda):
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                stores.add(arg.arg)
            if node.args.vararg:
                stores.add(node.args.vararg.arg)
            if node.args.kwarg:
                stores.add(node.args.kwarg.arg)
        # Import names are stores
        elif isinstance(node, ast.Import):
            for alias in node.names:
                stores.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                stores.add(alias.asname or alias.name)
        # For-loop variables
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                stores.add(node.target.id)

    # Remove dunder names and namespace builtins from free set
    free = loads - stores
    free.discard("__builtins__")
    return free
