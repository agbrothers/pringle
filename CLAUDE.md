## PRINGLE AGENT DOCUMENTATION

**Version 0.0.0**


## OVERVIEW
Pringle is an open-source, python-native 3D scientific plotting tool for visualizing surfaces, bringing dynamical systems to life, and whatever else the user can dream up. The `pringle/` package is fully implemented and actively being developed. Design is documented in `design-docs/` (20 docs including backlogs, see names below). 

**Why:** Existing interactive plotting tools, like Desmos 3D, are great but limited to their own expression language and have no Python ecosystem integration. Pringle brings the same UX to Python/numpy/scipy data structures.

**How to apply:** When resuming work, read `design-docs/05-architecture-decisions.md` for locked choices and check open GitHub Issues (`gh issue list`) for current open work.


## ROLES
You are assigned one of the following 3 roles: developer, planner, or profiler. If you have not been assigned a role, or if details regarding your role has been lost to compaction or otherwise appear ambiguous, you must ask the user to re-verify before proceeding. This is critically important to prevent stepping on the toes of other team members. Once assigned, please read the corresponding role description markdown file in /design-docs/roles. The planner role uses `gh issue` commands to file and read issues rather than editing markdown backlog files (see `design-docs/roles/planner.md`).


## GENERAL
- DO NOT BE A SYCOPHANT. Provide direct and objective feedback. Flattery is not helpful and, in fact, can be actively detrimental if it masks important critical feedback. 
- Review the relevant design-docs there when in need of context and before making assumptions or major changes. 
- When designs or code changes, always update the relevant design-docs to capture the difference. Do not update the docs if the user has not been consulted or did not sign off on the change. 
- When resuming work, check open GitHub Issues (`gh issue list`) in addition to the architecture decisions doc.


## DEVELOPMENT
- Keep changes minimal and focused. 
- Prefer modifying existing code over introducing abstractions. 
- Match surrounding coding sytle, naming conventions, and comments. 
- Code should be both concise and readable for new developers. 
- Minimizing context length is important where practical. Developers should not need to crawl across multiple files to track down a distributed implementation unless it cannot be avoided. 
- Use type hints for new or changed functions. 
- Add tests for bug fixes. 


## ENVIRONMENT
- Use the local uv venv `source .venv/bin/activate`. 
- If a required/desired package is missing, ask the user to install it for you. 


## Locked Technology Choices
- GPU/rendering: **pygfx + wgpu-py**
- UI framework: **PyQt6**
- Session format: **YAML**
- Evaluation: CPU numpy vectorized + buffer re-upload (v1); WGSL compute shaders deferred to v2 (see FEAT-037)


## Key Architecture Decisions
- **Unified cell list** — all cell types (equation, slider, folder, comment) live in one scrollable `CellListWidget`; there is no separate data panel
- **Data mode on `CellWidget`** — equation cells that produce scatter/curve arrays gain a stale indicator and `→` run button; `DataCellWidget` is a zombie class being phased out (BUG-030)
- **Unified DAG** across all cells; evaluation order is topological, not visual
- Magic variables (`z`, `y`, `xyz`, `points`) are renderer-local — NEVER exported to shared namespace
- Data-mode cells re-evaluate reactively on upstream parameter changes (slider animation, upstream cell edits), identical to non-data equation cells; text edits to the cell or its sub-cells fire `_mark_data_stale` (orange stale dot) instead of the eager debounce path; `→` button resamples (clears pinned RNG state, triggers full rebuild)
- Recurrence loop index: user sees `n`, internally renamed to `_pringle_loop_n` via AST
- Piecewise: `z = [f, g, h]` list syntax + N condition sub-cells → `np.select`
- `f(x,y) = expr` preprocessed to lambda; auto-renders as surface
- Boot sequence: load YAML (two-pass: cells then folder membership) → restore RNG states → single `_rebuild_namespace()` → first render; no separate "Run All data" step
- Security: explicit numpy/scipy whitelist + `__builtins__={}` + AST safety check (equation cells); no AST check for data-mode cells; `random` in namespace is `numpy.random` (not stdlib)
- Transparency: `alpha_mode="weighted_blend"` (WBOIT) when `opacity < 1.0` — order-independent, handles self-overlapping surfaces
- WASD panning is camera-relative (not world-space); forward = camera-to-target projected onto XY; Space/Shift remain world ±Z
- Session `view` block persists camera position, orbit target, and all overlay toggle states (axes, bbox, crosshair, shadow, light bg)
- All `CellStyle` fields are persisted to YAML (color, opacity, line_width, point_size, colormap, colormap_reversed, scatter_render_mode); sizes are world-space units


## Design Docs
- `01` Desmos 3D overview
- `02` GPU rendering options + WASD implementation
- `03` Expression evaluation + security model
- `04` Animation and time variation
- `05` Architecture decisions (master decisions table)
- `06` Panel architecture + unified DAG *(updated 2026-05-22)*
- `07` Cell types and blocks
- `08` Visual styling (CellStyle dataclass) *(updated 2026-05-22)*
- `09` Processing pipeline
- `10` Session YAML format *(updated 2026-05-22)*
- `11` Recurrence relations
- `12` User input and interaction *(updated 2026-05-22)*
- `13` Development plan (12 phases, PNG frame capture testing strategy)
- `14` Namespace reference (all whitelisted names, excluded builtins, rationale)
- `20` Profiling SOP

**Note:** Docs 15–19 removed 2026-05-24; active issue tracking on GitHub Issues. See `gh issue list` or https://github.com/agbrothers/pringle/issues.
