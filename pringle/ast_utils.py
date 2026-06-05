"""
AST utility functions used for DAG analysis and syntax highlighting.

Parses cell source and extracts structural information (free names, store
names, parameter names, cfg/camera write targets).  No security enforcement
— safety is provided by the session trust model (play button on load).
"""

from __future__ import annotations
import ast


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
        elif isinstance(node, ast.Import):
            for alias in node.names:
                stores.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                stores.add(alias.asname or alias.name)
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
