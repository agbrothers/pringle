"""YAML/JSON config helpers for per-repo plot configurations."""
from __future__ import annotations

import json
from pathlib import Path


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    text = p.read_text()
    if p.suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text) or {}
    return json.loads(text)


def save_config(path: str, config: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix in (".yaml", ".yml"):
        import yaml
        p.write_text(yaml.dump(config, default_flow_style=False))
    else:
        p.write_text(json.dumps(config, indent=2))
