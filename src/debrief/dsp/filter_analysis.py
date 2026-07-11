"""Filtered (gyroADC) vs unfiltered gyro comparison: noise reduction
achieved and estimated filter group-delay cost per axis.

Betaflight can log a pre-filter gyro trace into ``debug[]`` when
``debug_mode`` is set appropriately (e.g. GYRO_SCALED), but the integer
debug_mode value that means "unfiltered gyro" has changed across firmware
versions and we don't have an authoritative version->meaning table we're
confident in -- guessing one and silently mislabeling a debug channel as
"unfiltered gyro" would be exactly the kind of fabricated heuristic the
project rules forbid.

Instead this module data-driven-detects the unfiltered-gyro proxy: a debug
channel that is strongly correlated with the filtered gyro on the same axis
but carries more high-frequency energy AND leads it by a genuinely nonzero,
plausible lag is treated as a valid proxy. That last check matters: on a
real sample log, a debug channel was found that correlates 0.9998 with
gyro but at exactly zero lag -- physically impossible for a real filter's
input (any lowpass/notch chain has nonzero group delay), so it's almost
certainly a duplicate/copy of the already-filtered signal, not a genuine
pre-filter tap. Without the lag check this would have been silently
reported as a "0.0ms filter latency" finding -- a fabricated number dressed
up as measured. TUNABLE: all thresholds below are heuristic defaults.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

MIN_CORRELATION = 0.80
MIN_HF_ENERGY_RATIO = 1.05    # unfiltered proxy must carry at least this much more HF energy
HF_BAND_HZ = (80.0, 500.0)    # "high frequency" band for the noise-reduction figure
MAX_LAG_SEARCH_S = 0.050      # filter group delay is not going to exceed 50ms in practice
MIN_PLAUSIBLE_LAG_SAMPLES = 1  # a genuine pre-filter tap must lead by at least one sample


@dataclass
class FilterComparison:
    axis: str
    available: bool
    reason: str | None = None
    debug_channel: int | None = None
    correlation: float | None = None
    noise_reduction_db: float | None = None
    estimated_latency_s: float | None = None


def _bandpower(freq: np.ndarray, psd: np.ndarray, band: tuple[float, float]) -> float:
    mask = (freq >= band[0]) & (freq <= band[1])
    if not mask.any():
        return 0.0
    return float(np.trapezoid(psd[mask], freq[mask]))


def _estimate_lag_samples(leading: np.ndarray, lagging: np.ndarray, sample_rate_hz: float) -> int | None:
    """Lag (in samples, >=0) at which `leading` best predicts `lagging` via
    cross-correlation, searched only over non-negative lags (i.e. assumes
    `leading` genuinely precedes `lagging` -- appropriate for
    unfiltered->filtered, never the reverse).
    """
    max_lag = min(len(leading) - 1, int(round(MAX_LAG_SEARCH_S * sample_rate_hz)))
    if max_lag < 1:
        return None
    a = leading - np.mean(leading)
    b = lagging - np.mean(lagging)
    xcorr = signal.correlate(b, a, mode="full")
    lags = signal.correlation_lags(len(b), len(a), mode="full")
    center = len(lags) // 2
    window = slice(center, center + max_lag + 1)
    if not xcorr[window].size:
        return None
    best = int(np.argmax(xcorr[window]))
    return int(lags[window][best])


def detect_unfiltered_proxy(
    gyro_degps: np.ndarray, debug_channels: dict[int, np.ndarray], sample_rate_hz: float
) -> tuple[int | None, float | None]:
    """Returns (channel_index, correlation) for the debug[] channel most
    likely to be a genuine unfiltered predecessor of gyro_degps, or
    (None, None) if no channel passes the correlation, HF-energy-ratio,
    AND nonzero-lag checks.
    """
    best_ch, best_corr = None, None
    fs = sample_rate_hz
    freq_g, psd_g = signal.welch(gyro_degps, fs=fs, nperseg=min(4096, len(gyro_degps)))
    hf_g = _bandpower(freq_g, psd_g, HF_BAND_HZ)

    for ch, trace in debug_channels.items():
        if len(trace) != len(gyro_degps) or np.allclose(trace, 0):
            continue
        corr = float(np.corrcoef(gyro_degps, trace)[0, 1])
        if not np.isfinite(corr) or corr < MIN_CORRELATION:
            continue
        freq_d, psd_d = signal.welch(trace, fs=fs, nperseg=min(4096, len(trace)))
        hf_d = _bandpower(freq_d, psd_d, HF_BAND_HZ)
        if hf_g <= 0 or hf_d / max(hf_g, 1e-9) < MIN_HF_ENERGY_RATIO:
            continue
        lag = _estimate_lag_samples(trace, gyro_degps, fs)
        if lag is None or lag < MIN_PLAUSIBLE_LAG_SAMPLES:
            continue  # zero/negative lag: not physically consistent with being upstream of a filter
        if best_corr is None or corr > best_corr:
            best_ch, best_corr = ch, corr
    return best_ch, best_corr


def compare_filtered_vs_unfiltered(
    gyro_degps: np.ndarray,
    debug_channels: dict[int, np.ndarray],
    sample_rate_hz: float,
    axis: str = "roll",
) -> FilterComparison:
    if sample_rate_hz <= 0 or len(gyro_degps) < 256:
        return FilterComparison(axis, False, "segment too short for a spectral comparison")

    ch, corr = detect_unfiltered_proxy(gyro_degps, debug_channels, sample_rate_hz)
    if ch is None:
        return FilterComparison(
            axis,
            False,
            "no debug[] channel behaves like a genuine unfiltered predecessor of gyro "
            "(needs high correlation, more HF energy, AND a nonzero lead time) -- set "
            "debug_mode to a gyro-related mode and reflight to enable this comparison",
        )

    unfiltered = debug_channels[ch]
    freq_f, psd_f = signal.welch(gyro_degps, fs=sample_rate_hz, nperseg=min(4096, len(gyro_degps)))
    freq_u, psd_u = signal.welch(unfiltered, fs=sample_rate_hz, nperseg=min(4096, len(unfiltered)))
    hf_f = _bandpower(freq_f, psd_f, HF_BAND_HZ)
    hf_u = _bandpower(freq_u, psd_u, HF_BAND_HZ)
    noise_reduction_db = 10.0 * np.log10(hf_u / hf_f) if hf_f > 0 and hf_u > 0 else None

    lag = _estimate_lag_samples(unfiltered, gyro_degps, sample_rate_hz)
    latency_s = lag / sample_rate_hz if lag is not None else None

    return FilterComparison(
        axis=axis,
        available=True,
        debug_channel=ch,
        correlation=corr,
        noise_reduction_db=noise_reduction_db,
        estimated_latency_s=latency_s,
    )
