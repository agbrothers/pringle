# Pringle — Bug Backlog

Bugs are logged here as they are identified. Each entry includes a description, reproduction steps, root cause analysis, and suggested fixes where known.

See [15-feature-backlog.md](15-feature-backlog.md) for the feature backlog.  
See [16-closed-bugs.md](16-closed-bugs.md) for resolved bugs.

---

### BUG-037 — Renderer test suite crashes with SIGABRT under Python 3.13 incremental GC

**Status:** Open  
**Logged:** 2026-05-22  
**Severity:** HIGH — all tests that instantiate `PringleRenderer` / wgpu are non-runnable in CI

**Affected test files:**
- `tests/test_phase1.py`
- `tests/test_phase2.py`
- `tests/test_phase3.py`
- `tests/test_phase4_5.py`
- `tests/test_phase10.py`
- `tests/test_phase11.py`

**Symptom:**  
Tests abort mid-run with `Fatal Python error: Aborted`. The crash occurs in the wgpu-native poller thread while the Python main thread is in a GC cycle:

```
Thread 0x... (most recent call first):
  ... wgpu/backends/wgpu_native/_poller.py line 101 in run  ← poller thread

Current thread 0x... (most recent call first):
  Garbage-collecting
  ... renderstate.py in __init__   ← main thread inside wgpu/pygfx
```

**Root cause:**  
Python 3.13 introduced incremental garbage collection. GC can fire at any instruction boundary, including inside `cffi`/wgpu C-extension calls. The wgpu-native poller thread holds resources that are also accessed by the main thread's GC cycle. The combination causes an internal abort in the native wgpu library (`wgpu_native`).

Confirmed pre-existing: `git stash` of all current changes → same crash on all 6 test files. The crash is in `wgpu` / `pygfx`, not in Pringle code.

**Workaround:**  
Run tests excluding renderer test files:
```
python -m pytest tests/ --ignore=tests/test_rendering.py \
  --ignore=tests/test_phase1.py --ignore=tests/test_phase2.py \
  --ignore=tests/test_phase3.py --ignore=tests/test_phase4_5.py \
  --ignore=tests/test_phase10.py --ignore=tests/test_phase11.py
```
157 tests pass cleanly.

**Fix directions:**
- Disable Python 3.13 incremental GC in tests via `gc.set_threshold(0)` or `gc.disable()` in a pytest plugin/conftest — may mask the crash but doesn't fix it
- Upgrade wgpu-py / pygfx — the issue may be fixed in a newer wgpu-native release
- Use Python 3.12 (no incremental GC) for CI until wgpu is fixed
- File upstream bug with wgpu-py

---

---

### BUG-040 — RuntimeWarning: overflow in float32 cast for vector-field-trajectory data

**Status:** Open  
**Logged:** 2026-05-23

**Description:**  
Running `vector-field-trajectory.yml` prints the following warning to the console:

```
/Users/greysonbrothers/code/pringle/pringle/evaluator.py:551: RuntimeWarning: overflow encountered in cast
  data = np.asarray(data, dtype=np.float32)
```

The application continues, but overflowed values are silently replaced with ±`inf` in the GPU buffer, which can produce rendering artifacts (NaN geometry, invisible faces, or stray polygons).

**Reproduction:**
1. Open `examples/vector-field-trajectory.yml`.
2. Observe the warning on stdout.

**Root cause:**  
`evaluator.py:551` casts the evaluated data to `float32` unconditionally. If the expression produces values outside the float32 range (`|x| > 3.4 × 10³⁸`), numpy emits `RuntimeWarning: overflow encountered in cast` and replaces the out-of-range values with `±inf`. The vector-field-trajectory example likely accumulates trajectory positions over many time steps, producing large values in at least one component.

**Fix directions:**
- Clamp or clip values to a safe float32 range before casting, and surface a warning on the cell if any value was clipped.
- Alternatively, detect the overflow after cast (`np.any(np.isinf(data))`) and set `result.warning` with the count of overflowed values so the user is informed.
- Review the trajectory computation in `vector-field-trajectory.yml` to check whether the overflow is a data error (e.g. unbounded trajectory escaping the domain) or just values that are legitimately large but expected.

