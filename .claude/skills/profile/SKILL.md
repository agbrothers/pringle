---
name: profile
description: Run Pringle's profiling SOP and report PASS/FAIL against the 33 ms / 30 fps frame budget. Use when asked to profile, benchmark, check performance, find a bottleneck, or verify a perf fix hasn't regressed (slider animation, cell rebuild, recurrence, surface geometry).
---

# Profile Pringle

Canonical procedure: [design-docs/20-profiling-sop.md](../../../design-docs/20-profiling-sop.md). Read it before a full session — this skill is the quickstart + trigger, not a replacement.

**Target:** ≥ 30 fps at n=128, i.e. ≤ 33 ms total per animation frame. The benchmark prints a PASS/FAIL line against this; that line is the definition of done.

## Quickstart

Activate the venv first: `source .venv/bin/activate`.

```bash
# Slider animation pipeline (surface rendering)
python tests/bench_slider_animation.py --n 128 --frames 100

# Cell-panel full rebuild (cell add/remove/edit lag — PERF-016 context)
python tests/bench_cell_rebuild.py --n 128 --frames 5

# Memory allocation audit (top allocation sites)
python tests/bench_slider_animation.py --n 128 --frames 100 --mem
```

## How to run a session

1. **Baseline.** Run the benchmark above and capture the numbers. Compare against the last recorded baseline in memory (`project_perf_baseline.md`) — flag any regression vs. those figures.
2. **Pick the depth you need** (full detail in doc 20):
   - First look / live flame graph → `py-spy record --pid <APP_PID> -o flame.svg --duration 30`
   - Ranked hot path → `python -m cProfile -s cumulative tests/bench_slider_animation.py --n 128 --frames 60`
   - Line-level → add `@profile` to target fns (do NOT commit), `kernprof -l -v ...`
3. **Report** mean ms, P95 ms, % budget, and PASS/FAIL. If P95 >> 2× mean, suspect a GC stall or thermal throttle — see the Pitfalls section in doc 20.
4. **Update the baseline** in `project_perf_baseline.md` after a confirmed improvement, with the new numbers and date.

## Filing findings

New bottlenecks become GitHub issues with the `performance` label (and a severity: `low`/`medium`/`high`). Add the `benchmark` label when the issue carries before/after numbers. See the `file-issue` skill for the template.

## Notes

- Always profile in the production Python/numpy (the uv venv), never a debug build — skews 2–5×.
- Warm up before the timed run (`--warmup N`) to avoid thermal-throttle noise on macOS laptops.
- Fix CPU layers before GPU; GPU is rarely the bottleneck at n=128.
