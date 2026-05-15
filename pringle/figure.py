from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Style / control descriptors
# ---------------------------------------------------------------------------

@dataclass
class ElementStyle:
    color: Optional[str] = None
    opacity: float = 1.0
    size: float = 5.0
    width: float = 2.0
    colorscale: str = "Blues"
    showscale: bool = False


@dataclass
class SliderParam:
    key: str
    label: str
    min: float
    max: float
    default: float
    step: float


@dataclass
class ButtonAction:
    label: str
    callback: Callable  # (**state) -> dict of state updates
    color: str = "secondary"


@dataclass
class AnimationConfig:
    max_frames: int = 100
    fps: float = 10.0


# ---------------------------------------------------------------------------
# Element base + 3-D elements
# ---------------------------------------------------------------------------

class Element:
    def __init__(self, name: str, fn: Callable, style: Optional[ElementStyle] = None, visible: bool = True):
        self.name = name
        self.fn = fn
        self.style = style or ElementStyle()
        self.visible = visible

    def get_trace(self, state: dict):
        raise NotImplementedError


class Surface3D(Element):
    """fn(X, Y, **state) -> Z  where X, Y are numpy meshgrids."""

    def __init__(self, name, fn, x_range=(-3, 3), y_range=(-3, 3), resolution=50, **kwargs):
        super().__init__(name, fn, **kwargs)
        self.x_range = x_range
        self.y_range = y_range
        self.resolution = resolution

    def get_trace(self, state):
        import plotly.graph_objects as go

        x = np.linspace(*self.x_range, self.resolution)
        y = np.linspace(*self.y_range, self.resolution)
        X, Y = np.meshgrid(x, y)
        Z = self.fn(X, Y, **state)
        return go.Surface(
            x=X, y=Y, z=Z,
            colorscale=self.style.colorscale,
            opacity=self.style.opacity,
            showscale=self.style.showscale,
            visible=self.visible,
            name=self.name,
            hovertemplate="x: %{x:.3f}<br>y: %{y:.3f}<br>z: %{z:.3f}<extra>%{fullData.name}</extra>",
        )


class Scatter3D(Element):
    """fn(**state) -> array-like of shape (N, 3)."""

    def __init__(self, name, fn, draggable=False, **kwargs):
        super().__init__(name, fn, **kwargs)
        self.draggable = draggable

    def get_trace(self, state):
        import plotly.graph_objects as go

        pts = np.atleast_2d(np.array(self.fn(**state), dtype=float))
        return go.Scatter3d(
            x=pts[:, 0], y=pts[:, 1], z=pts[:, 2],
            mode="markers",
            marker=dict(color=self.style.color, size=self.style.size, opacity=self.style.opacity),
            visible=self.visible,
            name=self.name,
        )


class Curve3D(Element):
    """fn(**state) -> array-like of shape (N, 3). Set animate=True to reveal frame-by-frame."""

    def __init__(self, name, fn, animate=False, **kwargs):
        super().__init__(name, fn, **kwargs)
        self.animate = animate

    def get_trace(self, state):
        import plotly.graph_objects as go

        pts = np.array(self.fn(**state), dtype=float)
        if pts.ndim == 1:
            pts = pts[np.newaxis, :]
        if self.animate:
            frame = int(state.get("_frame", len(pts) - 1))
            pts = pts[: frame + 1]
        if len(pts) == 0:
            return go.Scatter3d(x=[], y=[], z=[], mode="lines", name=self.name, visible=self.visible)
        return go.Scatter3d(
            x=pts[:, 0], y=pts[:, 1], z=pts[:, 2],
            mode="lines",
            line=dict(color=self.style.color, width=self.style.width),
            opacity=self.style.opacity,
            visible=self.visible,
            name=self.name,
        )


class Vector3D(Element):
    """fn(**state) -> (origin, direction)  each shape (3,)."""

    def get_trace(self, state):
        import plotly.graph_objects as go

        origin, direction = self.fn(**state)
        origin = np.array(origin, dtype=float)
        direction = np.array(direction, dtype=float)
        tip = origin + direction
        return go.Scatter3d(
            x=[origin[0], tip[0]],
            y=[origin[1], tip[1]],
            z=[origin[2], tip[2]],
            mode="lines+markers",
            line=dict(color=self.style.color, width=self.style.width),
            marker=dict(size=[2, self.style.size], color=self.style.color),
            opacity=self.style.opacity,
            visible=self.visible,
            name=self.name,
        )


