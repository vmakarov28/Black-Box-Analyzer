import numpy as np

from debrief.dsp.events import detect_stick_snaps, detect_throttle_chops, score_propwash


def test_detect_throttle_chop():
    fs = 1000.0
    t = np.arange(0, 5, 1 / fs)
    throttle = np.full_like(t, 80.0)
    chop_start = int(2.0 * fs)
    throttle[chop_start:] = 30.0  # instant 50pp drop
    chops = detect_throttle_chops(t, throttle)
    assert len(chops) == 1
    assert chops[0].drop_pct >= 20.0
    # end_time_s (when the new, lower throttle level is reached) is the
    # reliable anchor point -- see ThrottleChopEvent docstring on why
    # start_time_s can read earlier than the literal transition sample.
    assert abs(chops[0].end_time_s - 2.0) < 0.05
    assert chops[0].start_time_s <= chops[0].end_time_s


def test_no_chop_on_slow_descent():
    fs = 1000.0
    t = np.arange(0, 5, 1 / fs)
    throttle = 80.0 - (t / 5.0) * 50.0  # slow ramp down over 5s, not a chop
    chops = detect_throttle_chops(t, throttle)
    assert chops == []


def test_detect_stick_snap():
    fs = 1000.0
    t = np.arange(0, 5, 1 / fs)
    setpoint = np.zeros_like(t)
    snap_idx = int(2.5 * fs)
    setpoint[snap_idx:] = 600.0
    snaps = detect_stick_snaps(t, setpoint, axis="roll")
    assert len(snaps) == 1
    assert snaps[0].rate_change_degps >= 400.0


def test_propwash_score_detects_oscillation():
    fs = 1000.0
    t = np.arange(0, 2, 1 / fs)
    setpoint = np.zeros_like(t)
    # oscillating tracking error after t=0.5s at 10Hz, decaying
    mask = t >= 0.5
    error = np.zeros_like(t)
    error[mask] = 50.0 * np.exp(-3 * (t[mask] - 0.5)) * np.sin(2 * np.pi * 10 * (t[mask] - 0.5))
    gyro = setpoint + error
    score = score_propwash(t, gyro, setpoint, event_end_time_s=0.5)
    assert score is not None
    assert score.rms_error_degps > 0
    assert score.bounce_back is True
    assert score.zero_crossings >= 2


def test_propwash_score_none_outside_flight_window():
    t = np.arange(0, 1, 0.001)
    gyro = np.zeros_like(t)
    setpoint = np.zeros_like(t)
    score = score_propwash(t, gyro, setpoint, event_end_time_s=5.0)  # window entirely past end of data
    assert score is None
