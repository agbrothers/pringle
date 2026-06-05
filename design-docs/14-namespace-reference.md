# Namespace Reference

All names pre-populated in equation cell expressions are enumerated here. The list is intentionally explicit — adding a convenience name requires a deliberate line in `pringle/namespace.py`. Cells can also `import` any Python module after the session trust gate is cleared (play button on load). See `03-expression-evaluation.md` for the trust model.

## How the namespace is built

Every cell executes in a fresh dict constructed by `build_equation_namespace()`. It contains:

1. **Module aliases** — `np = numpy`, `math` — so `np.sin(x)` and `math.floor(t)` work without an explicit import
2. **numpy/scipy convenience names** — imported individually for backward compatibility with existing `.yml` files (`sin`, `cos`, `pi`, etc.)
3. **Python builtins** — available normally (no `__builtins__` restriction)

Cell-level imports (`import scipy.optimize`) override pre-populated names naturally via standard Python scoping.

---

## Module aliases

`np` — the full `numpy` module (`np.sin`, `np.array`, `np.linalg.norm`, …)

`math` — the stdlib `math` module (`math.floor`, `math.factorial`, `math.tau`, …)

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

## Python builtins

Standard Python builtins are all available (no `__builtins__` restriction). Commonly used:

### Type constructors
`bool`, `int`, `float`, `complex`, `str`, `bytes`, `tuple`, `list`, `dict`, `set`

### Iterators and sequences
`range`, `enumerate`, `zip`, `sorted`, `reversed`, `len`, `map`, `filter`

### Type inspection
`isinstance`, `issubclass`, `callable`

---

## Adding a new convenience name

1. Add an import line in `namespace.py` under the appropriate group.
2. Add the name to the `ns` dict in `build_equation_namespace()` with a section comment.
3. Add it to the appropriate table in this doc.
