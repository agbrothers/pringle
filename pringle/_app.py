"""Internal Dash app builder — not part of the public API."""
from __future__ import annotations

import numpy as np


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize(val):
    if isinstance(val, np.ndarray):
        return val.tolist()
    if isinstance(val, np.generic):
        return val.item()
    return val


def _serialize_state(state: dict) -> dict:
    return {k: _serialize(v) for k, v in state.items()}


def _deserialize_state(state: dict) -> dict:
    result = {}
    for k, v in state.items():
        if isinstance(v, list) and len(v) > 0 and isinstance(v[0], list):
            result[k] = np.array(v)
        else:
            result[k] = v
    return result


def _is_3d(figure) -> bool:
    from .figure import Figure3D
    return isinstance(figure, Figure3D)


# ---------------------------------------------------------------------------
# JavaScript — WASD / Space / Shift camera panning
#
# Fix: read camera directly from graphDiv._fullLayout.scene.camera on each
# RAF tick instead of tracking it via a plotly_relayout event listener.
# This avoids the timing problem where .on() doesn't exist yet, and always
# gives the current camera including any mouse-driven rotation.
# ---------------------------------------------------------------------------

_KEYBOARD_CAMERA_JS = """
function(pageLoad) {
    var P = window._pringle = window._pringle || {};
    if (P.keyboardSetup) return window.dash_clientside.no_update;
    P.keyboardSetup = true;

    /* Key state — skip when focus is inside a text field */
    P.keys = {};
    var skipTags = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
    document.addEventListener('keydown', function(e) {
        if (skipTags.has(e.target.tagName)) return;
        P.keys[e.key] = true;
        if (e.key === ' ') e.preventDefault();
    });
    document.addEventListener('keyup', function(e) {
        delete P.keys[e.key];
    });

    /* Read the current camera directly from Plotly's internal layout.
       This is always up-to-date: Plotly updates _fullLayout.scene.camera
       after both mouse interaction and Plotly.relayout() calls. */
    function getCamera() {
        var el = document.getElementById('main-graph');
        if (el && el._fullLayout && el._fullLayout.scene) {
            var c = el._fullLayout.scene.camera;
            if (c && c.eye) return c;
        }
        return {eye:{x:1.25,y:1.25,z:1.25}, center:{x:0,y:0,z:0}, up:{x:0,y:0,z:1}};
    }

    /* requestAnimationFrame loop */
    function tick() {
        if (Object.keys(P.keys).length > 0) {
            var cam = getCamera();
            var spd = 0.04;

            /* Forward = eye→center projected onto the horizontal XY plane */
            var fx = cam.center.x - cam.eye.x;
            var fy = cam.center.y - cam.eye.y;
            var fl = Math.sqrt(fx*fx + fy*fy);
            if (fl > 1e-4) { fx /= fl; fy /= fl; }
            else            { fx = -0.707; fy = -0.707; }

            /* Right = forward × world-up (Z): (fy, -fx, 0) */
            var rx = fy, ry = -fx;

            var dx=0, dy=0, dz=0;
            if (P.keys['w']||P.keys['W']) { dx+=fx*spd; dy+=fy*spd; }
            if (P.keys['s']||P.keys['S']) { dx-=fx*spd; dy-=fy*spd; }
            if (P.keys['a']||P.keys['A']) { dx-=rx*spd; dy-=ry*spd; }
            if (P.keys['d']||P.keys['D']) { dx+=rx*spd; dy+=ry*spd; }
            if (P.keys[' '])              { dz+=spd; }
            if (P.keys['Shift'])          { dz-=spd; }

            if (dx||dy||dz) {
                Plotly.relayout('main-graph', {'scene.camera': {
                    eye:    {x:cam.eye.x+dx,    y:cam.eye.y+dy,    z:cam.eye.z+dz},
                    center: {x:cam.center.x+dx, y:cam.center.y+dy, z:cam.center.z+dz},
                    up:     cam.up
                }});
            }
        }
        requestAnimationFrame(tick);
    }
    tick();
    return 'keyboard-ready';
}
"""


