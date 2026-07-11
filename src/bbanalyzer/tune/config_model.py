"""Unified structured config -- whether the pilot's current tune comes
from a CLI diff file (preferred) or, failing that, the blackbox log's own
header, everything downstream deals with a single TuneConfig shape. `keys`
is the ground truth for the version-guard round-trip check: every key the
generator ever emits must appear here first, exactly as spelled.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bbanalyzer.parse.header import HeaderConfig


@dataclass
class TuneConfig:
    source: str  # "cli_diff" | "blackbox_header"
    keys: dict[str, str] = field(default_factory=dict)  # lowercased key -> raw value string, verbatim
    firmware_version: tuple[int, int, int] | None = None
    firmware_target: str | None = None
    simplified_tuning_active: bool = False
    raw_text: str = ""

    def get(self, key: str) -> str | None:
        return self.keys.get(key.lower())

    def has(self, key: str) -> bool:
        return key.lower() in self.keys


def from_header(cfg: HeaderConfig) -> TuneConfig:
    return TuneConfig(
        source="blackbox_header",
        keys={k.lower(): v for k, v in cfg.raw.items()},
        firmware_version=cfg.firmware_version,
        firmware_target=cfg.target,
        simplified_tuning_active=cfg.simplified_tuning_active,
    )