# ---------------------------------------------------------------------------
# 2-D elements
# ---------------------------------------------------------------------------

class Heatmap2D(Element):
    """fn(X, Y, **state) -> Z  where X, Y are numpy meshgrids."""

    def __init__(self, name, fn, x_range=(-3, 3), y_range=(-3, 3), resolution=60, **kwargs):
        super().__init__(name, fn, **kwargs)
        self.x_range = x_range
        self.y_range = y_range
        self.resolution = resolution

    def get_trace(self, state):
        import plotly.graph_objects as go

        x = np.linspace(*self.x_range, self.resolution)
        y = np.linspace(*self.y_range, self.resolution)
        X, Y = np.meshgrid(x, y)
        Z = self.fn(X, Y, **state)
        return go.Heatmap(
            x=x, y=y, z=Z,
            colorscale=self.style.colorscale,
            opacity=self.style.opacity,
            visible=self.visible,
            name=self.name,
            showscale=self.style.showscale,
        )


class Scatter2D(Element):
    """fn(**state) -> array-like of shape (N, 2)."""

    def get_trace(self, state):
        import plotly.graph_objects as go

        pts = np.atleast_2d(np.array(self.fn(**state), dtype=float))
        return go.Scatter(
            x=pts[:, 0], y=pts[:, 1],
            mode="markers",
            marker=dict(color=self.style.color, size=self.style.size, opacity=self.style.opacity),
            visible=self.visible,
            name=self.name,
        )


class Curve2D(Element):
    """fn(**state) -> array-like of shape (N, 2). Set animate=True to reveal frame-by-frame."""

    def __init__(self, name, fn, animate=False, **kwargs):
        super().__init__(name, fn, **kwargs)
        self.animate = animate

    def get_trace(self, state):
        import plotly.graph_objects as go

        pts = np.array(self.fn(**state), dtype=float)
        if self.animate:
            frame = int(state.get("_frame", len(pts) - 1))
            pts = pts[: frame + 1]
        return go.Scatter(
            x=pts[:, 0], y=pts[:, 1],
            mode="lines",
            line=dict(color=self.style.color, width=self.style.width),
            opacity=self.style.opacity,
            visible=self.visible,
            name=self.name,
        )


# ---------------------------------------------------------------------------
# Figure3D
# ---------------------------------------------------------------------------

