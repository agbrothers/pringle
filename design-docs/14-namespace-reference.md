# Namespace Reference

All names reachable from equation cell expressions are enumerated here. The list is intentionally explicit and auditable — adding a name requires a deliberate line in `pringle/namespace.py`, not a wildcard import.

## How the namespace is built

Every cell executes in a fresh dict constructed by `build_equation_namespace()`. It contains three layers:

1. **Whitelisted numpy/scipy names** — imported individually and added by name
2. **Safe Python builtins** — a curated subset; all others are blocked
3. **`__builtins__: {}`** — explicitly empties the builtins slot so any name not in layers 1–2 raises `NameError` at runtime

The AST safety check (`safety.py`) runs before `exec()` and blocks dunder attribute access (`obj.__anything__`), import statements, and calls to a set of named dangerous functions. These two layers together — restricted namespace + AST check — form the security model. See `03-expression-evaluation.md` for the threat model and reasoning.

---

## numpy

### Trigonometry
`sin`, `cos`, `tan`, `arcsin`, `arccos`, `arctan`, `arctan2`, `hypot`,
`sinh`, `cosh`, `tanh`, `arcsinh`, `arccosh`, `arctanh`

### Rounding / casting
`abs`, `floor`, `ceil`, `round`, `sign`, `clip`, `mod`, `int_`, `intp`

### Exponential / log
`exp`, `exp2`, `log`, `log2`, `log10`, `sqrt`, `cbrt`, `power`

### Array creation
`zeros`, `ones`, `empty`, `full`,
`zeros_like`, `ones_like`, `empty_like`, `full_like`,
`linspace`, `arange`, `meshgrid`,
`array`, `asarray`

### Stacking / joining
`concatenate`, `stack`, `column_stack`, `row_stack`, `hstack`, `vstack`

### Shape manipulation
`reshape`, `ravel`, `transpose`, `squeeze`

### Math / reduction
`sum`, `prod`, `cumsum`, `cumprod`,
`min`, `max`, `mean`, `median`, `std`, `var`, `maximum`, `minimum`,
`diff`, `gradient`,
`dot`, `cross`, `outer`, `einsum`

### Boolean / masking
`where`, `select`,
`isnan`, `isinf`, `isfinite`,
`logical_and`, `logical_or`, `logical_not`,
`any`, `all`

### Constants
`pi`, `e`, `inf`, `nan`

### Dtypes
`float32`, `float64`, `int32`, `int64`, `complex64`, `complex128`, `bool_`

Use as keyword arguments: `zeros((n, 3), dtype=float32)`.

### Random
`random` — the `numpy.random` module, available as a sub-namespace.
Example: `random.randn(100, 3)`, `random.uniform(0, 1, size=(50,))`.

---

## scipy

### scipy.special
`gamma`, `factorial`, `comb`,
`erf`, `erfc`, `erfinv`,
`j0`, `j1`, `jn`, `yn`,
`legendre`,
`logsumexp`

### scipy.linalg
`norm`, `det`, `inv`, `solve`, `eig`, `eigvals`, `svd`

---

## Safe Python builtins

These are explicitly whitelisted. They are common enough that excluding them causes real friction when porting Python code, and none of them provide a path around the AST dunder block.

### Type constructors
`bool`, `int`, `float`, `complex`, `str`, `bytes`, `tuple`, `list`, `dict`, `set`

### Iterators and sequences
`range`, `enumerate`, `zip`, `sorted`, `reversed`, `len`

### Type inspection
`isinstance`, `issubclass`, `callable`

---

## Excluded builtins — and why

These are intentionally absent. Each one either opens a direct escape path or is simply unnecessary given the available alternatives.

| Name | Why excluded |
|---|---|
| `getattr`, `setattr`, `hasattr` | **The main bypass.** These accept the attribute name as a runtime string, which sidesteps the AST dunder check. `getattr(sin, '__globals__')` would succeed where `sin.__globals__` is blocked. |
| `vars`, `dir`, `locals`, `globals` | Expose the execution namespace or the live globals of Python objects — direct information leak / escape path. |
| `type`, `object`, `super` | `type(x)` is equivalent to `x.__class__` and returns a live class object. Without `getattr`, the escape path is blocked, but these offer no utility that `isinstance` doesn't cover. |
| `eval`, `exec`, `compile` | Direct arbitrary code execution. Blocked by both name in the AST check and absence from namespace. |
| `open`, `input` | Filesystem and stdin access. |
| `__import__`, `importlib` | Module loading. `import` statements are also blocked at the AST level. |
| `print` | No output destination in the rendering context; use cell return values. |
| `map`, `filter` | Omitted for now — the numpy equivalents (`where`, vectorized expressions) cover the scientific use cases cleanly. Can be added if there is demand. |
| `format`, `repr` | Rarely needed in math expressions; `str()` and f-strings are available. |
| `id`, `hash` | No meaningful use in math expressions. |
| `breakpoint`, `exit`, `quit` | Process control. Blocked by name in the AST check. |
| `memoryview`, `bytearray` | Low-level buffer types with no math use case. |
| `property`, `staticmethod`, `classmethod` | Class machinery — no use without `class` definitions. |

### Why `map` and `filter` are excluded (but reconsidered if needed)

In most Pringle expressions, `map` and `filter` are replaceable by numpy vectorized operations (`where`, boolean indexing, list comprehensions). They are not blocked for security reasons — they are simply omitted to keep the namespace minimal. File an issue if they become necessary.

---

## Adding a new name

1. Add an import line in `namespace.py` under the appropriate group.
2. Add the name to the `ns` dict in `build_equation_namespace()` with a section comment.
3. Add it to the appropriate table in this doc.
4. If it is a Python builtin, add a row to the "Excluded builtins" table explaining why it is now included (or remove its row if it was previously excluded).
