"""Loads config.yaml and merges config.local.yaml (site values, not in git) into it."""

from pathlib import Path

import yaml


def merge(base, override):
    """Nested merge, so config.local.yaml only needs the values that change."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(folder):
    folder = Path(folder)
    cfg = yaml.safe_load((folder / "config.yaml").read_text())
    local = folder / "config.local.yaml"
    if local.exists():
        merge(cfg, yaml.safe_load(local.read_text()) or {})
    return cfg