**Affected files:**  
- `pringle/evaluator.py:551`

---

### BUG-041 — SyntaxError in recurrence RHS during mid-edit causes unhandled crash (Abort trap: 6)

**Status:** Open  
**Logged:** 2026-05-23  
**Possibly related:** BUG-038

**Description:**  
While editing a recurrence cell (specifically when adding `x` as a function argument), the app crashes with `Abort trap: 6` instead of showing an inline error. The traceback shows a `SyntaxError` during `compile()` inside `execute_recurrence`, which propagates unhandled up through `_eval_cell` → `_rebuild_namespace` → `_on_cell_changed`.

**Traceback:**
```
File ".../cell_list.py", line 876, in _on_cell_changed
    self._rebuild_namespace()
File ".../cell_list.py", line 768, in _eval_cell
    arr, warn = execute_recurrence(...)
File ".../recurrence.py", line 70, in execute_recurrence
    code = compile(rhs, "<recurrence>", "eval")
  File "<recurrence>", line 1
    path[n-1] - dt*
SyntaxError: invalid syntax
Abort trap: 6
```

**Root cause:**  
`execute_recurrence` calls `compile(rhs, "<recurrence>", "eval")` without wrapping it in a `try/except SyntaxError`. The `SyntaxError` propagates out of `_eval_cell`, which also doesn't catch it, and the exception reaches a layer (likely inside wgpu / pygfx internals) that causes a fatal abort instead of a recoverable error.

The immediate trigger is a partially-typed RHS (`path[n-1] - dt*`) — mid-edit state where the user had not yet finished the expression. The debounce or reactive evaluation fired before editing was complete.

**Note on `x` as argument:** The user noted this occurred while adding `x` as a function argument. It is possible the edit produced an intermediate parse-invalid state in the recurrence RHS, but the crash mechanism is the uncaught `SyntaxError` in `execute_recurrence` regardless of what specifically triggered the partial expression.

**Fix:**  
Wrap the `compile()` call in `recurrence.py` with `try/except SyntaxError` and return it as a user-visible warning on the cell, consistent with how other eval errors are handled:

```python
try:
    code = compile(rhs, "<recurrence>", "eval")
except SyntaxError as e:
    raise ValueError(f"Syntax error in recurrence rule: {e}") from e
```

The `ValueError` will then be caught by the existing exception handler in `_eval_cell`, which sets `result.error` and returns without crashing.

**Tests to add:**
- A recurrence cell with an incomplete RHS (e.g. `arr[n] = arr[n-1] +`) should produce `result.error` containing a syntax error message, not raise an unhandled exception.

**Affected files:**  
- `pringle/recurrence.py:70` — `compile()` call needs `try/except SyntaxError`

---

### BUG-042 — `t` cannot be used as a reliable integer index

**Status:** Open  
**Logged:** 2026-05-23

**Description:**  
`t` cannot be used as a reliable integer array index in expressions, particularly in patterns analogous to how `time` is used in `examples/vector-field-trajectory.yml` (e.g. `path[t]` or `path[int(t)]`). This is confusing because `time` (a slider) works cleanly as an index while `t` (a magic spatial variable) does not.

**Root cause (likely):**  
`t` is a magic spatial variable injected by the evaluation grid — it is a 2D float array of shape `(n, n)`, not a scalar. Attempting to use it as an array index either raises an `IndexError` (non-integer index), produces a broadcast over the 2D grid, or returns a value that is unexpectedly shaped. Additionally, if the user defines a slider named `t`, it shadows the magic `t` and the interaction between the slider scalar and the grid variable may be non-obvious or inconsistent.

A further issue: even when `t` is coerced via `int(t)`, floating-point precision at certain slider values can cause `int(1.9999...)` to undercount by 1, producing off-by-one indexing that is hard to debug.

