from pathlib import Path

from bbanalyzer.dsp import compute_flight_metrics
from bbanalyzer.parse import load

DATA = Path(__file__).parent / "data"


def test_compute_flight_metrics_on_real_log():
    lf = load(DATA / "good_tune.BBL")
    f = lf.flights[0]
    m = compute_flight_metrics(f)

    assert len(m.flat) >= 40
    assert set(m.axes.keys()) == {"roll", "pitch", "yaw"}
    assert m.throttle_chop_count > 0

    for axis in ("roll", "pitch", "yaw"):
        assert m.flat[f"step_response.{axis}.rise_time_s"] is not None
        assert m.flat[f"step_response.{axis}.stable"] in (True, False)
        assert m.flat[f"noise.{axis}.horizontal_band_count"] >= 0
        assert isinstance(m.flat[f"filter.{axis}.available"], bool)


def test_compute_flight_metrics_on_corrupt_flight_does_not_raise():
    lf = load(DATA / "stock_tune.BFL")
    f = lf.flights[0]  # the one real flight among the 13 skipped stubs
    m = compute_flight_metrics(f)
    assert len(m.flat) >= 40
