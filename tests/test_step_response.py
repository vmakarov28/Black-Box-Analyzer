import numpy as np
import pytest

from debrief.dsp.step_response import compute_step_response


def _synthetic_flight(duration_s=20.0, fs=1000.0, seed=0):
    """Setpoint = repeated step commands; gyro = setpoint through a
    first-order lag (tau) plus noise, i.e. a well-behaved system with a
    known, roughly-recoverable time constant.
    """
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    t = np.arange(n) / fs
    setpoint = np.zeros(n)
    step_times = np.arange(1.0, duration_s - 1.0, 2.0)
    for st in step_times:
        idx = int(st * fs)
        amplitude = 300.0 if (int(st) % 2 == 0) else -300.0
        setpoint[idx:] = amplitude if idx < n else 0
        # brief return to zero before next step so each is a clean edge
        idx_end = idx + int(1.5 * fs)
        if idx_end < n:
            setpoint[idx_end:] = 0.0

    tau = 0.02  # 20ms lag, typical order of magnitude for a tuned quad
    gyro = np.zeros(n)
    alpha = 1.0 - np.exp(-1.0 / (fs * tau))
    for i in range(1, n):
        gyro[i] = gyro[i - 1] + alpha * (setpoint[i] - gyro[i - 1])
    gyro += rng.normal(0, 3.0, n)  # measurement noise

    throttle = np.full(n, 50.0)
    return t, setpoint, gyro, throttle


def test_step_response_recovers_reasonable_metrics():
    t, sp, gyro, thr = _synthetic_flight()
    r = compute_step_response(t, sp, gyro, thr, axis="roll")
    assert r.response is not None
    assert r.n_windows > 3
    assert r.rise_time_s is not None
    assert 0 < r.rise_time_s < 0.5
    assert r.overshoot_pct is not None
    assert r.overshoot_pct < 60  # first-order lag has no real overshoot; generous bound for method noise
    assert r.settling_time_s is not None


def test_step_response_too_short_segment_returns_notes_not_crash():
    t = np.linspace(0, 0.05, 20)
    sp = np.zeros(20)
    gyro = np.zeros(20)
    thr = np.full(20, 50.0)
    r = compute_step_response(t, sp, gyro, thr, axis="roll")
    assert r.response is None
    assert r.rise_time_s is None
    assert len(r.notes) > 0


def test_step_response_idle_flight_no_stick_input():
    t, _, _, thr = _synthetic_flight()
    sp = np.zeros_like(t)
    gyro = np.random.default_rng(1).normal(0, 1.0, len(t))  # pure noise, no real motion
    r = compute_step_response(t, sp, gyro, thr, axis="roll")
    assert r.response is None
    assert any("stick input" in n for n in r.notes)


def test_step_response_against_real_log_matches_validated_values():
    """Regression pin against the Phase 2 validation-gate numbers
    (docs/phase2-validation-gate.md), where our roll-axis low-input
    response matched Plasmatree PID-Analyzer's reference to ~1e-12.
    """
    from pathlib import Path

    from debrief.parse import load

    lf = load(Path(__file__).parent / "data" / "good_tune.BBL")
    f = lf.flights[0]
    df = f.df
    time_s = df["time_s"].to_numpy()
    throttle_pct = (df["throttle"].to_numpy() - 1000) / (2000 - 1000) * 100
    setpoint = df["setpoint[0]"].to_numpy()
    gyro = df["gyro[0]"].to_numpy()
    r = compute_step_response(time_s, setpoint, gyro, throttle_pct, axis="roll")
    assert r.rise_time_s == pytest.approx(0.012191789, abs=1e-6)
    assert r.stable is True
