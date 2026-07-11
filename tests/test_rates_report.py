from pathlib import Path

from bbanalyzer.dsp import compute_flight_metrics
from bbanalyzer.parse import load
from bbanalyzer.tune.rates_report import build_rates_report

DATA = Path(__file__).parent / "data"


def test_rates_report_measured_p95_present_for_real_log():
    lf = load(DATA / "good_tune.BBL")
    f = lf.flights[0]
    m = compute_flight_metrics(f)
    report = build_rates_report(m, f.config)
    assert len(report) == 3
    for axis_info in report:
        assert axis_info.measured_p95_degps is not None
        assert axis_info.measured_p95_degps >= 0


def test_rates_report_legacy_formula_used_for_legacy_config():
    lf = load(DATA / "good_tune.BBL")  # BF 3.1.5, legacy rcRate format
    f = lf.flights[0]
    m = compute_flight_metrics(f)
    report = build_rates_report(m, f.config)
    roll = next(r for r in report if r.axis == "roll")
    assert roll.configured_max_degps is not None
    assert "approximate" in roll.configured_max_note


def test_rates_report_never_fabricates_unavailable_formula():
    from bbanalyzer.dsp.metrics import FlightMetrics
    from bbanalyzer.parse.header import HeaderConfig

    cfg = HeaderConfig(raw={})
    cfg.rates_raw = {"rates_type": "ACTUAL", "roll_rc_rate": "7"}  # modern format, deliberately unimplemented
    empty_metrics = FlightMetrics(axes={}, throttle_chop_count=0, flat={})
    report = build_rates_report(empty_metrics, cfg)
    for axis_info in report:
        assert axis_info.configured_max_degps is None
        assert "not confidently computable" in axis_info.configured_max_note