# ---------------------------------------------------------------------------
# JavaScript — fully clientside animation
#
# Fix 1 (play button broken): replaced window.dash_clientside.callback_context
# .triggered (unreliable in Dash 4.x) with prev-value comparison — works in
# all Dash versions without relying on internal callback context APIs.
#
# Fix 2 (trajectory change detection): use traj-version-store (an integer
# counter) as the Input rather than traj-store itself.  traj-store is always
# a new JSON object so reference comparison is meaningless; the counter
# increments exactly once per main-callback fire.
#
# Argument order (must match the clientside_callback registration below):
#   0 play_n   1 pause_n  2 reset_n  3 fps_val  4 frame_scrub
#   5 traj_ver (Input — triggers on param change)
#   6 traj_data (State — actual trajectory, not a trigger)
#   7 max_frames (State — animation config)
# ---------------------------------------------------------------------------

_ANIMATION_JS = """
function(play_n, pause_n, reset_n, fps_val, frame_scrub, traj_ver, traj_data, max_frames) {
    var P = window._pringle = window._pringle || {};

    /* Detect what changed by comparing with stored previous values.
       Works regardless of Dash version; no callback_context needed. */
    var playClicked  = (play_n  || 0) > (P.pp  || 0);
    var pauseClicked = (pause_n || 0) > (P.pa  || 0);
    var resetClicked = (reset_n || 0) > (P.pr  || 0);
    var fpsChanged   = fps_val     !== P.pf  && fps_val     != null;
    var frameChanged = frame_scrub !== P.pfs && frame_scrub != null;
    var trajChanged  = (traj_ver  || 0) > (P.ptv || 0);

    P.pp  = play_n  || 0;
    P.pa  = pause_n || 0;
    P.pr  = reset_n || 0;
    P.pf  = fps_val;
    P.pfs = frame_scrub;
    P.ptv = traj_ver || 0;

    if (traj_data)        P.traj     = traj_data;
    if (max_frames != null) P.maxFrame = max_frames;
    if (fps_val)            P.fps      = fps_val;

    /* Slice the stored trajectory and restyle only that trace.
       Plotly.restyle() updates data arrays in-place without touching the
       WebGL scene or camera — rotation remains free during animation. */
    function showFrame(frame) {
        var el = document.getElementById('main-graph');
        if (!el || !el._fullLayout || !P.traj) return;
        Object.keys(P.traj).forEach(function(idxStr) {
            var traceIdx = parseInt(idxStr, 10);
            var pts = P.traj[idxStr];
            var end = Math.min((frame || 0) + 1, pts.length);
            var sl  = pts.slice(0, end);
            var upd = {
                x: [sl.map(function(p){ return p[0]; })],
                y: [sl.map(function(p){ return p[1]; })]
            };
            if (sl.length && sl[0].length > 2) {
                upd.z = [sl.map(function(p){ return p[2]; })];
            }
            Plotly.restyle('main-graph', upd, [traceIdx]);
        });
    }

    function startAnim() {
        if (P.animInterval) clearInterval(P.animInterval);
        var ms = Math.max(16, Math.round(1000 / (P.fps || 10)));
        P.animInterval = setInterval(function() {
            P.animFrame = ((P.animFrame || 0) + 1) % ((P.maxFrame || 100) + 1);
            showFrame(P.animFrame);
        }, ms);
    }

    /* Priority: reset > pause > play > fps change > traj change > scrub */
    if (resetClicked) {
        if (P.animInterval) { clearInterval(P.animInterval); P.animInterval = null; }
        P.animFrame = 0;
        showFrame(0);
        return window.dash_clientside.no_update;
    }
    if (pauseClicked) {
        if (P.animInterval) { clearInterval(P.animInterval); P.animInterval = null; }
        return window.dash_clientside.no_update;
    }
    if (playClicked) {
        startAnim();
        return window.dash_clientside.no_update;
    }
    if (fpsChanged && P.animInterval) {
        startAnim();
        return window.dash_clientside.no_update;
    }
    if (trajChanged) {
        /* Parameters changed: reset trajectory, restart if already playing */
        P.animFrame = 0;
        showFrame(0);
        if (P.animInterval) startAnim();
        return window.dash_clientside.no_update;
    }
    if (frameChanged && !P.animInterval) {
        /* Manual scrub — only acts when animation is not playing */
        P.animFrame = frame_scrub || 0;
        showFrame(P.animFrame);
    }

    return window.dash_clientside.no_update;
}
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_app(figure):
    import dash
    import dash_bootstrap_components as dbc

    app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.CYBORG],
        suppress_callback_exceptions=True,
        title="Pringle",
    )
    app.layout = _build_layout(figure)
    _register_callbacks(app, figure)
    return app


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def _section_header(text: str):
    from dash import html
    return html.Div(
        text,
        style={
            "color": "#4a5580",
            "fontSize": "10px",
            "fontWeight": "700",
            "letterSpacing": "1.5px",
            "textTransform": "uppercase",
            "marginTop": "22px",
            "marginBottom": "6px",
            "borderBottom": "1px solid #1e2740",
            "paddingBottom": "5px",
        },
    )


def _build_layout(figure):
    import dash_bootstrap_components as dbc
    from dash import html

    return dbc.Container(
        [
            dbc.Row(
                [
                    dbc.Col(
                        _build_sidebar(figure),
                        width=3,
                        style={
                            "overflowY": "auto",
                            "height": "100vh",
                            "backgroundColor": "#080e1a",
                            "padding": "16px 12px",
                            "borderRight": "1px solid #1e2740",
                        },
                    ),
                    dbc.Col(
                        _build_graph_panel(figure),
                        width=9,
                        style={"padding": "0"},
                    ),
                ],
                className="g-0",
            ),
        ],
        fluid=True,
        style={"backgroundColor": "#0d1117", "minHeight": "100vh"},
    )


def _build_sidebar(figure):
    from dash import dcc, html
    import dash_bootstrap_components as dbc

    is3d = _is_3d(figure)
    children = [
        html.Div(
            figure.title,
            style={
                "color": "white",
                "fontSize": "17px",
                "fontWeight": "700",
                "marginBottom": "18px",
                "paddingBottom": "12px",
                "borderBottom": "1px solid #1e2740",
            },
        ),
    ]

    # Layers
    if figure.elements:
        children.append(_section_header("Layers"))
        for i, elem in enumerate(figure.elements):
            children.append(
                dbc.Switch(
                    id=f"vis-{i}",
                    label=elem.name,
                    value=elem.visible,
                    style={"color": "#c0c8e0", "fontSize": "13px"},
                    className="mb-1",
                )
            )

    # Parameters
    if figure.sliders:
        children.append(_section_header("Parameters"))
        for param in figure.sliders:
            children.extend([
                html.Div(param.label,
                         style={"color": "#8890b0", "fontSize": "11px",
                                "marginTop": "10px", "marginBottom": "2px"}),
                dcc.Slider(
                    id=f"slider-{param.key}",
                    min=param.min, max=param.max, value=param.default, step=param.step,
                    marks=None,
                    tooltip={"placement": "bottom", "always_visible": True},
                    className="mb-1",
                ),
            ])

    # Actions
    has_actions = figure.buttons or figure._has_draggable
    if has_actions:
        children.append(_section_header("Actions"))
        if figure._has_draggable:
            children.append(
                dbc.Button("📍  Place Start Point", id="btn-select-mode",
                           color="primary", outline=True, size="sm",
                           className="mb-2 w-100")
            )
        for i, btn in enumerate(figure.buttons):
            children.append(
                dbc.Button(btn.label, id=f"btn-action-{i}", color=btn.color,
                           size="sm", n_clicks=0, className="mb-2 w-100")
            )

    # Animation
    if figure.animation:
        children.append(_section_header("Animation"))
        children.extend([
            dbc.ButtonGroup(
                [
                    dbc.Button("▶", id="btn-play",       color="success", size="sm"),
                    dbc.Button("⏸", id="btn-pause",      color="warning", size="sm"),
                    dbc.Button("↺", id="btn-reset-anim", color="danger",  size="sm"),
                ],
                className="mb-3 w-100",
            ),
            html.Div("Frame", style={"color": "#8890b0", "fontSize": "11px", "marginBottom": "2px"}),
            dcc.Slider(id="slider-frame", min=0, max=figure.animation.max_frames,
                       value=0, step=1, marks=None,
                       tooltip={"placement": "bottom", "always_visible": True},
                       className="mb-2"),
            html.Div("Speed (fps)", style={"color": "#8890b0", "fontSize": "11px", "marginBottom": "2px"}),
            dcc.Slider(id="slider-fps", min=1, max=60, value=int(figure.animation.fps),
                       step=1, marks=None,
                       tooltip={"placement": "bottom", "always_visible": True},
                       className="mb-2"),
        ])

    # Axis Bounds
    axes = [("X", "x"), ("Y", "y"), ("Z", "z")] if is3d else [("X", "x"), ("Y", "y")]
    children.append(_section_header("Axis Bounds"))
    _inp = {
        "backgroundColor": "#111827", "color": "white",
        "border": "1px solid #2a3050", "fontSize": "11px",
        "height": "26px", "padding": "2px 6px",
    }
    for label, key in axes:
        children.append(
            dbc.Row([
                dbc.Col(html.Div(label, style={"color": "#8890b0", "fontSize": "11px",
                                               "paddingTop": "5px", "textAlign": "right"}), width=2),
                dbc.Col(dbc.Input(id=f"bounds-{key}-min", type="number", placeholder="min",
                                  debounce=True, size="sm", style=_inp), width=5),
                dbc.Col(dbc.Input(id=f"bounds-{key}-max", type="number", placeholder="max",
                                  debounce=True, size="sm", style=_inp), width=5),
            ], className="mb-1 g-1")
        )

    children.append(
        html.Div("WASD · Space/Shift to pan",
                 style={"color": "#2a3050", "fontSize": "10px",
                        "marginTop": "20px", "textAlign": "center"})
    )
    return html.Div(children)


def _build_graph_panel(figure):
    from dash import dcc, html

    stores = [
        dcc.Store(id="app-state",           data=_serialize_state(figure._state_defaults)),
        dcc.Store(id="select-mode-active",  data=False),
        dcc.Store(id="traj-store",          data={}),
        dcc.Store(id="traj-version-store",  data=0),
        dcc.Store(id="page-load-store",     data=True),
        dcc.Store(id="anim-status-store",   data="idle"),
    ]
    if figure.animation:
        stores.append(dcc.Store(id="anim-config-store", data=figure.animation.max_frames))

    return html.Div([
        *stores,
        dcc.Graph(
            id="main-graph",
            style={"height": "100vh"},
            config={"scrollZoom": True, "displayModeBar": True, "displaylogo": False},
        ),
    ])


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _register_callbacks(app, figure) -> None:
    import dash
    from dash import Input, Output, State, ctx

    has_anim      = figure.animation is not None
    has_draggable = figure._has_draggable
    is3d          = _is_3d(figure)
    n_sliders     = len(figure.sliders)
    n_vis         = len(figure.elements)
    n_btns        = len(figure.buttons)
    slider_keys   = [p.key for p in figure.sliders]
    axes          = ["x", "y", "z"] if is3d else ["x", "y"]

    anim_trace_indices = [
        i for i, e in enumerate(figure.elements)
        if hasattr(e, "animate") and e.animate
    ]

    # -------------------------------------------------------------------
    # Axis bounds: included directly in the main callback so every
    # Plotly.react() always bakes the current bounds into the layout.
    # This prevents clicks / parameter changes from resetting user-set bounds.
    # -------------------------------------------------------------------
    bounds_inputs = []
    for ax in axes:
        bounds_inputs.append(Input(f"bounds-{ax}-min", "value"))
        bounds_inputs.append(Input(f"bounds-{ax}-max", "value"))

    # -------------------------------------------------------------------
    # Callback A — full figure recompute
    # -------------------------------------------------------------------
    main_inputs = (
        [Input(f"slider-{p.key}", "value") for p in figure.sliders]
        + [Input(f"vis-{i}", "value") for i in range(n_vis)]
        + [Input(f"btn-action-{i}", "n_clicks") for i in range(n_btns)]
        + [Input("main-graph", "clickData")]
        + ([Input("btn-select-mode", "n_clicks")] if has_draggable else [])
        + bounds_inputs
    )
    main_states = [
        State("app-state",          "data"),
        State("select-mode-active", "data"),
        State("traj-version-store", "data"),
    ]
    if has_anim:
        main_states.append(State("slider-frame", "value"))

    @app.callback(
        Output("main-graph",          "figure"),
        Output("app-state",           "data"),
        Output("select-mode-active",  "data"),
        Output("traj-store",          "data"),
        Output("traj-version-store",  "data"),
        main_inputs,
        main_states,
        prevent_initial_call=False,
    )
    def update_figure(*args):
        idx = 0
        slider_vals   = args[idx: idx + n_sliders]; idx += n_sliders
        vis_vals      = args[idx: idx + n_vis];     idx += n_vis
        btn_vals      = args[idx: idx + n_btns];    idx += n_btns  # noqa: F841
        click_data    = args[idx];                  idx += 1
        select_clicks = args[idx] if has_draggable else None; idx += (1 if has_draggable else 0)  # noqa: F841

        # Axis bounds (interleaved: min0, max0, min1, max1, ...)
        n_axes = len(axes)
        bounds_raw    = args[idx: idx + n_axes * 2]; idx += n_axes * 2
        axis_ranges   = {}
        for i, ax in enumerate(axes):
            lo, hi = bounds_raw[2 * i], bounds_raw[2 * i + 1]
            if lo is not None and hi is not None and lo < hi:
                axis_ranges[ax] = (lo, hi)

        stored_state  = args[idx] or {};    idx += 1
        select_mode   = args[idx] or False; idx += 1
        traj_version  = args[idx] or 0;    idx += 1
        frame_val     = args[idx] if has_anim else 0

        state     = _deserialize_state(stored_state)
        triggered = ctx.triggered_id

        if has_draggable and triggered == "btn-select-mode":
            select_mode = not select_mode

        if triggered == "main-graph" and click_data and select_mode:
            pt = click_data["points"][0]
            state["x0"] = float(pt.get("x", state.get("x0", 0.0)))
            state["y0"] = float(pt.get("y", state.get("y0", 0.0)))
            state["z0"] = float(pt.get("z", state.get("z0", 0.0)))
            select_mode = False

        params = {
            k: (v if v is not None else figure.sliders[i].default)
            for i, (k, v) in enumerate(zip(slider_keys, slider_vals))
        }
        for i, btn in enumerate(figure.buttons):
            if triggered == f"btn-action-{i}":
                updates = btn.callback(**{**state, **params}) or {}
                state.update(updates)

        full_state = {**state, **params, "_frame": int(frame_val or 0)}

        for elem, vis in zip(figure.elements, vis_vals):
            if vis is not None:
                elem.visible = bool(vis)

        plotly_fig = figure.get_figure(full_state, axis_ranges=axis_ranges or None)

        # Pre-compute full trajectories for animated traces
        traj_data: dict = {}
        for trace_idx in anim_trace_indices:
            elem = figure.elements[trace_idx]
            try:
                pts = np.array(elem.fn(**full_state), dtype=float)
                traj_data[str(trace_idx)] = pts.tolist()
            except Exception as exc:
                print(f"[pringle] trajectory error for '{elem.name}': {exc}")

        new_version = (traj_version or 0) + 1
        return plotly_fig, _serialize_state(state), select_mode, traj_data, new_version

    # -------------------------------------------------------------------
    # Clientside animation — play/pause/reset/scrub, zero server round-trips
    # -------------------------------------------------------------------
    if has_anim:
        anim_inputs = [
            Input("btn-play",          "n_clicks"),
            Input("btn-pause",         "n_clicks"),
            Input("btn-reset-anim",    "n_clicks"),
            Input("slider-fps",        "value"),
            Input("slider-frame",      "value"),
            Input("traj-version-store","data"),   # increments when params change
        ]
        anim_states = [
            State("traj-store",        "data"),   # actual trajectory (not a trigger)
            State("anim-config-store", "data"),
        ]
        app.clientside_callback(
            _ANIMATION_JS,
            Output("anim-status-store", "data"),
            anim_inputs,
            anim_states,
            prevent_initial_call=True,
        )

    # -------------------------------------------------------------------
    # Select-mode button styling
    # -------------------------------------------------------------------
    if has_draggable:
        @app.callback(
            Output("btn-select-mode", "outline"),
            Output("btn-select-mode", "color"),
            Input("select-mode-active", "data"),
        )
        def style_select_button(active):
            return (not active), ("warning" if active else "primary")

    # -------------------------------------------------------------------
    # WASD keyboard camera — entirely clientside
    # -------------------------------------------------------------------
    app.clientside_callback(
        _KEYBOARD_CAMERA_JS,
        Output("page-load-store", "data"),
        Input("page-load-store",  "data"),
        prevent_initial_call=False,
    )
