"""Event segmentation: throttle chops and stick snaps, with gyro tracking
error ("propwash score" / bounce-back detection) in the windows after them.

All thresholds here are heuristic defaults tuned against the sample logs
during development (TUNABLE), not sourced from a Betaflight spec -- there
isn't an authoritative definition of "how fast is a throttle chop."
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# TUNABLE
CHOP_MIN_DROP_PCT = 20.0        # throttle must fall by at least this many percentage points
CHOP_MAX_DURATION_S = 0.30      # ...within this long a window to count as a "chop" (not a slow descent)
SNAP_MIN_RATE_DEGPS = 400.0     # setpoint must swing by at least this much
SNAP_MAX_DURATION_S = 0.15
EVENT_MERGE_GAP_S = 0.10        # events closer together than this are merged into one
PROPWASH_WINDOW_S = (0.05, 0.50)  # analysis window relative to event end
MIN_EVENT_SPACING_S = 0.20


@dataclass
class ThrottleChopEvent:
    """end_time_s marks when the lower throttle level was reached (reliable
    -- this is what propwash analysis anchors to). start_time_s is the
    earliest point within the detection window consistent with that drop,
    which for a fast/near-instant chop can read up to CHOP_MAX_DURATION_S
    earlier than the actual stick movement, not the literal transition
    sample -- a byproduct of the sliding-window detection method.
    """

    start_time_s: float
    end_time_s: float
    drop_pct: float


@dataclass
class StickSnapEvent:
    axis: str
    start_time_s: float
    end_time_s: float
    rate_change_degps: float


@dataclass
class PropwashScore:
    event_start_time_s: float
    rms_error_degps: float
    peak_error_degps: float
    zero_crossings: int
    bounce_back: bool


def _find_rapid_changes(time_s: np.ndarray, signal_arr: np.ndarray, min_change: float, max_duration_s: float) -> list[tuple[int, int, float]]:
    """Finds (start_idx, end_idx, signed_change) spans where signal_arr
    changes by at least min_change within at most max_duration_s, via a
    sliding-window running max/min over the max-duration horizon.
    """
    n = len(time_s)
    if n < 2:
        return []
    dt = np.median(np.diff(time_s))
    if dt <= 0:
        return []
    horizon = max(1, int(round(max_duration_s / dt)))
    events = []
    i = 0
    while i < n - 1:
        j_end = min(n, i + horizon + 1)
        window = signal_arr[i:j_end]
        idx_min = i + int(np.argmin(window))
        idx_max = i + int(np.argmax(window))
        change = window[idx_max - i] - window[idx_min - i]
        if abs(change) >= min_change:
            start_idx, end_idx = (idx_min, idx_max) if idx_max > idx_min else (idx_max, idx_min)
            events.append((start_idx, end_idx, float(signal_arr[end_idx] - signal_arr[start_idx])))
            i = end_idx + max(1, int(round(MIN_EVENT_SPACING_S / dt)))
        else:
            i += 1
    return events


def detect_throttle_chops(time_s: np.ndarray, throttle_pct: np.ndarray) -> list[ThrottleChopEvent]:
    spans = _find_rapid_changes(time_s, throttle_pct, CHOP_MIN_DROP_PCT, CHOP_MAX_DURATION_S)
    events = [
        ThrottleChopEvent(start_time_s=float(time_s[s]), end_time_s=float(time_s[e]), drop_pct=-change)
        for s, e, change in spans
        if change < 0  # only drops count as "chops"
    ]
    return events


def detect_stick_snaps(time_s: np.ndarray, setpoint_degps: np.ndarray, axis: str = "roll") -> list[StickSnapEvent]:
    spans = _find_rapid_changes(time_s, setpoint_degps, SNAP_MIN_RATE_DEGPS, SNAP_MAX_DURATION_S)
    return [
        StickSnapEvent(axis=axis, start_time_s=float(time_s[s]), end_time_s=float(time_s[e]), rate_change_degps=change)
        for s, e, change in spans
    ]


def score_propwash(
    time_s: np.ndarray,
    gyro_degps: np.ndarray,
    setpoint_degps: np.ndarray,
    event_end_time_s: float,
) -> PropwashScore | None:
    """Gyro tracking error (gyro - setpoint) in the window after a throttle
    chop. Elevated oscillatory error there is characteristic of propwash;
    a bounce-back is flagged when the error's sign actually alternates
    (genuine oscillation) rather than a single overshoot-and-recover.
    """
    lo = event_end_time_s + PROPWASH_WINDOW_S[0]
    hi = event_end_time_s + PROPWASH_WINDOW_S[1]
    mask = (time_s >= lo) & (time_s <= hi)
    if mask.sum() < 5:
        return None
    error = gyro_degps[mask] - setpoint_degps[mask]
    error = error - np.mean(error[: max(1, len(error) // 5)])  # remove any residual steady offset from just before window start
    rms = float(np.sqrt(np.mean(error**2)))
    peak = float(np.max(np.abs(error)))
    signs = np.sign(error)
    signs = signs[signs != 0]
    zero_crossings = int(np.sum(np.diff(signs) != 0)) if len(signs) > 1 else 0
    return PropwashScore(
        event_start_time_s=event_end_time_s,
        rms_error_degps=rms,
        peak_error_degps=peak,
        zero_crossings=zero_crossings,
        bounce_back=zero_crossings >= 2,
    )