**Expected behavior:**  
- If the user defines a slider `t`, it should be a scalar and usable as `int(t)` as an index without precision surprises.
- If no slider `t` is defined, attempting to use the magic `t` grid as an index should produce a clear warning rather than a confusing broadcast result or silent error.
- Documentation should clarify that `t` as a magic variable is the grid time axis and is not an integer counter; users wanting an integer animation frame counter should use a slider with `int()` coercion or use the `n` loop index in recurrence cells.

**Affected files:**  
- `pringle/namespace.py` — magic variable injection
- `pringle/evaluator.py` — possible conflict between slider `t` and magic `t`
- `design-docs/03-expression-evaluation.md` — documentation clarification
- `design-docs/07-cell-types-and-blocks.md` — magic variable table

---

### BUG-038 — Assigning to a reserved spatial variable crashes the app instead of warning the user

**Status:** Open  
**Logged:** 2026-05-22

**Description:**  
Writing `x = linspace(0, 100)` (or any bare assignment to a reserved spatial variable) in an equation cell causes an unhandled `ValueError` that propagates past the renderer and terminates the process with `Abort trap: 6`. The user receives no diagnostic; the application dies silently. The correct behavior is a warning message explaining that the variable is reserved.

**Reproduction:**
1. Open a fresh Pringle session (default 64-point grid).
2. Add an equation cell and type `x = linspace(0, 100)`.
3. The cell evaluates → `ValueError: all the input array dimensions except for the concatenation axis must match exactly, but along dimension 0, the array at index 0 has size 50 and the array at index 1 has size 64` → `Abort trap: 6`.

**Root cause:**  
The evaluation pipeline has three layers that interact incorrectly:

1. **`preprocess.is_slider_cell`** (`preprocess.py:102`) correctly rejects `x = linspace(0, 100)` as a slider (it checks `name in MAGIC_NAMES or name in SPATIAL_NAMES`). The cell is therefore routed through the full equation evaluator.

2. **`run_cell`** (`evaluator.py:336`) executes the source with `exec(preprocessed, local_ns)`. The grid variables (`x`, `y`, `u`, `v`, `t`) are injected into `local_ns` at Layer 5 *before* exec runs (line ~401), but `exec` writes back into that same dict, so the user's `x = linspace(0, 100)` overwrites the grid's 2D `x` array with a 50-element 1D array. `get_store_names` records `"x"` in `user_stores`. No guard exists here.

3. **`_detect_magic`** (`evaluator.py:61`) sees `"x" in user_stores`, finds a 1D ndarray in `local_ns["x"]`, and returns render type `"curve_x"` with the user's 50-element array as `result.data`.

4. **`_on_cell_result`** (`app.py:602`) handles `"curve_x"` by calling `np.column_stack([result.data, self._grid.y1d, zeros(...)])`. `result.data` has 50 elements; `self._grid.y1d` has 64 elements → `ValueError` → unhandled → `Abort trap: 6`.

The shape-validation helper `_check_render_data` (`evaluator.py:305`) already validates `surface`, `curve`, and `scatter` types but has no case for `curve_x`, so the bad length slips through.

**Design note — `curve_x` removal:**  
`x = f(y)` (the `curve_x` render type) is currently listed as a supported feature in `05-architecture-decisions.md` and `07-cell-types-and-blocks.md`. The decision has been made to **remove** this feature: `x`, `u`, `v`, and `t` are strictly input/spatial variables and should not be assignable. This bug fix should implement that removal. `y` remains a valid magic output variable for curve rendering (`y = f(x)`).

**Affected files:**  
- `pringle/evaluator.py` — `run_cell`, `_detect_magic`, `_check_render_data`
- `pringle/app.py` — `_on_cell_result` (defensive guard)
- `design-docs/05-architecture-decisions.md` — remove `x = f(y)` from curve list
- `design-docs/07-cell-types-and-blocks.md` — remove `x` row from magic variable table

**Suggested fix:**

