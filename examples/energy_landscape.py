"""Generalized Associative Memory energy landscape demo.

Energy function:
    E(x, y) = -log( sum_mu exp(-beta * ||z - xi_mu||^2) )

where xi_mu are the stored attractor patterns.  The surface has a local
minimum at each attractor, and the gradient-descent trajectory shows how a
particle rolls downhill toward the nearest attractor.

Run:
    uv run python examples/energy_landscape.py
"""
import numpy as np
import pringle as pr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(42)
RANGE = (-4, 4)


def _sample_attractors(n: int, scale: float = 2.5) -> np.ndarray:
    return RNG.uniform(-scale, scale, size=(n, 2))


def energy(X, Y, attractors, beta=1.0, **_):
    """Associative memory energy landscape (scalar or meshgrid)."""
    attractors = np.array(attractors, dtype=float)
    # Broadcast: (H, W, 1) - (1, 1, N)
    dx = X[..., np.newaxis] - attractors[:, 0]
    dy = Y[..., np.newaxis] - attractors[:, 1]
    dists_sq = dx**2 + dy**2
    log_sum = np.log(np.sum(np.exp(-beta * dists_sq), axis=-1) + 1e-9)
    return -log_sum


def _energy_scalar(x, y, attractors, beta=1.0):
    """Single-point energy evaluation."""
    return float(energy(np.array([[x]]), np.array([[y]]), attractors, beta)[0, 0])


def gradient_descent(x0=0.0, y0=0.0, attractors=None, beta=1.0, n_steps=80, lr=0.05, **_):
    """Return trajectory as (N+1, 3) array."""
    if attractors is None:
        attractors = _sample_attractors(5)
    attractors = np.array(attractors, dtype=float)
    x, y = float(x0), float(y0)
    traj = [[x, y, _energy_scalar(x, y, attractors, beta)]]
    eps = 1e-4
    for _ in range(int(n_steps)):
        gx = (_energy_scalar(x + eps, y, attractors, beta)
              - _energy_scalar(x - eps, y, attractors, beta)) / (2 * eps)
        gy = (_energy_scalar(x, y + eps, attractors, beta)
              - _energy_scalar(x, y - eps, attractors, beta)) / (2 * eps)
        x -= lr * gx
        y -= lr * gy
        traj.append([x, y, _energy_scalar(x, y, attractors, beta)])
    return np.array(traj)


def attractors_3d(attractors=None, beta=1.0, **_):
    """Attractor points lifted onto the energy surface."""
    if attractors is None:
        attractors = _sample_attractors(5)
    pts = np.array(attractors, dtype=float)
    zs = [_energy_scalar(p[0], p[1], pts, beta) for p in pts]
    return np.column_stack([pts, zs])


def start_point(x0=0.0, y0=0.0, attractors=None, beta=1.0, **_):
    """The current initial-condition marker on the surface."""
    if attractors is None:
        attractors = _sample_attractors(5)
    z = _energy_scalar(float(x0), float(y0), np.array(attractors, dtype=float), beta)
    return [[float(x0), float(y0), z]]


def gradient_arrow(x0=0.0, y0=0.0, attractors=None, beta=1.0, **_):
    """Negative-gradient arrow at the start point (direction of steepest descent)."""
    if attractors is None:
        attractors = _sample_attractors(5)
    attractors = np.array(attractors, dtype=float)
    eps = 1e-4
    z0 = _energy_scalar(float(x0), float(y0), attractors, beta)
    gx = (_energy_scalar(x0 + eps, y0, attractors, beta)
          - _energy_scalar(x0 - eps, y0, attractors, beta)) / (2 * eps)
    gy = (_energy_scalar(x0, y0 + eps, attractors, beta)
          - _energy_scalar(x0, y0 - eps, attractors, beta)) / (2 * eps)
    origin = np.array([float(x0), float(y0), z0])
    direction = np.array([-gx, -gy, 0.0]) * 0.4  # scale for visibility
    return origin, direction


# ---------------------------------------------------------------------------
# Build figure
# ---------------------------------------------------------------------------

initial_attractors = _sample_attractors(6)
N_DEFAULT = 6

fig = pr.Figure3D(title="Associative Memory Energy Landscape")

fig.add_surface(
    "Energy Surface",
    fn=energy,
    x_range=RANGE,
    y_range=RANGE,
    resolution=60,
    colorscale="Blues",
    opacity=0.80,
)

fig.add_scatter3d(
    "Attractors",
    fn=attractors_3d,
    color="tomato",
    size=6,
    opacity=1.0,
)

fig.add_scatter3d(
    "Start Point",
    fn=start_point,
    color="#00ff88",
    size=9,
    opacity=1.0,
    draggable=True,  # enables 📍 Place Start Point button
)

fig.add_curve3d(
    "Trajectory",
    fn=gradient_descent,
    color="#ffaa00",
    width=4,
    animate=True,   # revealed frame-by-frame during animation
)

fig.add_vector3d(
    "Gradient Arrow",
    fn=gradient_arrow,
    color="#00ccff",
    width=4,
    size=10,
)

# --- Sliders ---
fig.add_slider("beta",    label="β  (sharpness)",     min=0.1, max=5.0,  default=1.0,  step=0.05)
fig.add_slider("n_steps", label="Steps (time horizon)", min=10,  max=200,  default=80,   step=5)
fig.add_slider("lr",      label="Learning rate",       min=0.005, max=0.2, default=0.05, step=0.005)

# --- Resample button ---
def resample(n_attractors=N_DEFAULT, **_):
    return {"attractors": RNG.uniform(-2.5, 2.5, size=(max(1, int(n_attractors)), 2))}

fig.add_slider("n_attractors", label="N attractors", min=1, max=20, default=N_DEFAULT, step=1)
fig.add_button("🎲  Resample Attractors", resample, color="info")

# --- Animation ---
fig.set_animation(max_frames=200, fps=15.0)

# Seed initial state
fig._state_defaults["attractors"] = initial_attractors

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fig.launch(port=8050, debug=True)