class Figure3D:
    """Interactive 3-D plot powered by Plotly + Dash.

    Usage::

        fig = Figure3D(title="My Plot")
        fig.add_surface("Surface", fn=my_fn, x_range=(-3, 3), y_range=(-3, 3))
        fig.add_slider("beta", label="β", min=0.1, max=5.0, default=1.0, step=0.1)
        fig.launch()
    """

    def __init__(self, title: str = "Pringle", config_path: Optional[str] = None):
        self.title = title
        self.config_path = config_path
        self.elements: list[Element] = []
        self.sliders: list[SliderParam] = []
        self.buttons: list[ButtonAction] = []
        self.animation: Optional[AnimationConfig] = None
        # x0/y0 are always in state so click-to-place always works
        self._state_defaults: dict = {"x0": 0.0, "y0": 0.0}
        self._has_draggable: bool = False

        if config_path:
            self._apply_config(config_path)

    # --- element builders ---

    def add_surface(
        self, name: str, fn: Callable, *,
        x_range=(-3, 3), y_range=(-3, 3), resolution: int = 50,
        colorscale: str = "Blues", opacity: float = 0.85,
        showscale: bool = False, visible: bool = True,
    ) -> "Figure3D":
        style = ElementStyle(colorscale=colorscale, opacity=opacity, showscale=showscale)
        self.elements.append(Surface3D(name, fn, x_range, y_range, resolution, style=style, visible=visible))
        return self

    def add_scatter3d(
        self, name: str, fn: Callable, *,
        color: str = "red", size: float = 5, opacity: float = 1.0,
        visible: bool = True, draggable: bool = False,
    ) -> "Figure3D":
        style = ElementStyle(color=color, size=size, opacity=opacity)
        elem = Scatter3D(name, fn, draggable=draggable, style=style, visible=visible)
        self.elements.append(elem)
        if draggable:
            self._has_draggable = True
        return self

    def add_curve3d(
        self, name: str, fn: Callable, *,
        color: str = "orange", width: float = 3, opacity: float = 1.0,
        visible: bool = True, animate: bool = False,
    ) -> "Figure3D":
        style = ElementStyle(color=color, width=width, opacity=opacity)
        self.elements.append(Curve3D(name, fn, animate=animate, style=style, visible=visible))
        return self

    def add_vector3d(
        self, name: str, fn: Callable, *,
        color: str = "lime", width: float = 4, size: float = 8,
        opacity: float = 1.0, visible: bool = True,
    ) -> "Figure3D":
        style = ElementStyle(color=color, width=width, size=size, opacity=opacity)
        self.elements.append(Vector3D(name, fn, style=style, visible=visible))
        return self

    # --- control builders ---

    def add_slider(
        self, key: str, *,
        label: Optional[str] = None,
        min: float = 0, max: float = 1, default: float = 0.5, step: float = 0.01,
    ) -> "Figure3D":
        self.sliders.append(SliderParam(key=key, label=label or key, min=min, max=max, default=default, step=step))
        self._state_defaults[key] = default
        return self

    def add_button(self, label: str, callback: Callable, *, color: str = "secondary") -> "Figure3D":
        """callback(**state) -> dict of state updates."""
        self.buttons.append(ButtonAction(label=label, callback=callback, color=color))
        return self

    def set_animation(self, *, max_frames: int = 100, fps: float = 10.0) -> "Figure3D":
        self.animation = AnimationConfig(max_frames=max_frames, fps=fps)
        return self

    # --- rendering ---

    def get_figure(self, state: dict, axis_ranges: dict | None = None):
        """Render the figure.

        axis_ranges: optional dict mapping axis name to (min, max) tuple,
            e.g. {"x": (-3, 3), "y": (-3, 3), "z": (-5, 0)}.
        """
        import plotly.graph_objects as go

        traces = []
        for elem in self.elements:
            try:
                traces.append(elem.get_trace(state))
            except Exception as exc:
                print(f"[pringle] '{elem.name}' error: {exc}")

        _ax_base = dict(gridcolor="#2a3050", color="#aaa",
                        showbackground=True, backgroundcolor="#0d1117")
        xax = dict(**_ax_base)
        yax = dict(**_ax_base)
        zax = dict(**_ax_base)
        if axis_ranges:
            for ax, rng in axis_ranges.items():
                if rng and rng[0] is not None and rng[1] is not None and rng[0] < rng[1]:
                    target = {"x": xax, "y": yax, "z": zax}.get(ax)
                    if target is not None:
                        target.update(range=list(rng), autorange=False)

        fig = go.Figure(data=traces)
        fig.update_layout(
            title=dict(text=self.title, font=dict(color="white", size=16)),
            scene=dict(
                bgcolor="#0d1117",
                aspectmode="auto",
                uirevision="constant",   # must be set at scene level for 3-D camera
                xaxis=xax,
                yaxis=yax,
                zaxis=zax,
            ),
            margin=dict(l=0, r=0, t=40, b=0),
            paper_bgcolor="#0d1117",
            font=dict(color="white"),
            legend=dict(bgcolor="rgba(20,20,40,0.85)", font=dict(color="white", size=12),
                        bordercolor="#333", borderwidth=1),
            uirevision="constant",
        )
        return fig

    def launch(self, *, port: int = 8050, debug: bool = True, host: str = "127.0.0.1") -> None:
        from ._app import build_app
        app = build_app(self)
        print(f"\n  Pringle → http://{host}:{port}\n")
        app.run(host=host, port=port, debug=debug)

    # --- config ---

    def _apply_config(self, path: str) -> None:
        from .config import load_config
        cfg = load_config(path)
        for slider in self.sliders:
            if slider.key in cfg.get("params", {}):
                slider.default = cfg["params"][slider.key]
        self._state_defaults.update(cfg.get("state", {}))

    def save_config(self, path: str) -> None:
        from .config import save_config
        cfg = {
            "params": {s.key: s.default for s in self.sliders},
            "state": {k: v for k, v in self._state_defaults.items() if k not in ("x0", "y0")},
        }
        save_config(path, cfg)


# ---------------------------------------------------------------------------
# Figure2D
# ---------------------------------------------------------------------------

