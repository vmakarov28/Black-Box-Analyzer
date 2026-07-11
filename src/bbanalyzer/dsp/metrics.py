"""Top-level DSP orchestrator: a loaded Flight -> ~40 named scalar metrics
plus the full per-axis curve data (for Phase 5 plotting). Pure function,
no plotting, no file I/O -- this is the only module the rules layer
(Phase 3) and report layer (Phase 5) need to import from dsp/.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from bbanalyzer.dsp.events import (
    PropwashScore,
    detect_stick_snaps,
    detect_throttle_chops,
    score_propwash,
)
from bbanalyzer.dsp.filter_analysis import FilterComparison, compare_filtered_vs_unfiltered
from bbanalyzer.dsp.noise import (
    DiagonalTrace,
    HorizontalBand,
    NoiseHeatmap,
    compute_noise_heatmap,
    detect_diagonal_trace,
    detect_horizontal_bands,
)
from bbanalyzer.dsp.step_response import StepResponseResult, compute_step_response

AXES = ("roll", "pitch", "yaw")
AXIS_IDX = {"roll": 0, "pitch": 1, "yaw": 2}


@dataclass
class AxisResult:
    axis: str
    step_response: StepResponseResult
    noise: NoiseHeatmap
    diagonal_trace: DiagonalTrace | None
    horizontal_bands: list[HorizontalBand]
    filter_comparison: FilterComparison
    stick_snap_count: int
    propwash_scores: list[PropwashScore] = field(default_factory=list)


@dataclass
class FlightMetrics:
    axes: dict[str, AxisResult]
    throttle_chop_count: int
    flat: dict[str, object]


def _throttle_pct(df, header_raw: dict[str, str]) -> np.ndarray:
    max_throttle = float(header_raw.get("maxthrottle", 2000))
    throttle_raw = df["throttle"].to_numpy(dtype=np.float64) if "throttle" in df.columns else df["rcCommand[3]"].to_numpy(dtype=np.float64)
    return np.clip((throttle_raw - 1000.0) / max(max_throttle - 1000.0, 1.0) * 100.0, 0, 100)


def compute_flight_metrics(flight) -> FlightMetrics:
    """flight: a bbanalyzer.parse.loader.Flight"""
    df = flight.df
    time_s = df["time_s"].to_numpy(dtype=np.float64)
    throttle_pct = _throttle_pct(df, flight.header)
    sample_rate_hz = flight.sample_rate_hz or 1000.0

    debug_channels = {}
    for i in range(4):
        col = f"debug[{i}]"
        if col in df.columns:
            debug_channels[i] = df[col].to_numpy(dtype=np.float64)

    chops = detect_throttle_chops(time_s, throttle_pct)

    axes: dict[str, AxisResult] = {}
    flat: dict[str, object] = {}

    for axis in AXES:
        idx = AXIS_IDX[axis]
        gyro_col = f"gyro[{idx}]"
        setpoint_col = f"setpoint[{idx}]"
        if gyro_col not in df.columns:
            continue
        gyro = df[gyro_col].to_numpy(dtype=np.float64)

        if setpoint_col in df.columns:
            setpoint = df[setpoint_col].to_numpy(dtype=np.float64)
            step = compute_step_response(time_s, setpoint, gyro, throttle_pct, axis=axis)
            snaps = detect_stick_snaps(time_s, setpoint, axis=axis)
            propwash = [
                s
                for chop in chops
                if (s := score_propwash(time_s, gyro, setpoint, chop.end_time_s)) is not None
            ]
        else:
            step = StepResponseResult(axis, np.linspace(0, 0.5, 2), None, None, None, 0, 0, None, None, None, None,
                                       ["setpoint unavailable for this axis"])
            snaps = []
            propwash = []

        noise = compute_noise_heatmap(time_s, gyro, throttle_pct, axis=axis)
        diagonal = detect_diagonal_trace(noise)
        horizontal = detect_horizontal_bands(noise)
        filt = compare_filtered_vs_unfiltered(gyro, debug_channels, sample_rate_hz, axis=axis)

        axes[axis] = AxisResult(
            axis=axis,
            step_response=step,
            noise=noise,
            diagonal_trace=diagonal,
            horizontal_bands=horizontal,
            filter_comparison=filt,
            stick_snap_count=len(snaps),
            propwash_scores=propwash,
        )

        p = f"step_response.{axis}."
        flat[p + "rise_time_s"] = step.rise_time_s
        flat[p + "overshoot_pct"] = step.overshoot_pct
        flat[p + "settling_time_s"] = step.settling_time_s
        flat[p + "stable"] = step.stable
        flat[p + "n_windows"] = step.n_windows
        flat[p + "n_windows_high"] = step.n_windows_high

        n = f"noise.{axis}."
        flat[n + "diagonal_detected"] = diagonal is not None
        flat[n + "diagonal_correlation"] = diagonal.correlation if diagonal else None
        flat[n + "diagonal_slope_hz_per_pct"] = diagonal.slope_hz_per_pct if diagonal else None
        flat[n + "horizontal_band_count"] = len(horizontal)
        flat[n + "horizontal_band_1_hz"] = horizontal[0].freq_hz if horizontal else None

        fl = f"filter.{axis}."
        flat[fl + "available"] = filt.available
        flat[fl + "noise_reduction_db"] = filt.noise_reduction_db
        flat[fl + "latency_ms"] = filt.estimated_latency_s * 1000.0 if filt.estimated_latency_s is not None else None

        e = f"events.{axis}."
        flat[e + "stick_snap_count"] = len(snaps)
        rms_vals = [p.rms_error_degps for p in propwash]
        flat[e + "propwash_max_rms_degps"] = max(rms_vals) if rms_vals else None
        flat[e + "propwash_bounce_back_rate"] = (
            sum(1 for p in propwash if p.bounce_back) / len(propwash) if propwash else None
        )

    flat["events.throttle_chop_count"] = len(chops)

    return FlightMetrics(axes=axes, throttle_chop_count=len(chops), flat=flat)
