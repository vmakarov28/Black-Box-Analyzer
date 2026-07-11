"""Throttle-vs-frequency gyro noise heatmap, plus automatic detection of
diagonal traces (RPM-linked noise, since motor RPM scales roughly with
throttle) vs horizontal bands (frame/prop resonance at a fixed frequency
regardless of throttle).

The heatmap construction (windowed rfft, weight by |Re(spectrum)|, 2D
histogram against throttle, normalize by throttle-bin sample count) mirrors
Plasmatree PID-Analyzer's ``stackspectrum``/``hist2d`` so Phase 2's
validation gate can reconcile against it numerically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter1d

from debrief.dsp._common import resample_uniform, rfft_spectrum, window_stack

NOISE_FRAME_LEN_S = 0.3
NOISE_SUPERPOS = 16
LANDING_TRIM_S = 2.0   # TUNABLE: trims the tail to avoid contaminating noise stats with landing/touchdown
THROTTLE_BINS = 101    # 0..100% inclusive, 1%-wide bins
FREQ_DECIMATE = 4       # matches upstream's freq[::4] -- keeps heatmap size sane
SMOOTH_WIDTH = 3

# TUNABLE: heuristic thresholds for the diagonal/horizontal classifier below,
# not sourced from a spec -- reasonable defaults tightened against the
# sample logs during development.
MIN_THROTTLE_SAMPLES = 20        # ignore throttle bins with too few windows to trust
DIAGONAL_MIN_CORR = 0.6          # Pearson r between throttle% and peak-freq
DIAGONAL_MIN_BINS = 8            # need this many well-populated throttle bins to even attempt correlation
HORIZONTAL_ENERGY_PERCENTILE = 75.0   # a frequency row must be in the top quartile of mean energy
HORIZONTAL_MAX_CV = 0.5          # ...and have coefficient-of-variation below this across throttle


@dataclass
class NoiseHeatmap:
    axis: str
    freq_hz: np.ndarray             # (n_freq,)
    throttle_pct: np.ndarray        # (n_throttle,) bin centers, 0..100
    psd: np.ndarray                 # (n_freq, n_throttle) normalized magnitude
    throttle_sample_counts: np.ndarray
    notes: list[str] = field(default_factory=list)


@dataclass
class DiagonalTrace:
    correlation: float
    slope_hz_per_pct: float
    freq_at_min_throttle_hz: float
    freq_at_max_throttle_hz: float


@dataclass
class HorizontalBand:
    freq_hz: float
    energy_percentile: float
    coefficient_of_variation: float


def compute_noise_heatmap(
    time_s: np.ndarray, gyro_degps: np.ndarray, throttle_pct: np.ndarray, axis: str = "roll"
) -> NoiseHeatmap:
    notes: list[str] = []
    t, gy, thr = resample_uniform(time_s, gyro_degps, throttle_pct)
    dt = t[1] - t[0] if len(t) > 1 else 0.0
    flen = max(1, round(NOISE_FRAME_LEN_S / dt)) if dt > 0 else 0

    if dt <= 0 or len(t) < flen * (NOISE_SUPERPOS + 4):
        notes.append("segment too short for a throttle-binned noise heatmap")
        return NoiseHeatmap(axis, np.array([]), np.array([]), np.zeros((0, 0)), np.zeros(0), notes)

    stacks = window_stack({"gyro": gy, "throttle": thr}, flen, NOISE_SUPERPOS)
    n_windows = stacks["gyro"].shape[0]
    trim = int(NOISE_SUPERPOS * LANDING_TRIM_S / NOISE_FRAME_LEN_S)
    if trim > 0 and n_windows > trim:
        gyro_stack = stacks["gyro"][: n_windows - trim]
        throttle_stack = stacks["throttle"][: n_windows - trim]
    else:
        gyro_stack, throttle_stack = stacks["gyro"], stacks["throttle"]
        notes.append("flight too short to apply the landing trim; heatmap may include touchdown noise")

    if gyro_stack.shape[0] < 3:
        notes.append("too few windows remain after landing trim")
        return NoiseHeatmap(axis, np.array([]), np.array([]), np.zeros((0, 0)), np.zeros(0), notes)

    window = np.hanning(flen)
    gyro_w = gyro_stack * window
    thr_w = throttle_stack * window

    freq, spec = rfft_spectrum(dt, gyro_w)
    weights = np.abs(spec.real)
    peak_throttle = np.abs(thr_w).max(axis=1)

    n_freq_bins = max(1, len(freq) // FREQ_DECIMATE)

    # Build the 2D histogram: rows=freq bins, cols=throttle bins, weighted by |Re(spectrum)|.
    freqs_tiled = np.repeat(freq[None, :], len(peak_throttle), axis=0)
    throttles_tiled = np.repeat(peak_throttle[:, None], len(freq), axis=1)
    hist2d, throt_edges, freq_edges_ = np.histogram2d(
        throttles_tiled.flatten(),
        freqs_tiled.flatten(),
        range=[[0, 100], [freq[0], freq[-1]]],
        bins=[THROTTLE_BINS - 1, n_freq_bins],
        weights=weights.flatten(),
    )
    throttle_hist, _ = np.histogram(peak_throttle, bins=THROTTLE_BINS - 1, range=[0, 100])
    hist2d_norm = hist2d / (throttle_hist[:, None] + 1e-9)
    hist2d_norm = hist2d_norm.transpose()  # -> (n_freq_bins, n_throttle_bins)
    hist2d_sm = gaussian_filter1d(hist2d_norm, SMOOTH_WIDTH, axis=1, mode="constant")  # smooth across throttle, matching reference

    freq_centers = 0.5 * (freq_edges_[:-1] + freq_edges_[1:])
    throttle_centers = 0.5 * (throt_edges[:-1] + throt_edges[1:])

    return NoiseHeatmap(
        axis=axis,
        freq_hz=freq_centers,
        throttle_pct=throttle_centers,
        psd=hist2d_sm,
        throttle_sample_counts=throttle_hist,
        notes=notes,
    )


def detect_diagonal_trace(heatmap: NoiseHeatmap, min_freq_hz: float = 30.0) -> DiagonalTrace | None:
    """RPM-linked noise shows up as a ridge whose frequency rises with
    throttle (motor RPM scales roughly linearly with throttle in cruise).
    Finds each well-populated throttle bin's peak frequency (above
    min_freq_hz to skip DC/low-frequency airframe motion) and checks for a
    strong positive correlation between throttle and peak frequency.
    """
    if heatmap.psd.size == 0:
        return None
    valid_cols = np.where(heatmap.throttle_sample_counts >= MIN_THROTTLE_SAMPLES)[0]
    if len(valid_cols) < DIAGONAL_MIN_BINS:
        return None
    freq_mask = heatmap.freq_hz >= min_freq_hz
    if not freq_mask.any():
        return None

    throttles, peak_freqs = [], []
    for col in valid_cols:
        col_energy = heatmap.psd[freq_mask, col]
        if col_energy.max() <= 0:
            continue
        peak_idx = np.argmax(col_energy)
        throttles.append(heatmap.throttle_pct[col])
        peak_freqs.append(heatmap.freq_hz[freq_mask][peak_idx])

    if len(throttles) < DIAGONAL_MIN_BINS:
        return None
    throttles_arr, peaks_arr = np.array(throttles), np.array(peak_freqs)
    if np.std(throttles_arr) == 0 or np.std(peaks_arr) == 0:
        return None
    corr = float(np.corrcoef(throttles_arr, peaks_arr)[0, 1])
    if corr < DIAGONAL_MIN_CORR:
        return None
    slope = float(np.polyfit(throttles_arr, peaks_arr, 1)[0])
    order = np.argsort(throttles_arr)
    return DiagonalTrace(
        correlation=corr,
        slope_hz_per_pct=slope,
        freq_at_min_throttle_hz=float(peaks_arr[order[0]]),
        freq_at_max_throttle_hz=float(peaks_arr[order[-1]]),
    )


def detect_horizontal_bands(heatmap: NoiseHeatmap, max_bands: int = 3) -> list[HorizontalBand]:
    """Frame/prop resonance shows up as a row of persistently elevated
    energy at roughly the same frequency regardless of throttle. Flags
    frequency rows that are both high-energy (top quartile of mean energy
    across all rows) and low-variance across throttle (coefficient of
    variation below a threshold), i.e. "loud everywhere", vs a diagonal
    ridge which is loud only in a throttle-dependent band.
    """
    if heatmap.psd.size == 0:
        return []
    valid_cols = np.where(heatmap.throttle_sample_counts >= MIN_THROTTLE_SAMPLES)[0]
    if len(valid_cols) < 3:
        return []
    sub = heatmap.psd[:, valid_cols]
    row_mean = sub.mean(axis=1)
    row_std = sub.std(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cv = np.where(row_mean > 0, row_std / row_mean, np.inf)
    energy_threshold = np.percentile(row_mean, HORIZONTAL_ENERGY_PERCENTILE)
    candidates = np.where((row_mean >= energy_threshold) & (cv <= HORIZONTAL_MAX_CV))[0]
    if len(candidates) == 0:
        return []
    ranked = sorted(candidates, key=lambda i: -row_mean[i])
    bands = []
    for i in ranked[:max_bands]:
        bands.append(
            HorizontalBand(
                freq_hz=float(heatmap.freq_hz[i]),
                energy_percentile=float((row_mean < row_mean[i]).mean() * 100),
                coefficient_of_variation=float(cv[i]),
            )
        )
    return bands
