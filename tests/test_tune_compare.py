from pathlib import Path

from bbanalyzer.dsp import compute_flight_metrics
from bbanalyzer.parse import load
from bbanalyzer.tune.compare import compare_flights

DATA = Path(__file__).parent / "data"


def test_compare_identical_flight_shows_zero_deltas():
    lf = load(DATA / "good_tune.BBL")
    m = compute_flight_metrics(lf.flights[0])
    rows = compare_flights(m, m)
    numeric_rows = [r for r in rows if r.delta is not None]
    assert numeric_rows
    for r in numeric_rows:
        assert abs(r.delta) < 1e-6


def test_compare_direction_of_improvement_labeled_correctly():
    from bbanalyzer.tune.compare import _delta_row

    # rise_time_s: lower is better
    row = _delta_row("roll.rise_time_s", 0.020, 0.010)
    assert row.improved is True
    row = _delta_row("roll.rise_time_s", 0.010, 0.020)
    assert row.improved is False

    # noise_reduction_db: higher is better
    row = _delta_row("roll.noise_reduction_db", 3.0, 6.0)
    assert row.improved is True

    # stable: False->True is an improvement
    row = _delta_row("roll.stable", False, True)
    assert row.improved is True
    row = _delta_row("roll.stable", True, False)
    assert row.improved is False


def test_compare_missing_data_reports_none_not_a_fabricated_delta():
    from bbanalyzer.tune.compare import _delta_row

    row = _delta_row("roll.rise_time_s", None, 0.010)
    assert row.delta is None
    assert row.improved is None
