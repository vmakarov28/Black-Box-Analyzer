"""Parses a Betaflight CLI `diff`/`dump` text file (paste-ready output from
the Configurator or `diff` command over a serial connection) into a
TuneConfig. This is the preferred source config for the tune generator --
see config_model.from_header for the fallback when no diff file is given.
"""
from __future__ import annotations

import re

from bbanalyzer.tune.config_model import TuneConfig

_SET_LINE_RE = re.compile(r"^\s*set\s+([a-zA-Z0-9_]+)\s*=\s*(.+?)\s*$", re.IGNORECASE)
_VERSION_RE = re.compile(
    r"#\s*Betaflight\s*/\s*(\S+)\s*(?:\([^)]*\))?\s*(\d+)\.(\d+)\.(\d+)", re.IGNORECASE
)


def parse_cli_diff(text: str) -> TuneConfig:
    keys: dict[str, str] = {}
    firmware_version = None
    firmware_target = None

    for line in text.splitlines():
        if firmware_version is None:
            m = _VERSION_RE.search(line)
            if m:
                firmware_target = m.group(1)
                firmware_version = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
                continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _SET_LINE_RE.match(line)
        if m:
            key, value = m.group(1).lower(), m.group(2).strip()
            keys[key] = value

    simplified_active = keys.get("simplified_pids_mode", "").strip().upper() == "ON"

    return TuneConfig(
        source="cli_diff",
        keys=keys,
        firmware_version=firmware_version,
        firmware_target=firmware_target,
        simplified_tuning_active=simplified_active,
        raw_text=text,
    )


def parse_cli_diff_file(path: str) -> TuneConfig:
    from pathlib import Path

    return parse_cli_diff(Path(path).read_text(encoding="utf-8", errors="replace"))
