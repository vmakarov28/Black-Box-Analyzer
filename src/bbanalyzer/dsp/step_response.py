"""Step response per axis via windowed Wiener deconvolution of
setpoint -> gyro, matching Plasmatree PID-Analyzer's method (see
docs/phase1-parser-evaluation.md and dsp/_common.py for the ported
primitives and the Phase 2 validation-gate writeup for numeric
reconciliation).

Setpoint here is the reconstructed PID-loop target from
``parse.setpoint`` (``gyro + axisP/(0.032029*P_gain)``), not a
rates-curve conversion of the RC stick -- see that module's docstring.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from bbanalyzer.dsp._common import (
    resample_uniform,
    weighted_mode_average,
    wiener_deconvolution,
    window_stack,
)

FRAME_LEN_S = 1.0          # window length the deconvolution operates over
RESP_LEN_S = 0.5           # length of the extracted step-response curve
CUTFREQ_HZ = 25.0          # content above this treated as noise by the Wiener filter
SUPERPOS = 16              # window overlap factor
# TUNABLE: matches PID-Analyzer's default split between "small stick" and
# "full deflection" response -- not derived from a spec, just the
# convention this whole analysis method was built around.
HIGH_INPUT_THRESHOLD_DEGPS = 500.0
MIN_INPUT_DEGPS = 20.0      # ignore windows with near-zero stick input (nothing to deconvolve)
MIN_HIGH_WINDOWS = 10       # need at least this many high-input windows for a separate estimate
MIN_WINDOWS_FOR_RESULT = 3

# TUNABLE: standard control-theory step metric conventions applied to a
# system whose ideal DC gain is 1.0 (gyro fully tracks setpoint). Not
# sourced from Betaflight docs -- just the usual 10/90% rise and +-10%
# settling-band definitions.
SETTLE_BAND = 0.10
STABLE_MAX_OVERSHOOT_PCT = 40.0


@dataclass
class StepResponseResult:
    axis: str
    time_s: np.ndarray
    response: np.ndarray | None
    response_low: np.ndarray | None
    response_high: np.ndarray | None
    n_windows: int
    n_windows_high: int
    rise_time_s: float | None
    overshoot_pct: float | None
    settling_time_s: float | None
    stable: bool | None
    notes: list[str] = field(default_factory=list)


def _extract_step_metrics(time_s: np.ndarray, response: np.ndarray | None, target: float = 1.0) -> dict:
    if response is None or len(response) == 0:
        return dict(rise_time_s=None, overshoot_pct=None, settling_time_s=None, stable=None)

    above10 = np.where(response >= 0.10 * target)[0]
    above90 = np.where(response >= 0.90 * target)[0]
    rise_time_s = None
    if len(above10) and len(above90):
        idx10, idx90 = above10[0], above90[0]
        if idx90 > idx10:
            rise_time_s = float(time_s[idx90] - time_s[idx10])

    peak = float(np.max(response))
    overshoot_pct = max(0.0, (peak / target - 1.0) * 100.0) if target else None

    band_lo, band_hi = target * (1 - SETTLE_BAND), target * (1 + SETTLE_BAND)
    outside = np.where((response < band_lo) | (response > band_hi))[0]
    if len(outside) == 0:
        settling_time_s = 0.0
    elif outside[-1] < len(response) - 1:
        settling_time_s = float(time_s[outside[-1] + 1])
    else:
        settling_time_s = None  # never re-enters the settle band within the response window

    stable = None
    if rise_time_s is not None and overshoot_pct is not None:
        stable = (overshoot_pct < STABLE_MAX_OVERSHOOT_PCT) and (settling_time_s is not None)

    return dict(
        rise_time_s=rise_time_s,
        overshoot_pct=overshoot_pct,
        settling_time_s=settling_time_s,
        stable=stable,
    )


def compute_step_response(
    time_s: np.ndarray,
    setpoint_degps: np.ndarray,
    gyro_degps: np.ndarray,
    throttle_pct: np.ndarray,
    axis: str = "roll",
) -> StepResponseResult:
    """Pure function: three aligned 1D arrays in -> a StepResponseResult.

    No plotting, no file I/O. Returns None-valued metrics with an
    explanatory note (never a fabricated number) when the flight segment
    is too short or the stick input too quiet to deconvolve reliably.
    """
    notes: list[str] = []
    rlen_placeholder = np.linspace(0.0, RESP_LEN_S, 2)

    if len(time_s) < 10:
        notes.append("segment too short to compute a step response")
        return StepResponseResult(axis, rlen_placeholder, None, None, None, 0, 0, None, None, None, None, notes)

    t, sp, gy, thr = resample_uniform(time_s, setpoint_degps, gyro_degps, throttle_pct)
    dt = t[1] - t[0]
    if dt <= 0:
        notes.append("non-increasing time axis after resampling")
        return StepResponseResult(axis, rlen_placeholder, None, None, None, 0, 0, None, None, None, None, notes)

    flen = max(1, round(FRAME_LEN_S / dt))
    rlen = max(1, round(RESP_LEN_S / dt))
    if len(t) < flen * 2:
        notes.append(f"segment shorter than 2x the {FRAME_LEN_S}s analysis window")
        return StepResponseResult(axis, np.linspace(0, RESP_LEN_S, rlen), None, None, None, 0, 0, None, None, None, None, notes)

    stacks = window_stack({"input": sp, "gyro": gy, "throttle": thr}, flen, SUPERPOS)
    n_windows_total = stacks["input"].shape[0]
    time_axis = t[:rlen] - t[0]

    if n_windows_total < MIN_WINDOWS_FOR_RESULT:
        notes.append(f"too few {FRAME_LEN_S}s windows ({n_windows_total}) for a reliable step response")
        return StepResponseResult(axis, time_axis, None, None, None, n_windows_total, 0, None, None, None, None, notes)

    win = np.hanning(flen)
    inp = stacks["input"] * win
    outp = stacks["gyro"] * win
    thr_w = stacks["throttle"] * win

    deconv = wiener_deconvolution(inp, outp, CUTFREQ_HZ, dt)[:, :rlen]
    resp_stack = np.cumsum(deconv, axis=1)

    max_in = np.max(np.abs(inp), axis=1)

    active_mask = (max_in > MIN_INPUT_DEGPS).astype(np.float64)
    low_mask = active_mask * (max_in <= HIGH_INPUT_THRESHOLD_DEGPS).astype(np.float64)
    high_mask = active_mask * (max_in > HIGH_INPUT_THRESHOLD_DEGPS).astype(np.float64)
    if high_mask.sum() < MIN_HIGH_WINDOWS:
        high_mask = high_mask * 0.0

    if active_mask.sum() == 0:
        notes.append("no windows with stick input above the noise floor -- quad likely hovering/idle throughout")
        return StepResponseResult(axis, time_axis, None, None, None, n_windows_total, 0, None, None, None, None, notes)

    resp_all, _ = weighted_mode_average(resp_stack, active_mask)
    resp_low, _ = weighted_mode_average(resp_stack, low_mask) if low_mask.sum() > 0 else (None, None)
    resp_high, _ = weighted_mode_average(resp_stack, high_mask) if high_mask.sum() > 0 else (None, None)

    metrics = _extract_step_metrics(time_axis, resp_all)
    if high_mask.sum() == 0:
        notes.append("insufficient full-deflection stick input for a separate high-input response estimate")

    return StepResponseResult(
        axis=axis,
        time_s=time_axis,
        response=resp_all,
        response_low=resp_low,
        response_high=resp_high,
        n_windows=int(active_mask.sum()),
        n_windows_high=int(high_mask.sum()),
        notes=notes,
        **metrics,
    )
