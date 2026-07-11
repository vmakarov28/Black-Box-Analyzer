"""Shared windowing/spectral primitives used by step_response.py and noise.py.

The windowing, Wiener deconvolution, and weighted-mode-average routines are
ported from Plasmatree PID-Analyzer's ``Trace`` class (BEER-WARE licensed,
see docs/phase1-parser-evaluation.md) so that Phase 2's validation gate can
reconcile numerically against it. They're pure functions here (no plotting,
no classes) per the DSP-layer design requirement.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d


def resample_uniform(time_s: np.ndarray, *signals: np.ndarray) -> tuple[np.ndarray, ...]:
    """Interpolate onto a uniform time grid spanning [time_s[0], time_s[-1]]
    with the same sample count. Blackbox logs are near-uniform already;
    this removes small jitter before FFT-based processing, matching
    PID-Analyzer's ``equalize_data``.
    """
    n = len(time_s)
    new_time = np.linspace(time_s[0], time_s[-1], n, dtype=np.float64)
    out = [np.interp(new_time, time_s, s) for s in signals]
    return (new_time, *out)


def _to_unit_range(x: np.ndarray) -> np.ndarray:
    x = x - x.min()
    m = x.max()
    return x / m if m else x


def window_stack(arrays: dict[str, np.ndarray], win_len: int, superpos: int) -> dict[str, np.ndarray]:
    """Slice each named 1D array into overlapping windows of length win_len,
    hopping by win_len//superpos. Shape: (n_windows, win_len) per key.
    Mirrors PID-Analyzer's ``winstacker`` exactly, including its choice to
    drop the last ``superpos`` windows rather than use a ragged tail.
    """
    n = len(next(iter(arrays.values())))
    hop = max(1, win_len // superpos)
    n_windows = max(0, n // hop - superpos)
    out: dict[str, np.ndarray] = {}
    for name, arr in arrays.items():
        stacked = np.empty((n_windows, win_len), dtype=np.float64)
        for i in range(n_windows):
            start = i * hop
            stacked[i] = arr[start : start + win_len]
        out[name] = stacked
    return out


def wiener_deconvolution(
    input_stack: np.ndarray, output_stack: np.ndarray, cutfreq_hz: float, dt_s: float
) -> np.ndarray:
    """Per-window frequency-domain Wiener deconvolution of output by input.

    Both arrays are (n_windows, win_len), already windowed (e.g.
    Hanning-multiplied). Content above ``cutfreq_hz`` is treated as noise
    to regularize against -- real stick step commands are low-frequency,
    so this keeps the deconvolution from amplifying high-frequency gyro
    noise into the recovered impulse response.
    """
    win_len = input_stack.shape[1]
    pad = 1024 - (win_len % 1024)
    inp = np.pad(input_stack, [(0, 0), (0, pad)], mode="constant")
    outp = np.pad(output_stack, [(0, 0), (0, pad)], mode="constant")
    H = np.fft.fft(inp, axis=-1)
    G = np.fft.fft(outp, axis=-1)
    freq = np.abs(np.fft.fftfreq(inp.shape[1], dt_s))
    sn = _to_unit_range(np.clip(freq, cutfreq_hz - 1e-9, cutfreq_hz))
    len_lpf = np.sum(np.ones_like(sn) - sn)
    sn = _to_unit_range(gaussian_filter1d(sn, max(len_lpf, 1e-9) / 6.0))
    sn = 10.0 * (-sn + 1.0 + 1e-9)
    Hcon = np.conj(H)
    deconvolved = np.real(np.fft.ifft(G * Hcon / (H * Hcon + 1.0 / sn), axis=-1))
    return deconvolved


def weighted_mode_average(
    values: np.ndarray,
    weights: np.ndarray,
    value_range: tuple[float, float] = (-1.5, 3.5),
    n_bins: int = 1000,
    smooth_width: int = 7,
) -> tuple[np.ndarray, np.ndarray]:
    """Collapse a stack of per-window curves (n_windows, n_t) into one
    representative curve by taking, at each time step, the mode of the
    weighted distribution of values across windows. This is robust to
    outlier windows (e.g. one window straddling a clipped stick input)
    in a way a plain mean is not. Ported from PID-Analyzer's
    ``weighted_mode_avr``.

    Returns (curve, spread) where spread is a rough dispersion measure
    (fraction of value-range covered by bins above a fixed density
    threshold, at each time step) -- useful as a confidence indicator,
    not a real statistical error bar.
    """
    n_windows, n_t = values.shape
    if n_windows == 0 or weights.sum() == 0:
        return np.zeros(n_t), np.zeros(n_t)
    resp_y = np.linspace(value_range[0], value_range[1], n_bins)
    t_idx = np.repeat(np.arange(n_t)[None, :], n_windows, axis=0)
    w = np.repeat(weights, n_t)
    hist2d = np.histogram2d(
        t_idx.flatten(),
        values.flatten(),
        range=[[0, n_t - 1], list(value_range)],
        bins=[n_t, n_bins],
        weights=w.flatten(),
    )[0].transpose()
    if hist2d.sum() == 0:
        return np.zeros(n_t), np.zeros(n_t)
    hist2d_sm = gaussian_filter1d(hist2d, smooth_width, axis=0, mode="constant")
    col_max = np.max(hist2d_sm, axis=0)
    col_max = np.where(col_max == 0, 1.0, col_max)
    hist2d_sm = hist2d_sm / col_max
    pixelpos = np.repeat(resp_y.reshape(-1, 1), n_t, axis=1)
    avg = np.average(pixelpos, axis=0, weights=hist2d_sm * hist2d_sm)
    hist_bin_height = 0.5 / (n_bins / (value_range[1] - value_range[0]))
    spread = np.sum(np.where(hist2d > 0.5, hist_bin_height, 0.0), axis=0)
    return avg, spread


def rfft_spectrum(dt_s: float, traces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Real FFT of a stack of windows (n_windows, win_len), padded to a
    multiple of 1024 for speed. Returns (freq_hz, complex_spectrum).
    """
    win_len = traces.shape[-1]
    pad = 1024 - (win_len % 1024)
    padded = np.pad(traces, [(0, 0)] * (traces.ndim - 1) + [(0, pad)], mode="constant")
    spec = np.fft.rfft(padded, axis=-1, norm="ortho")
    freq = np.fft.rfftfreq(padded.shape[-1], dt_s)
    return freq, spec
