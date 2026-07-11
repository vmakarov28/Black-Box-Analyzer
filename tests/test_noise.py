import numpy as np

from debrief.dsp.noise import compute_noise_heatmap, detect_diagonal_trace, detect_horizontal_bands


def _ramp_then_hold(t, duration_s, ramp_frac=0.85):
    """0->100% over the first ramp_frac of the flight, then holds at 100%.
    Holding at the end (rather than ramping straight through to the last
    sample) means the noise-heatmap's landing-trim (last 2s dropped) only
    eats into the redundant hold period, not the sole high-throttle
    samples -- otherwise a monotonic full-flight ramp would lose its only
    high-throttle data to the trim.
    """
    ramp_end = duration_s * ramp_frac
    return np.clip(t / ramp_end * 100.0, 0, 100)


def _rpm_linked_flight(duration_s=90.0, fs=2000.0, seed=0):
    """Throttle ramps 0->100%; gyro noise contains a tone whose frequency
    scales linearly with throttle (motor-RPM-like) -- a synthetic
    diagonal trace. Long enough that every 1%-wide throttle bin collects
    well over MIN_THROTTLE_SAMPLES windows.
    """
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    t = np.arange(n) / fs
    throttle = _ramp_then_hold(t, duration_s)
    freq_hz = 50.0 + throttle * 3.0  # 50Hz at 0% throttle up to 350Hz at 100%
    phase = 2 * np.pi * np.cumsum(freq_hz) / fs
    tone = 20.0 * np.sin(phase)
    gyro = tone + rng.normal(0, 2.0, n)
    return t, gyro, throttle


def _resonance_flight(duration_s=90.0, fs=2000.0, seed=0):
    """A fixed-frequency resonance present at all throttle levels."""
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    t = np.arange(n) / fs
    throttle = np.clip(_ramp_then_hold(t, duration_s), 5, 100)
    tone = 15.0 * np.sin(2 * np.pi * 120.0 * t)  # constant 120Hz frame resonance
    gyro = tone + rng.normal(0, 2.0, n)
    return t, gyro, throttle


def test_diagonal_trace_detected_on_rpm_linked_signal():
    t, gyro, throttle = _rpm_linked_flight()
    hm = compute_noise_heatmap(t, gyro, throttle, axis="roll")
    assert hm.psd.size > 0
    diag = detect_diagonal_trace(hm, min_freq_hz=20.0)
    assert diag is not None
    assert diag.correlation > 0.6
    assert diag.slope_hz_per_pct > 0


def test_horizontal_band_detected_on_resonance_signal():
    t, gyro, throttle = _resonance_flight()
    hm = compute_noise_heatmap(t, gyro, throttle, axis="roll")
    bands = detect_horizontal_bands(hm)
    assert len(bands) >= 1
    assert abs(bands[0].freq_hz - 120.0) < 15.0


def test_noise_heatmap_too_short_segment_graceful():
    t = np.linspace(0, 0.1, 50)
    gyro = np.zeros(50)
    throttle = np.full(50, 50.0)
    hm = compute_noise_heatmap(t, gyro, throttle, axis="roll")
    assert hm.psd.size == 0
    assert len(hm.notes) > 0
    assert detect_diagonal_trace(hm) is None
    assert detect_horizontal_bands(hm) == []