class Figure2D:
    """Interactive 2-D plot powered by Plotly + Dash.

    Usage::

        fig = Figure2D(title="My 2D Plot")
        fig.add_heatmap("Heat", fn=my_fn, x_range=(-3, 3), y_range=(-3, 3))
        fig.add_slider("beta", label="β", min=0.1, max=5.0, default=1.0, step=0.1)
        fig.launch()
    """

    def __init__(self, title: str = "Pringle 2D", config_path: Optional[str] = None):
        self.title = title
        self.config_path = config_path
        self.elements: list[Element] = []
        self.sliders: list[SliderParam] = []
        self.buttons: list[ButtonAction] = []
        self.animation: Optional[AnimationConfig] = None
        self._state_defaults: dict = {"x0": 0.0, "y0": 0.0}
        self._has_draggable: bool = False

        if config_path:
            self._apply_config(config_path)

    def add_heatmap(
        self, name: str, fn: Callable, *,
        x_range=(-3, 3), y_range=(-3, 3), resolution: int = 60,
        colorscale: str = "Blues", opacity: float = 1.0,
        showscale: bool = True, visible: bool = True,
    ) -> "Figure2D":
        style = ElementStyle(colorscale=colorscale, opacity=opacity, showscale=showscale)
        self.elements.append(Heatmap2D(name, fn, x_range, y_range, resolution, style=style, visible=visible))
        return self

    def add_scatter2d(
        self, name: str, fn: Callable, *,
        color: str = "red", size: float = 8, opacity: float = 1.0, visible: bool = True,
    ) -> "Figure2D":
        style = ElementStyle(color=color, size=size, opacity=opacity)
        self.elements.append(Scatter2D(name, fn, style=style, visible=visible))
        return self

    def add_curve2d(
        self, name: str, fn: Callable, *,
        color: str = "orange", width: float = 2, opacity: float = 1.0,
        visible: bool = True, animate: bool = False,
    ) -> "Figure2D":
        style = ElementStyle(color=color, width=width, opacity=opacity)
        self.elements.append(Curve2D(name, fn, animate=animate, style=style, visible=visible))
        return self

    def add_slider(
        self, key: str, *,
        label: Optional[str] = None,
        min: float = 0, max: float = 1, default: float = 0.5, step: float = 0.01,
    ) -> "Figure2D":
        self.sliders.append(SliderParam(key=key, label=label or key, min=min, max=max, default=default, step=step))
        self._state_defaults[key] = default
        return self

    def add_button(self, label: str, callback: Callable, *, color: str = "secondary") -> "Figure2D":
        self.buttons.append(ButtonAction(label=label, callback=callback, color=color))
        return self

    def set_animation(self, *, max_frames: int = 100, fps: float = 10.0) -> "Figure2D":
        self.animation = AnimationConfig(max_frames=max_frames, fps=fps)
        return self

    def get_figure(self, state: dict, axis_ranges: dict | None = None):
        import plotly.graph_objects as go

        traces = []
        for elem in self.elements:
            try:
                traces.append(elem.get_trace(state))
            except Exception as exc:
                print(f"[pringle] '{elem.name}' error: {exc}")

        xax = dict(gridcolor="#2a3050", color="#aaa", zerolinecolor="#444")
        yax = dict(gridcolor="#2a3050", color="#aaa", zerolinecolor="#444")
        if axis_ranges:
            for ax, rng in axis_ranges.items():
                if rng and rng[0] is not None and rng[1] is not None and rng[0] < rng[1]:
                    target = {"x": xax, "y": yax}.get(ax)
                    if target is not None:
                        target.update(range=list(rng), autorange=False)

        fig = go.Figure(data=traces)
        fig.update_layout(
            title=dict(text=self.title, font=dict(color="white", size=16)),
            margin=dict(l=50, r=20, t=50, b=50),
            paper_bgcolor="#0d1117",
            plot_bgcolor="#131b2e",
            font=dict(color="white"),
            xaxis=xax,
            yaxis=yax,
            legend=dict(bgcolor="rgba(20,20,40,0.85)", font=dict(color="white", size=12),
                        bordercolor="#333", borderwidth=1),
            uirevision="constant",
        )
        return fig

    def launch(self, *, port: int = 8050, debug: bool = True, host: str = "127.0.0.1") -> None:
        from ._app import build_app
        app = build_app(self)
        print(f"\n  Pringle 2D → http://{host}:{port}\n")
        app.run(host=host, port=port, debug=debug)

    def _apply_config(self, path: str) -> None:
        from .config import load_config
        cfg = load_config(path)
        for slider in self.sliders:
            if slider.key in cfg.get("params", {}):
                slider.default = cfg["params"][slider.key]
        self._state_defaults.update(cfg.get("state", {}))

    def save_config(self, path: str) -> None:
        from .config import save_config
        cfg = {
            "params": {s.key: s.default for s in self.sliders},
            "state": {k: v for k, v in self._state_defaults.items() if k not in ("x0", "y0")},
        }
        save_config(path, cfg)
