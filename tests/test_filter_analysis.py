import numpy as np
from scipy import signal

from bbanalyzer.dsp.filter_analysis import compare_filtered_vs_unfiltered, detect_unfiltered_proxy


def _filtered_and_unfiltered(fs=2000.0, duration_s=10.0, delay_samples=8, seed=0):
    rng = np.random.default_rng(seed)
    n = int(fs * duration_s)
    t = np.arange(n) / fs
    base = 30.0 * np.sin(2 * np.pi * 5 * t)  # slow "real" motion
    hf_noise = rng.normal(0, 6.0, n)
    unfiltered = base + hf_noise

    b, a = signal.butter(2, 80.0, fs=fs, btype="low")
    filtered = signal.lfilter(b, a, unfiltered)
    filtered = np.concatenate([np.zeros(delay_samples), filtered[:-delay_samples]])  # emulate extra group delay
    return t, filtered, unfiltered, fs


def test_detect_unfiltered_proxy_finds_correct_channel():
    t, filtered, unfiltered, fs = _filtered_and_unfiltered()
    rng = np.random.default_rng(1)
    unrelated = rng.normal(0, 10.0, len(t))
    debug_channels = {0: unrelated, 1: unfiltered, 2: np.zeros_like(t)}
    ch, corr = detect_unfiltered_proxy(filtered, debug_channels, fs)
    assert ch == 1
    assert corr > 0.8


def test_compare_filtered_vs_unfiltered_reports_noise_reduction_and_latency():
    t, filtered, unfiltered, fs = _filtered_and_unfiltered(delay_samples=8)
    result = compare_filtered_vs_unfiltered(filtered, {0: unfiltered}, fs, axis="roll")
    assert result.available is True
    assert result.noise_reduction_db is not None
    assert result.noise_reduction_db > 0  # filtered has less HF energy than unfiltered
    assert result.estimated_latency_s is not None
    assert result.estimated_latency_s > 0


def test_compare_unavailable_when_no_plausible_proxy():
    fs = 2000.0
    n = 4000
    rng = np.random.default_rng(2)
    gyro = rng.normal(0, 5.0, n)
    unrelated_debug = {0: rng.normal(0, 5.0, n)}  # uncorrelated with gyro
    result = compare_filtered_vs_unfiltered(gyro, unrelated_debug, fs, axis="yaw")
    assert result.available is False
    assert result.reason is not None
    assert result.noise_reduction_db is None
