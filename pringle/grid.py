"""
Spatial grid management for expression evaluation.

Produces the (x, y), (u, v) meshgrids that are injected into cell
namespaces during evaluation.  Grid bounds and resolution are set from
the View Settings panel and stored in a GridConfig.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


@dataclass
class GridConfig:
    x_min: float = -5.0
    x_max: float =  5.0
    y_min: float = -5.0
    y_max: float =  5.0
    z_min: float = -5.0
    z_max: float =  5.0
    u_min: float = 0.0
    u_max: float = float(2 * np.pi)
    v_min: float = 0.0
    v_max: float = float(2 * np.pi)
    n: int = 64  # grid points per axis


@dataclass
class Grid:
    """Pre-computed meshgrids for a given GridConfig."""
    config: GridConfig
    x: np.ndarray   # (n, n) float32
    y: np.ndarray   # (n, n) float32
    u: np.ndarray   # (n, n) float32
    v: np.ndarray   # (n, n) float32
    x1d: np.ndarray  # (n,)   float32 — for 2D curve evaluation
    y1d: np.ndarray  # (n,)


def make_grid(config: GridConfig | None = None) -> Grid:
    """Build a Grid from a GridConfig (default config if not provided)."""
    if config is None:
        config = GridConfig()
    n = config.n

    x1d = np.linspace(config.x_min, config.x_max, n, dtype=np.float32)
    y1d = np.linspace(config.y_min, config.y_max, n, dtype=np.float32)
    u1d = np.linspace(config.u_min, config.u_max, n, dtype=np.float32)
    v1d = np.linspace(config.v_min, config.v_max, n, dtype=np.float32)

    x, y = np.meshgrid(x1d, y1d, indexing="xy")
    u, v = np.meshgrid(u1d, v1d, indexing="xy")

    return Grid(config=config, x=x, y=y, u=u, v=v, x1d=x1d, y1d=y1d)


def grid_vars(grid: Grid, t: float = 0.0) -> dict:
    """
    Return the dict of grid variables to inject into a cell's local namespace.

    These sit at the highest priority layer (Layer 5) in the shared
    namespace stack — they cannot be shadowed by user expressions.
    """
    return {
        "x": grid.x,
        "y": grid.y,
        "u": grid.u,
        "v": grid.v,
        "t": np.float32(t),
    }
