from pathlib import Path

import pytest

from bbanalyzer.parse import LogParseError, load

DATA = Path(__file__).parent / "data"


def test_load_single_flight_bbl():
    lf = load(DATA / "good_tune.BBL")
    assert lf.n_declared_logs == 1
    assert len(lf.flights) == 1
    f = lf.flights[0]
    assert f.n_frames > 100_000
    assert f.duration_s == pytest.approx(156.78, abs=0.1)
    assert f.setpoint_axes == ["roll", "pitch", "yaw"]
    assert f.config.firmware_name == "Betaflight"
    assert f.config.firmware_version == (3, 1, 5)
    assert f.config.pid_gains["roll"].P == 19.0
    for col in ("time_s", "gyro[0]", "gyro[1]", "gyro[2]",
                "setpoint[0]", "setpoint[1]", "setpoint[2]", "throttle",
                "motor[0]", "debug[0]"):
        assert col in f.df.columns


def test_load_multiflight_corrupt_bfl():
    """14 embedded logs: 13 are empty arm-blip stubs, 1 is a real flight.
    Must load the real one and gracefully skip the stubs, not raise.
    """
    lf = load(DATA / "stock_tune.BFL")
    assert lf.n_declared_logs == 14
    assert len(lf.flights) == 1
    assert len(lf.skipped) == 13
    assert all("0 frames" in s["reason"] for s in lf.skipped)
    f = lf.flights[0]
    assert f.index == 12
    assert f.n_frames > 500_000


def test_garbage_file_raises_log_parse_error(tmp_path):
    garbage = tmp_path / "not_a_log.bbl"
    garbage.write_bytes(b"definitely not a blackbox log" * 50)
    with pytest.raises(LogParseError):
        load(garbage)


def test_missing_file_raises():
    with pytest.raises(LogParseError):
        load("/no/such/file.bbl")


def test_truncated_file_loads_partial_without_raising(tmp_path):
    data = (DATA / "good_tune.BBL").read_bytes()
    truncated = tmp_path / "truncated.BBL"
    truncated.write_bytes(data[:5000] + data[200_000:250_000])
    lf = load(truncated)
    assert len(lf.flights) == 1
    assert lf.flights[0].n_frames > 0
    assert lf.flights[0].n_frames < 154_311
