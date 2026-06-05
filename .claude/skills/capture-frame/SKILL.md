---
name: capture-frame
description: Headlessly render a Pringle scene to a PNG and assert it's visually valid (offscreen frame-capture test). Use when verifying renderer output, adding a visual regression test, checking a surface/scatter/curve renders correctly, or generating a reference frame.
---

# Capture a Frame (Headless Visual Test)

Canonical strategy: the "PNG Frame Capture Strategy" section of [design-docs/13](../../../design-docs/13-development-plan.md). Existing tests live in [tests/test_rendering.py](../../../tests/test_rendering.py); frames and references in [tests/frames/](../../../tests/frames/).

Works headlessly (no display) and inside pytest. Activate the venv first: `source .venv/bin/activate`.

## Render → PNG

```python
import gfx, imageio
renderer = gfx.WgpuRenderer(gfx.offscreen_target((800, 600)))
renderer.render(scene, camera)
frame = renderer.target.read()          # numpy (H, W, 4) uint8
imageio.imwrite("tests/frames/<name>.png", frame)
```

Match the actual offscreen-render helper used in `tests/test_rendering.py` rather than hand-rolling — reuse the existing pipeline.

## Assertions (what a valid frame must satisfy)

1. **Not all black** — the renderer produced output.
2. **Not a single flat color** — the mesh is visible, not degenerate.
3. **Optional pixel regression** — compare against a checked-in reference under `tests/frames/references/`. Generate the reference once, commit it, then diff future runs against it.

## Workflow

1. Build the scene (evaluator → mesh → scene/camera), reusing the test helpers.
2. Render offscreen and write the PNG to `tests/frames/<name>.png`.
3. Run the not-black / not-flat assertions; add a reference-diff if the frame should be pixel-stable.
4. Visually inspect the PNG, then either commit it as a reference or note expected appearance in the test.

## Notes

- wgpu uploads lazily — geometry isn't on the GPU until the first `render()` call, so read back *after* rendering.
- Keep frame size and camera deterministic so reference diffs are stable across runs.