**Step 1 — Guard in `run_cell` (`evaluator.py`, after line 385):**  
After `user_stores = get_store_names(preprocessed)`, add an early-return that fires whenever the user assigns to any reserved spatial input variable. Use the set `SPATIAL_NAMES - {"y"}` (i.e., `{"x", "u", "v", "t"}`); `y` is exempt because it is a valid magic output for curve rendering.

```python
_RESERVED_INPUT = SPATIAL_NAMES - {"y"}  # x, u, v, t are input-only
reserved_conflicts = user_stores & _RESERVED_INPUT
if reserved_conflicts:
    name = sorted(reserved_conflicts)[0]
    result.warning = (
        f"'{name}' is a reserved variable and cannot be assigned to. "
        f"Pringle automatically injects x, y, u, v, and t as the evaluation grid. "
        f"To render, assign to a magic output variable: "
        f"z (surface), y (curve), xyz (parametric), or points (scatter)."
    )
    return result
```

The warning is intentionally set on `result.warning` (orange indicator), not `result.error`, so the cell stays non-fatal.

**Step 2 — Remove `x` branch from `_detect_magic` (`evaluator.py:87-90`):**  
Delete the `if "x" in user_stores:` block. It is dead code once the Step 1 guard is in place, and removing it makes the intent explicit.

**Step 3 — Defensive guard in `_on_cell_result` (`app.py`, `curve_x` branch):**  
Even if Step 1 is present, add a length check before `np.column_stack` to prevent any future regression from reaching an unhandled exception:

```python
elif result.render_type == "curve_x":
    if len(result.data) != len(self._grid.y1d):
        # Mismatched lengths — silently skip; upstream should have warned
        vp.remove_object(cell_id)
        return
    pts = np.column_stack([...])
```

**Step 4 — Update design docs:**  
- `05-architecture-decisions.md` line 117: remove `x = f(y)` from the curve plots entry.
- `07-cell-types-and-blocks.md` line 28: remove the `x` / `Curve (implicit role)` row from the magic variable table.

**Tests to add:**  
Add to the existing evaluator test suite (e.g., `tests/test_phase3.py`):
- `x = linspace(0, 100)` → `result.warning` is non-empty, `result.render_type` is `None`, no exception raised
- `u = zeros((64, 64))` → same: warning, no crash
- `t = 5.0` → same: warning, no crash
- `y = sin(x)` → still produces `render_type == "curve"` (y is not blocked)
- `z = x**2 + y**2` → still produces `render_type == "surface"` (z is not blocked)

---

### BUG-044 — Constant values outside default slider range (min=0, max=10) do not morph to slider

**Status:** Open  
**Logged:** 2026-05-23  
**Related:** BUG-043 (morph timing)

**Description:**  
When a scalar assignment like `a = 15` or `a = -3` is typed, the morph to `SliderWidget` does not occur because the value falls outside the hardcoded default range `[0, 10]`. The value is either silently rejected, displayed as a plain equation cell, or clamped. This makes it impossible to quickly create sliders for parameters with natural values outside that range.

**Reproduction:**
1. Type `a = 15` in an equation cell and press Enter (or click away).  
2. The cell does not become a slider — it remains an equation cell (or produces unexpected behavior).

**Root cause:**  
`_maybe_morph_to_slider` (or the `SliderWidget` constructor) validates that the initial value fits within `[_DEFAULT_MIN, _DEFAULT_MAX]` (currently `0` and `10`) and bails out if it does not, instead of expanding the range to accommodate the value.

**Fix:**  
When constructing the initial slider range for a new morph, derive the bounds dynamically from the value rather than using a hardcoded `[0, 10]`:

```python
def _initial_slider_range(value: float) -> tuple[float, float]:
    """Choose a sensible default range that always contains value."""
    if value == 0:
        return 0.0, 10.0
    elif value > 0:
        return 0.0, _round_up_nice(value * 2)
    else:  # value < 0
        return _round_down_nice(value * 2), 0.0

def _round_up_nice(x: float) -> float:
    """Round x up to a round number (next power of 10, or nearest 5/10 multiple)."""
    import math
    mag = 10 ** math.floor(math.log10(abs(x)))
    return math.ceil(x / mag) * mag
```

