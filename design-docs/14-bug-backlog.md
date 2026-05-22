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
