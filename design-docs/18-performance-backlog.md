# Pringle — Performance Backlog

Performance issues are logged here as they are identified through static analysis, dynamic profiling, or user observation. Each entry includes a root cause analysis, estimated impact, and a suggested fix.

See [19-closed-performance.md](19-closed-performance.md) for resolved issues.  
See [20-profiling-sop.md](20-profiling-sop.md) for the profiling standard operating procedure.

**Performance target:** ≥ 30 fps at n=128 (≤ 33 ms total per animation frame).

---

## Measured Baseline (2026-05-19, n=128, 30 frames)

Run via `python tests/bench_slider_animation.py --n 128 --frames 30`.

| Component | Mean ms | % of 33ms budget |
|-----------|---------|-----------------|
| `_clip_mesh_to_mask` (→ BUG-001) | **170.2** | **516%** |
| `_grid_indices` (PERF-003) | **54.7** | **166%** |
| Cell evaluation chain (PERF-001, PERF-006) | **17.0** | **52%** |
| ↳ z_surface computation alone | 10.9 | 33% |
| `_grid_normals` | 2.6 | 8% |
| AST pipeline / 6 downstream cells (PERF-006) | 2.7 | 8% |
| `build_equation_namespace()` (PERF-005) | 0.02 | ~0% |
| **Estimated total frame** | **253** | **767%** |

**Effective frame rate at baseline: ~4 fps at n=128.**

---

## Post-patch Benchmark (2026-05-20, n=128, 30 frames)

After BUG-001 partial fix and PERF-003 vectorization (both applied by dev 2026-05-20). Geometry functions timed directly via inline benchmark (bench script API mismatch after refactor; see PERF-010).

| Component | Mean ms | % of 33ms budget | vs baseline |
|-----------|---------|-----------------|-------------|
| `_clip_mesh_to_mask` (partial fix, PERF-010) | **26.7** | **81%** | 6.4× faster |
| `_grid_gradients + _grid_normals` (FEAT-038) | 0.31 | 1% | — |
| `_grid_indices` (PERF-003, closed) | 0.19 | 1% | 295× faster |
| Cell evaluation chain (PERF-001, PERF-006) | **17.0** | **52%** | unchanged |
| **Estimated total frame** | **44** | **134%** | **5.7× faster** |

**Effective frame rate post-patch: ~23 fps at n=128.** Below 30 fps target. Primary remaining bottleneck is PERF-010 (O(n²) vertex list conversion inside `_clip_mesh_to_mask`). Fixing it is estimated to cut the function from 26.7 ms to ~3–5 ms and push the frame to ~20 ms (~50 fps).

---

## Priority Legend

| Priority | Description |
|----------|-------------|
| CRITICAL | Blocks 30fps target on its own; must fix before any other optimization |
| HIGH | Significant contribution to frame budget; fix in first optimization pass |
| MEDIUM | Measurable but not dominant; address in second pass |
| LOW | Minor; fix opportunistically or when touching the relevant code |

---

