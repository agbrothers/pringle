"""
Session persistence — save and load a full Pringle session as YAML.

YAML format (version 1)
-----------------------
version: 1
grid:
  x_min: float  x_max: float  y_min: float  y_max: float  n: int
cells:
  - id: str
    type: equation | slider | data
    source: str
    style:
      color: [r, g, b, a]
    visible: bool          # equation cells
    value: float           # slider cells (current, possibly != initial)
    min_val: float         # slider cells
    max_val: float         # slider cells
    sub_cells:
      - type: constraint | condition | initial_condition | recursion
        source: str

Public API
----------
cell_to_dict(cell)                     → dict
save_session(path, cell_list, grid_config, data_panel=None)
load_session(path)                     → dict
restore_cell_list(cell_list, cells_data)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from pringle.grid import GridConfig

if TYPE_CHECKING:
    from pringle.cell_list import CellListWidget


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def cell_to_dict(cell) -> dict:
    """Serialize any cell widget to a JSON-safe dict."""
    from pringle.slider_widget import SliderWidget
    from pringle.data_cell_widget import DataCellWidget
    from pringle.folder_cell_widget import FolderCellWidget

    base = {
        "id": cell.cell_id,
        "style": {
            "color":           list(cell.style.color),
            "opacity":         cell.style.opacity,
            "line_width":      cell.style.line_width,
            "point_size":      cell.style.point_size,
            "scatter_as_line": cell.style.scatter_as_line,
        },
    }

    if isinstance(cell, FolderCellWidget):
        base["type"] = "folder"
        base["name"] = cell.name
        base["collapsed"] = cell.is_collapsed
        base["sub_cells"] = []

    elif isinstance(cell, SliderWidget):
        base["type"] = "slider"
        base["source"] = cell.source()
        base["name"] = cell.name
        base["value"] = float(cell.value)
        base["min_val"] = float(cell._min)
        base["max_val"] = float(cell._max)
        base["step"] = float(cell._step_box.value())
        base["is_playing"] = cell._play_btn.isChecked()
        base["anim_mode"] = cell._anim_mode
        base["sub_cells"] = []

    elif isinstance(cell, DataCellWidget):
        base["type"] = "data"
        base["source"] = cell.source()
        base["sub_cells"] = [
            {"type": s.sub_type(), "source": s.source()}
            for s in cell._sub_cells
        ]

    else:
        # CellWidget (equation)
        base["type"] = "equation"
        base["source"] = cell.source()
        base["visible"] = cell.is_visible_cell()
        base["sub_cells"] = [
            {"type": s.sub_type(), "source": s.source()}
            for s in cell._sub_cells
        ]

    return base


def grid_config_to_dict(config: GridConfig) -> dict:
    return {
        "x_min": config.x_min, "x_max": config.x_max,
        "y_min": config.y_min, "y_max": config.y_max,
        "z_min": config.z_min, "z_max": config.z_max,
        "n": config.n,
    }


def grid_config_from_dict(d: dict) -> GridConfig:
    return GridConfig(
        x_min=d.get("x_min", -5.0), x_max=d.get("x_max", 5.0),
        y_min=d.get("y_min", -5.0), y_max=d.get("y_max", 5.0),
        z_min=d.get("z_min", -5.0), z_max=d.get("z_max", 5.0),
        n=int(d.get("n", 64)),
    )


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_session(
    path: str | Path,
    cell_list: CellListWidget,
    grid_config: GridConfig,
) -> None:
    """Serialize session to a YAML file at *path*."""
    session = {
        "version": 1,
        "grid": grid_config_to_dict(grid_config),
        "cells": [cell_to_dict(c) for c in cell_list._cells],
    }
    Path(path).write_text(yaml.dump(session, allow_unicode=True, sort_keys=False))


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_session(path: str | Path) -> dict:
    """
    Parse a YAML session file and return the raw dict.

    Raises ValueError if the file format version is unrecognised.
    """
    raw = yaml.safe_load(Path(path).read_text())
    version = raw.get("version", 1)
    if version != 1:
        raise ValueError(f"Unsupported session version: {version}")
    return raw


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def restore_cell_list(
    cell_list: CellListWidget,
    cells_data: list[dict],
) -> None:
    """
    Reconstruct a CellListWidget from loaded YAML cell data.

    Clears existing cells first.
    """
    from pringle.style import CellStyle
    from pringle.slider_widget import SliderWidget
    from pringle.cell_widget import ConstraintSubCell

    # Remove all existing cells
    for cell in list(cell_list._cells):
        cell_list.remove_cell(cell.cell_id)

    sliders_to_play: list = []

    for data in cells_data:
        cell_type = data.get("type", "equation")
        source = data.get("source", "")
        style_data = data.get("style", {})
        raw_color = style_data.get("color", [0.22, 0.40, 0.88, 1.0])
        color = tuple(float(v) for v in raw_color)
        style = CellStyle(
            color=color,
            opacity=float(style_data.get("opacity", 1.0)),
            line_width=float(style_data.get("line_width", 0.05)),
            point_size=float(style_data.get("point_size", 0.1)),
            scatter_as_line=style_data.get("scatter_as_line", False),
        )

        if cell_type == "folder":
            from pringle.folder_cell_widget import FolderCellWidget
            folder = cell_list.add_folder(
                name=data.get("name", "Group"),
                style=style,
            )
            if data.get("collapsed", False):
                folder.set_collapsed(True)
            continue

        if cell_type == "data":
            cell = cell_list.add_data_cell(source=source, style=style)
        else:
            cell = cell_list.add_cell(source=source, style=style)

        # Restore slider-specific state
        if cell_type == "slider" and isinstance(cell, SliderWidget):
            # Set box values first so _on_range_changed reads correct pair
            cell._min_box.setValue(float(data.get("min_val", 0.0)))
            cell._max_box.setValue(float(data.get("max_val", 10.0)))
            if "step" in data:
                cell._step_box.setValue(float(data["step"]))
            cell._spinbox.setRange(cell._min, cell._max)
            cell.set_value(float(data.get("value", cell.value)), emit=False)
            if "anim_mode" in data:
                cell.set_anim_mode(data["anim_mode"])
            if data.get("is_playing", False):
                sliders_to_play.append(cell)

        # Restore equation cell state
        elif cell_type == "equation":
            from pringle.cell_widget import CellWidget
            if isinstance(cell, CellWidget):
                if not data.get("visible", True):
                    cell._eye_btn.setChecked(False)
                    cell._on_visibility_toggled(False)
                for sub_data in data.get("sub_cells", []):
                    sub = cell.add_sub_cell(sub_data.get("type", "constraint"))
                    sub._edit.setText(sub_data.get("source", ""))

        # Restore data cell sub-cells
        elif cell_type == "data":
            from pringle.data_cell_widget import DataCellWidget
            if isinstance(cell, DataCellWidget):
                for sub_data in data.get("sub_cells", []):
                    sub = cell.add_sub_cell(sub_data.get("type", "initial_condition"))
                    sub._edit.setText(sub_data.get("source", ""))

    # Start any sliders that were playing when saved (must happen after full restore
    # so the shared namespace is populated before the first animation tick fires)
    for cell in sliders_to_play:
        cell._play_btn.setChecked(True)
        cell._on_play_toggled(True)


