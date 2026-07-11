import re
from pathlib import Path

from bbanalyzer.dsp import compute_flight_metrics
from bbanalyzer.llm.fallback import render_fallback_narrative
from bbanalyzer.parse import load
from bbanalyzer.report import render_report
from bbanalyzer.rules import diagnose

DATA = Path(__file__).parent / "data"


def test_render_report_is_self_contained(tmp_path):
    lf = load(DATA / "good_tune.BBL")
    flight = lf.flights[0]
    m = compute_flight_metrics(flight)
    findings = diagnose(m, flight.config)
    narrative = render_fallback_narrative(findings, m)

    out = render_report(flight, m, findings, narrative, tmp_path / "report.html", log_filename="good_tune.BBL")
    assert out.is_file()
    html = out.read_text(encoding="utf-8")

    assert "<!doctype html>" in html.lower()
    assert flight.config.craft_name in html
    # no unrendered Jinja placeholders leaked through
    assert not re.search(r"{{.*?}}", html)
    # at least the 3 plots inlined as data URIs
    assert html.count("data:image/png;base64,") >= 3
    # zero external network references
    for bad in ("http://", "https://", "//cdn.", "<script src"):
        assert bad not in html.lower()


def test_render_report_no_recommended_findings(tmp_path):
    from bbanalyzer.dsp.metrics import FlightMetrics
    from bbanalyzer.llm.schema import NarrativeReport

    lf = load(DATA / "good_tune.BBL")
    flight = lf.flights[0]
    empty_metrics = FlightMetrics(axes={}, throttle_chop_count=0, flat={})
    narrative = NarrativeReport(summary="Nothing to report.", items=[], other_observations=[])
    out = render_report(flight, empty_metrics, [], narrative, tmp_path / "report.html")
    html = out.read_text(encoding="utf-8")
    assert "No findings met the bar" in html
