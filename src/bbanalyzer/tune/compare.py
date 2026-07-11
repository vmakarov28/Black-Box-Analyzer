"""analyze --compare before.bbl after.bbl: renders step-response and noise
deltas between two logs so a staged change can actually be verified to
have helped, rather than assumed. Pure comparison logic here; plotting
lives in report/plots.py, file writing in cli.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from bbanalyzer.dsp.metrics import AXES, FlightMetrics

# direction of "improvement" per metric -- used only to label the delta,
# never to hide a result; both numbers are always shown regardless.
_LOWER_IS_BETTER = {
    "rise_time_s", "overshoot_pct", "settling_time_s",
    "noise_reduction_db_inverted",  # placeholder, not used directly (see below)
    "propwash_max_rms_degps",
}
_HIGHER_IS_BETTER = {"noise_reduction_db"}


@dataclass
class MetricDelta:
    name: str
    before: float | str | None
    after: float | str | None
    delta: float | None
    improved: bool | None


def _delta_row(name: str, before, after) -> MetricDelta:
    if isinstance(before, bool) or isinstance(after, bool):
        improved = None
        if isinstance(before, bool) and isinstance(after, bool) and before != after:
            improved = after is True  # went unstable->stable (good) or stable->unstable (bad)
        return MetricDelta(name, before, after, None, improved)
    if before is None or after is None:
        return MetricDelta(name, before, after, None, None)
    delta = after - before
    improved = None
    base = name.split(".")[-1]
    if base in _HIGHER_IS_BETTER:
        improved = delta > 0
    elif base in _LOWER_IS_BETTER:
        improved = delta < 0
    return MetricDelta(name, before, after, delta, improved)


def compare_flights(before: FlightMetrics, after: FlightMetrics) -> list[MetricDelta]:
    rows: list[MetricDelta] = []
    for axis in AXES:
        b, a = before.axes.get(axis), after.axes.get(axis)
        b_sr, a_sr = (b.step_response if b else None), (a.step_response if a else None)
        rows.append(_delta_row(f"{axis}.rise_time_s", getattr(b_sr, "rise_time_s", None), getattr(a_sr, "rise_time_s", None)))
        rows.append(_delta_row(f"{axis}.overshoot_pct", getattr(b_sr, "overshoot_pct", None), getattr(a_sr, "overshoot_pct", None)))
        rows.append(_delta_row(f"{axis}.settling_time_s", getattr(b_sr, "settling_time_s", None), getattr(a_sr, "settling_time_s", None)))
        rows.append(_delta_row(f"{axis}.stable", getattr(b_sr, "stable", None), getattr(a_sr, "stable", None)))

        b_fc, a_fc = (b.filter_comparison if b else None), (a.filter_comparison if a else None)
        b_nr = b_fc.noise_reduction_db if (b_fc and b_fc.available) else None
        a_nr = a_fc.noise_reduction_db if (a_fc and a_fc.available) else None
        rows.append(_delta_row(f"{axis}.noise_reduction_db", b_nr, a_nr))

        b_rms = max((p.rms_error_degps for p in b.propwash_scores), default=None) if b else None
        a_rms = max((p.rms_error_degps for p in a.propwash_scores), default=None) if a else None
        rows.append(_delta_row(f"{axis}.propwash_max_rms_degps", b_rms, a_rms))

    rows.append(_delta_row("throttle_chop_count", before.throttle_chop_count, after.throttle_chop_count))
    return rows
