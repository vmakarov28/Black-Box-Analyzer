"""Bounds checks. These never clamp a value down to something "close
enough" -- an out-of-bounds request is rejected outright and surfaced for
a human to look at, per the hard safety requirement. TUNABLE: the specific
numbers below are conservative defaults, not values from a Betaflight spec.
"""
from __future__ import annotations

MAX_GAIN_MOVE_PCT = 30.0
MIN_FILTER_HZ = 20.0
NYQUIST_SAFETY_MARGIN = 0.9  # a requested cutoff may use at most this fraction of loop-rate/2


def validate_gain_change(current_value: float, new_value: float) -> tuple[bool, str | None]:
    if current_value == 0:
        return False, "current value is 0 -- can't compute a safe percentage move; needs a human to pick a starting value"
    pct = abs(new_value - current_value) / abs(current_value) * 100.0
    if pct > MAX_GAIN_MOVE_PCT:
        return False, f"requested move is {pct:.0f}%, over the {MAX_GAIN_MOVE_PCT:.0f}% per-stage cap"
    return True, None


def validate_filter_hz(value: float, loop_rate_hz: float | None) -> tuple[bool, str | None]:
    if value < MIN_FILTER_HZ:
        return False, f"{value:.0f}Hz is below the {MIN_FILTER_HZ:.0f}Hz sane minimum -- would filter out real signal"
    if loop_rate_hz:
        nyquist_limit = (loop_rate_hz / 2.0) * NYQUIST_SAFETY_MARGIN
        if value > nyquist_limit:
            return False, f"{value:.0f}Hz exceeds {NYQUIST_SAFETY_MARGIN:.0%} of Nyquist ({nyquist_limit:.0f}Hz) for a {loop_rate_hz:.0f}Hz loop rate"
    return True, None