Simpler alternative (acceptable for v1): `min = min(0, value)`, `max = max(10, value)`. This is less elegant but always contains the value and avoids the rounding logic.

**Tests to add:**
- `a = 15` → morphs to `SliderWidget` with value `15.0` and `max >= 15`.
- `a = -3` → morphs to `SliderWidget` with value `-3.0` and `min <= -3`.
- `a = 0` → morphs to `SliderWidget` with value `0.0` and default range `[0, 10]`.
- `a = 5` → morphs to `SliderWidget` with value `5.0`, range still contains `5`.

**Affected files:**  
- `pringle/cell_list.py` — `_maybe_morph_to_slider` (initial range selection)
- `pringle/cell_widget.py` (or `slider_widget.py`) — `SliderWidget` constructor validation

---

### BUG-045 — Slider value clamped to range bounds instead of flagging the offending bound

**Status:** Open  
**Logged:** 2026-05-23  
**Related:** BUG-044 (range bounds)

**Description:**  
When the user manually types a value into the slider's value field that falls outside `[min, max]`, the value is silently snapped back to the nearest bound. The desired behavior is to keep the typed value and instead show a red border on whichever bound is now invalid — identical to the existing red-border pattern for invalid text inputs elsewhere in the UI — so the user knows to widen the range rather than having their value overwritten.

**Reproduction:**
1. Create a slider `a = 5` with default range `[0, 10]`.
2. Click the value field and type `15`, then press Tab or Enter.
3. The value snaps back to `10` — the typed `15` is lost.

**Expected behavior:**
- The value field shows `15`.
- The `max` field gets a red border (since `max=10 < value=15`).
- The red border on `max` clears once the user sets `max >= 15`.
- Symmetrically: if the user types `-3` and `min=0`, the `min` field gets the red border.

**Root cause:**  
The `SliderWidget` value-commit handler clamps the incoming value via `np.clip(value, self._min, self._max)` (or equivalent) before storing it, discarding out-of-range input. There is no validation pass that checks the bound fields against the current value and applies a red-border style.

**Fix:**

In the value-field commit handler (`SliderWidget`):
```python
def _on_value_committed(self, text: str) -> None:
    try:
        v = float(text)
    except ValueError:
        self._value_edit.setStyleSheet("border: 1px solid red;")
        return
    self._value = v   # store unclamped
    self._value_edit.setStyleSheet("")  # clear any previous error
    self._validate_bounds()             # check if bounds need flagging
    self._update_handle_position()
    self.value_changed.emit(self._value)

def _validate_bounds(self) -> None:
    """Flag min/max fields with red border if they conflict with current value."""
    min_invalid = self._value < self._min
    max_invalid = self._value > self._max
    red = "border: 1px solid red;"
    self._min_edit.setStyleSheet(red if min_invalid else "")
    self._max_edit.setStyleSheet(red if max_invalid else "")
```

Call `_validate_bounds()` also from the min/max commit handlers so the border clears as soon as the user fixes the bound. The slider handle position should clamp visually to `[min, max]` when the value is outside bounds (so the track remains usable), but the stored value and namespace value must reflect the actual typed number.

**UX note:**  
The slider track handle should clamp visually to the nearer end when the value is outside range (same as today), but the namespace-exported value and the value field text must be the true un-clamped value. This ensures downstream expressions see `a = 15` even if the track shows the handle pegged at the right end.

**Tests to add:**
- Typing `15` into the value field of a `[0, 10]` slider stores value `15`, shows red border on `max`, no red on `min`.
- Typing `-3` stores `-3`, red border on `min`, none on `max`.
- After correcting `max` to `20`, the red border clears and the handle repositions.
- Typing a non-numeric string shows red on the value field itself (existing behavior).

**Affected files:**  
- `pringle/cell_widget.py` or `pringle/slider_widget.py` — value/bound commit handlers, `_validate_bounds` helper

---
