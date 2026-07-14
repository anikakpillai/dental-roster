"""
Reads and writes config YAML files.

This is the only file that modifies config on disk.
Everything else reads through the loader — only API
endpoints that handle manager edits come through here.
"""
from __future__ import annotations
from pathlib import Path
import yaml


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}


def _write(path: Path, data: dict):
    path.write_text(
        yaml.dump(data, default_flow_style=False,
                  allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_staff_raw(config_dir: Path) -> list[dict]:
    return _load(config_dir / "staff.yaml").get("staff", [])


def save_staff_raw(config_dir: Path, staff_list: list[dict]):
    _write(config_dir / "staff.yaml", {"staff": staff_list})


def load_rules_raw(config_dir: Path) -> dict:
    return _load(config_dir / "rules.yaml")


def save_rules_raw(config_dir: Path, rules: dict):
    _write(config_dir / "rules.yaml", rules)