### PERF-010 — O(n²) vertex list/array roundtrip in `_clip_mesh_to_mask`
**Status:** Open  
**Priority:** CRITICAL  
**Logged:** 2026-05-20  
**Discovered via:** Post-patch benchmark (2026-05-20)  
**Measured impact:** ~13 ms of the 26.7 ms `_clip_mesh_to_mask` total at n=128; function still at 81% of frame budget after BUG-001 partial fix  
**Files:** [renderer.py:99-100](../pringle/renderer.py#L99), [renderer.py:153-154](../pringle/renderer.py#L153)

**Description:**  
The BUG-001 patch vectorized triangle classification correctly (O(n) boundary loop), but retained a full-array Python list conversion that is still O(n²):

```python
# line 99-100 — called every frame, always:
new_pos = list(positions)   # 16,384 numpy rows → Python list
new_nor = list(normals)     # 16,384 numpy rows → Python list
...
# line 153-154 — rebuild from list:
out_pos = np.array(new_pos, dtype=np.float32)   # list → numpy
out_nor = np.array(new_nor, dtype=np.float32)
```

This conversion costs ~13 ms regardless of how many boundary triangles exist. At n=128, 16,384 rows are converted to and from Python lists on every animation frame even though only ~512 new boundary vertices are appended. The numpy array creation from a heterogeneous Python list is particularly slow because numpy must process each row individually.

**Fix:**  
Avoid converting the full position/normal arrays to Python lists. Instead, accumulate only the *new* boundary vertices in a small separate list, then `np.concatenate` them with the original arrays:

```python
# Replace lines 99-154 with:
new_verts_pos: list[np.ndarray] = []
new_verts_nor: list[np.ndarray] = []
vertex_offset = len(positions)   # index of first new vertex

def _bv(ia: int, ib: int) -> int:
    key = (min(ia, ib), max(ia, ib))
    if key in edge_cache:
        return edge_cache[key]
    f_a, f_b = float(f_values[ia]), float(f_values[ib])
    denom = f_a - f_b
    t = float(np.clip(f_a / denom, 0.0, 1.0)) if abs(denom) > 1e-10 else 0.5
    new_verts_pos.append(positions[ia] + t * (positions[ib] - positions[ia]))
    nv = normals[ia] + t * (normals[ib] - normals[ia])
    length = float(np.linalg.norm(nv))
    new_verts_nor.append(nv / length if length > 1e-8 else nv)
    vi = vertex_offset + len(new_verts_pos) - 1
    edge_cache[key] = vi
    return vi

# ... boundary loop unchanged ...

if new_verts_pos:
    out_pos = np.concatenate([positions, np.array(new_verts_pos, dtype=np.float32)], axis=0)
    out_nor = np.concatenate([normals,   np.array(new_verts_nor, dtype=np.float32)], axis=0)
else:
    out_pos, out_nor = positions, normals
```

This reduces the `np.array()` call from 16,384 rows to ~512 rows (the new boundary vertices only). The original arrays are passed through unchanged via `np.concatenate`, which is O(1) for the original slice.

**Estimated impact after fix:** `_clip_mesh_to_mask` ~3–5 ms → frame total ~20 ms → ~50 fps.

---

### PERF-001 — DAG rebuilt from scratch on every animation tick
**Status:** Open  
**Priority:** CRITICAL  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [dag.py:85-106](../pringle/dag.py#L85), [cell_list.py:808-831](../pringle/cell_list.py#L808)

**Description:**  
Every 16 ms slider animation tick triggers `_on_slider_value_changed`, which calls `build_dag(evaluable)` unconditionally before evaluating downstream cells. `build_dag` calls `cell_defines()` and `cell_uses()` for every evaluable cell in the session. Each of those calls `_preprocess_src()` (a regex match) and then `get_store_names()` or `get_free_names()` (a full `ast.parse()` round-trip). With memory.yml's ~20 evaluable cells this produces roughly **40 AST parses per frame** just to reconstruct a dependency graph that has not changed.

The DAG only changes when a cell's source text changes (`content_changed` signal). Between edits — including the entire duration of slider animation — the graph is identical on every tick.

**Estimated cost:** ~40 × `ast.parse()` + regex per frame; likely 2–5 ms per tick at n=128.

**Fix:**  
Cache the `nx.DiGraph` and the `downstream_of` result keyed on `{cell_id: source_text}` for the evaluable cells. Invalidate the cache in `_on_cell_changed` (the only signal that changes cell sources). On a slider tick, skip `build_dag` entirely and use the cached descendants list.

```python
# In CellListWidget.__init__:
self._dag_cache: nx.DiGraph | None = None
self._dag_source_key: dict[str, str] = {}  # cell_id → source at last build

def _get_dag(self, evaluable: list) -> nx.DiGraph:
    key = {c.cell_id: c.source() for c in evaluable}
    if key != self._dag_source_key or self._dag_cache is None:
        self._dag_cache = build_dag(evaluable)
        self._dag_source_key = key
    return self._dag_cache
```

---

### PERF-002 — Full GPU geometry recreated on every surface update
**Status:** Open  
**Priority:** CRITICAL  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [renderer.py:162-231](../pringle/renderer.py#L162), [renderer.py:592-603](../pringle/renderer.py#L592)

**Description:**  
`make_surface_mesh` constructs brand-new `positions`, `indices`, and `normals` numpy arrays on every call, then wraps them in new `gfx.Geometry` and `gfx.Mesh` objects. `add_object` then removes the old scene object and adds the new one, triggering a full GPU buffer upload.

During slider animation, only the z-values change. The mesh topology (index buffer) and the x/y positions are constant across all frames. Yet the entire ~770 KB of data (positions + indices + normals at n=128) is re-uploaded to the GPU every 16 ms.

| Buffer | Size at n=128 | Changes per frame? |
|--------|---------------|--------------------|
| positions (N×3 float32) | 192 KB | z column only |
| indices (T×3 int32) | ~387 KB | Never during animation |
| normals (N×3 float32) | 192 KB | Yes (z-dependent) |
| **Total** | **~771 KB** | — |

**Measured cost (headless benchmark):** The CPU object-creation overhead (~9 ms difference between `geo/cpu_total` and `mesh/make_surface_mesh` at n=128) is small noise against PERF-003/004. **The GPU upload cost is not captured by the headless benchmark** — `gfx.Geometry` defers the actual wgpu buffer upload until the first `render()` call, which the benchmark never invokes. The ~771 KB upload cost is therefore a blind spot in the current numbers and must be measured via Instruments / wgpu timestamp queries (SOP Phase 5). This issue becomes the dominant bottleneck once PERF-003 and PERF-004 reduce CPU geometry time from ~227 ms to ~3 ms.

**Fix (short-term):** Cache the index buffer (`_grid_indices` result) per grid shape — it never changes for a fixed n. Pass it into `make_surface_mesh` as an optional argument to avoid recomputing it.

**Fix (long-term):** Maintain live `gfx.Geometry` objects per cell and update only the z-values and normals in-place using pygfx's buffer update API (`.data[...] = new_values` on a `gfx.Buffer`). The index buffer is never uploaded again after the first frame.

```python
# Pseudocode for buffer update path:
if cell_id in self._live_geometry:
    geo = self._live_geometry[cell_id]
    geo.positions.data[:, 2] = z.ravel()  # update z in-place
    geo.positions.update_range(0, len(z.ravel()))
    # recompute and upload normals only
else:
    # first frame: full construction
    ...
```

---

### PERF-005 — `build_equation_namespace()` called twice per `run_cell` invocation
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Measured impact:** 0.02 ms per call at n=128 — effectively free; deprioritized relative to backlog  
**Files:** [evaluator.py:346](../pringle/evaluator.py#L346), [evaluator.py:365](../pringle/evaluator.py#L365)

**Description:**  
`run_cell` calls `build_equation_namespace()` at line 346 to build the execution namespace, and then calls it again at line 365 alongside `grid_vars(grid)` just to compute `base_keys` — the set of names that should not be exported from the cell's output. This second call constructs a fresh 100+-key dict and discards it immediately.

```python
# line 346 — used for execution:
local_ns = build_equation_namespace()

# line 365 — used only for key set, dict immediately discarded:
base_keys = set(build_equation_namespace().keys()) | set(grid_vars(grid).keys())
```

**Estimated cost:** 2 dict constructions per cell per frame; minor individually but the memory.yml β chain evaluates ~6 downstream cells per tick → 12 wasted namespace constructions per frame.

**Fix:** Precompute `_BASE_KEYS` as a module-level frozenset. Both `build_equation_namespace().keys()` and `grid_vars(make_grid()).keys()` are static; they do not depend on runtime state:

```python
# evaluator.py module level:
_BASE_KEYS: frozenset[str] = frozenset(build_equation_namespace()) | frozenset(grid_vars(make_grid()))

# run_cell: replace line 365 with:
for k, v in local_ns.items():
    if k.startswith("__") or k in _BASE_KEYS or k in MAGIC_NAMES:
        continue
    result.exports[k] = v
```

---

### PERF-006 — AST parsed 3× per `run_cell` invocation
**Status:** Open  
**Priority:** MEDIUM  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [evaluator.py:333-339](../pringle/evaluator.py#L333), [safety.py:52-60](../pringle/safety.py#L52), [safety.py:63-81](../pringle/safety.py#L63), [safety.py:84-140](../pringle/safety.py#L84)

**Description:**  
For each equation cell evaluation, `run_cell` triggers three separate `ast.parse()` calls on the same preprocessed source string:

1. `get_free_names(preprocessed)` — parses to find Load references  
2. `get_store_names(preprocessed)` — parses again to find Store targets  
3. `check_ast(preprocessed)` — parses a third time for the security walk

Each parse is independent; the AST object is not shared between them. Additionally, the DAG functions (`cell_defines`, `cell_uses` in `dag.py`) parse the same source a fourth and fifth time per rebuild tick.

**Estimated cost:** At ~50 µs per `ast.parse` call on typical expression lengths, 3 parses per cell × 6 downstream cells = 18 parse calls per frame ≈ ~0.9 ms. Larger cells and larger sessions will scale this higher.

**Fix:** Parse once in `run_cell` and pass the `ast.Module` object to all consumers. Requires adding an `ast_tree` parameter to `get_free_names`, `get_store_names`, and `check_ast`:

```python
# evaluator.py
tree = ast.parse(preprocessed, mode="exec")
result.free_names = get_free_names(preprocessed, tree=tree)
user_stores = get_store_names(preprocessed, tree=tree)
if not is_data_cell:
    check_ast(preprocessed, tree=tree)
```

---

### PERF-007 — Shadow geometry created unconditionally even when shadows are disabled
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [renderer.py:592-603](../pringle/renderer.py#L592)

**Description:**  
`add_object` always calls `_make_shadow_object(obj)` and, if successful, adds the shadow to the scene. This copies position arrays and creates `gfx.Geometry`/`gfx.Mesh` scene objects even when `self._shadow_visible` is `False` (the default). The shadows are then immediately hidden via `.visible = False`, but the allocation and scene-graph overhead still occurs every frame.

**Fix:** Guard the shadow creation with `if self._shadow_visible`:

```python
def add_object(self, cell_id: str, obj: gfx.WorldObject) -> bool:
    is_new = cell_id not in self._objects
    self.remove_object(cell_id)
    self._objects[cell_id] = obj
    self._scene.add(obj)
    if self._shadow_visible:                    # ← add this guard
        shadow = self._make_shadow_object(obj)
        if shadow is not None:
            shadow.visible = True
            self._scene.add(shadow)
            self._shadow_objects[cell_id] = shadow
    return is_new
```

---

### PERF-008 — Viewport issues unconditional `request_draw()` at 60 fps regardless of scene state
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [app.py:68-71](../pringle/app.py#L68)

**Description:**  
`PringleViewport._tick()` calls `self.request_draw()` unconditionally every 16 ms — even when no slider is animating, no cell has changed, and the camera has not moved. This causes the wgpu renderer to re-render an identical scene at 60 fps, consuming GPU time and power for no visual benefit.

**Fix:** Introduce a `_scene_dirty` flag on `PringleRenderer`. Set it in `add_object`, `remove_object`, `set_visible`, `_rebuild_overlay`, and during active camera orbit/pan. Clear it after each `render()` call. In `_tick`, only call `request_draw()` if the scene is dirty or held keys are active.

---

### PERF-009 — `_always_defined()` in `dag.py` rebuilds the equation namespace on first call
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis  
**Files:** [dag.py:26-35](../pringle/dag.py#L26)

**Description:**  
`_always_defined()` lazily builds and caches its result from `build_equation_namespace()` on first call — this is fine. However, if the module is freshly imported (new process), the first DAG build pays a construction cost. Additionally, the result is a module-level `global` mutated in-place, which can cause subtle bugs in multi-threaded futures.

**Fix:** Replace with a module-level constant computed at import time:

```python
from pringle.namespace import build_equation_namespace
from pringle.preprocess import SPATIAL_NAMES

_ALWAYS_DEFINED: frozenset[str] = (
    frozenset(build_equation_namespace())
    | SPATIAL_NAMES
    | {"t", "True", "False", "None"}
)
```

---

## YAML Equation Optimization Issues

These issues are specific to how expressions are written in session files and represent tips that can be documented in a user-facing guide.

---

### PERF-Y01 — `shape = array([x, y]).shape[1:]` allocates a full temporary array to read a shape
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis of memory.yml  
**Session file:** examples/memory.yml

**Description:**  
The UTILS/shape cell constructs a full `(2, 128, 128)` array (≈ 786 KB at n=128) merely to call `.shape[1:]`. Since `x` is already a `(n, n)` array, the shape is simply `x.shape`.

**Current expression:**
```python
shape = array([x, y]).shape[1:]
```

**Optimized expression:**
```python
shape = x.shape
```

This avoids a 786 KB allocation on every evaluation of this cell.

---

### PERF-Y02 — `E` function uses a Python list comprehension that inhibits vectorization
**Status:** Open  
**Priority:** MEDIUM  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis of memory.yml  
**Session file:** examples/memory.yml

**Description:**  
The ENERGY/E cell is defined as:
```python
E(v) = -β_inv * Q( sum( [F ( β*( S(m[:, None], v) ) ) for m in M], axis=0))
```

The `[... for m in M]` list comprehension iterates over the rows of `M` one at a time in Python, creating `k` intermediate arrays (one per memory point) before passing a Python list to `sum`. For k=10 memory points this is 10 separate numpy calls and Python iterations.

`E_batch` — the visible surface cell — already uses the fully batched `InvDistSqBatch` and is the correct implementation. However, `E` is still visible in the session and could mislead users who copy it.

**Note:** `E` is set to `visible: false` in memory.yml, so it does not currently affect rendering performance. This is a documentation issue — the non-batch version should be clearly marked as the naive/reference implementation.

**Optimized pattern:** Always prefer batch operations over Python loops over array rows. See [21-equation-tips.md](21-equation-tips.md) (forthcoming) for the full vectorization guide.

---

### PERF-Y03 — `logsumexp` could replace `log(sum(exp(...)))` for numerical stability and speed
**Status:** Open  
**Priority:** LOW  
**Logged:** 2026-05-19  
**Discovered via:** Static analysis of memory.yml  
**Session file:** examples/memory.yml

**Description:**  
`E_batch(v) = -β_inv * Q( sum( F( β * InvDistSqBatch(M, v) ), axis=0))` expands to:

```
-(1/β) * log( sum( exp( β * (-||m - v||²) ), axis=0 ) )
```

This is exactly the log-sum-exp pattern. `scipy.special.logsumexp` computes this in a numerically stable way (avoiding overflow for large β) and is typically faster than the explicit `log(sum(exp(...)))` chain because it can use the max-shift trick internally.

**Optimized expression (requires adding `logsumexp` to the equation namespace whitelist):**
```python
E_batch(v) = β_inv * logsumexp(-β * InvDistSqBatch(M, v), axis=0)
```

Note the sign flip: `InvDistSqBatch` returns negative squared distances, so the signs work out.

**Blocker:** `logsumexp` is not currently in `build_equation_namespace()`. Needs to be added to `namespace.py`.
