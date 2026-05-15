# Test Frames

PNG frames saved by each test phase. Inspect these visually to confirm rendering is correct.

| File | Phase | Expected |
|---|---|---|
| `phase1_surface.png` | 1 — GPU baseline | Blue Phong-shaded sin(x)*cos(y) surface, visible shading gradient |
| `phase1_line.png` | 1 — GPU baseline | Orange helix curve in 3D |
| `phase1_scatter.png` | 1 — GPU baseline | Yellow scatter points forming a sphere |
| `phase2_*.png` | 2 — Evaluation engine | Surfaces rendered from evaluated expressions |

## Regression Testing

Reference frames are stored in `references/`. After visual inspection, copy a frame here:

    cp tests/frames/phase1_surface.png tests/frames/references/phase1_surface.png

Tests compare new renders against references using mean absolute pixel difference < 2%.
