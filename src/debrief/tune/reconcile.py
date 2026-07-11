"""If the pilot's supplied CLI diff and the blackbox log's own header
config disagree, the log was very likely flown on a different tune than
the one the diff represents -- meaning every finding in this report may
already be stale. This module produces loud, specific warnings for that
case; the caller (cli.py) is expected to surface them prominently, not
just log them.

TUNABLE: the tolerance for "PID gains agree" is a rounding-error
allowance, not a documented spec value -- Betaflight gains are integers,
so any real difference should be an exact mismatch; the tolerance exists
only to avoid noise from e.g. a diff dumped mid-edit with a stale rounding
artifact.
"""
from __future__ import annotations

from debrief.parse.header import HeaderConfig
from debrief.tune.config_model import TuneConfig

_PID_TOLERANCE = 1.0  # absolute gain units


def _to_float(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def check_diff_vs_header_agreement(diff_cfg: TuneConfig, header_cfg: HeaderConfig) -> list[str]:
    warnings: list[str] = []

    if diff_cfg.firmware_version and header_cfg.firmware_version and diff_cfg.firmware_version != header_cfg.firmware_version:
        warnings.append(
            f"Firmware version mismatch: the supplied CLI diff is for {'.'.join(map(str, diff_cfg.firmware_version))} "
            f"but this log was flown on {'.'.join(map(str, header_cfg.firmware_version))}. "
            "The diagnosis below is almost certainly for a different tune/firmware than this flight."
        )

    for axis, gains in header_cfg.pid_gains.items():
        for term, log_value in (("P", gains.P), ("I", gains.I), ("D", gains.D)):
            if log_value is None:
                continue
            diff_value = _to_float(diff_cfg.get(f"{term.lower()}_{axis}"))
            if diff_value is None:
                continue
            if abs(diff_value - log_value) > _PID_TOLERANCE:
                warnings.append(
                    f"{term}[{axis}] mismatch: the supplied CLI diff has {diff_value:g}, but this log's own header "
                    f"recorded {log_value:g} at flight time. The log was very likely flown on a different tune than "
                    "the one in the diff file -- treat every finding below as potentially stale."
                )

    return warnings
