"""RATES HONESTY: rates are pilot preference, not a tuning defect. This
module only ever runs behind an explicit --rates flag, and everything it
produces is labeled preference-based, never phrased as a "fix".

Reports measured stick usage (95th percentile |commanded rotation rate|
per axis, from dsp.metrics -- solid, no formula risk) against the
*configured* max rate, when we can compute it with confidence.

We deliberately do NOT implement the modern "Actual"/"Betaflight" rates
curve formula here: it has changed shape across firmware versions and
getting it subtly wrong would silently misinform a rates change
recommendation, which is exactly the kind of fabricated heuristic the
project rules forbid. The one case computed is the legacy Cleanflight/
BF3.x rcRate-only approximation, which is simple and stable across the
versions that use it. Everywhere else, the raw configured values are
shown verbatim instead of a guessed number.
"""
from __future__ import annotations

from dataclasses import dataclass

from bbanalyzer.dsp.metrics import AXES, FlightMetrics
from bbanalyzer.parse.header import HeaderConfig

# TUNABLE: the *200 factor is the long-standing community approximation for
# legacy (pre-"Actual Rates") Cleanflight/Betaflight max stick rate, not an
# exact firmware formula.
_LEGACY_MAX_RATE_FACTOR = 200.0


@dataclass
class AxisRatesInfo:
    axis: str
    measured_p95_degps: float | None
    configured_max_degps: float | None  # None if not confidently computable
    configured_max_note: str
    raw_rates: dict[str, str]


def _legacy_max_rate(rates_raw: dict[str, str], axis: str) -> float | None:
    key = "rcRate" if axis in ("roll", "pitch") else "rcYawRate"
    val = rates_raw.get(key)
    if val is None:
        return None
    try:
        rc_rate = float(val) / 100.0
    except ValueError:
        return None
    return rc_rate * _LEGACY_MAX_RATE_FACTOR


def build_rates_report(m: FlightMetrics, cfg: HeaderConfig) -> list[AxisRatesInfo]:
    report = []
    is_legacy = "rcRate" in cfg.rates_raw and "rates_type" not in cfg.rates_raw
    for axis in AXES:
        ax = m.axes.get(axis)
        measured = ax.stick_p95_degps if ax else None

        configured = None
        note = "configured max rate not confidently computable from header data for this rates format"
        if is_legacy:
            configured = _legacy_max_rate(cfg.rates_raw, axis)
            if configured is not None:
                note = "approximate (legacy rcRate*200 formula)"

        report.append(
            AxisRatesInfo(
                axis=axis,
                measured_p95_degps=measured,
                configured_max_degps=configured,
                configured_max_note=note,
                raw_rates=dict(cfg.rates_raw),
            )
        )
    return report
