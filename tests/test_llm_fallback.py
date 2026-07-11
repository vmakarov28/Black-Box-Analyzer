from pathlib import Path

from debrief.dsp import compute_flight_metrics
from debrief.llm import render_fallback_narrative
from debrief.parse import load
from debrief.rules import diagnose

DATA = Path(__file__).parent / "data"


def test_fallback_renders_without_any_model():
    lf = load(DATA / "good_tune.BBL")
    f = lf.flights[0]
    m = compute_flight_metrics(f)
    findings = diagnose(m, f.config)

    report = render_fallback_narrative(findings, m)
    assert report.generated_by == "template-fallback"
    assert report.summary
    assert len(report.items) == sum(1 for x in findings if x.recommended)
    assert len(report.items) <= 3


def test_low_confidence_findings_phrased_as_questions():
    lf = load(DATA / "good_tune.BBL")
    f = lf.flights[0]
    m = compute_flight_metrics(f)
    findings = diagnose(m, f.config)

    from debrief.rules.flag import Confidence

    for finding in findings:
        if not finding.recommended:
            continue
        item = next(
            i for i in render_fallback_narrative(findings, m).items if i.finding_id == finding.id
        )
        if finding.confidence == Confidence.LOW:
            assert item.is_question
            assert "?" in item.whats_wrong or "?" in item.why_plain_english


def test_fallback_never_fabricates_a_cli_command():
    """Without a validated diff supplied, cli_diff must never contain a
    bare `set` command -- only a clearly-marked, unvalidated direction hint.
    """
    lf = load(DATA / "good_tune.BBL")
    f = lf.flights[0]
    m = compute_flight_metrics(f)
    findings = diagnose(m, f.config)
    report = render_fallback_narrative(findings, m)
    for item in report.items:
        for line in item.cli_diff:
            assert line.startswith("#"), f"unvalidated CLI diff line must be a comment, got: {line}"


def test_fallback_uses_supplied_validated_cli_diff():
    lf = load(DATA / "good_tune.BBL")
    f = lf.flights[0]
    m = compute_flight_metrics(f)
    findings = diagnose(m, f.config)
    recommended = [x for x in findings if x.recommended]
    assert recommended, "expected at least one recommended finding on this log"
    target = recommended[0]
    diff_map = {target.id: ["set p_roll = 40"]}
    report = render_fallback_narrative(findings, m, cli_diff_by_finding=diff_map)
    item = next(i for i in report.items if i.finding_id == target.id)
    assert item.cli_diff == ["set p_roll = 40"]


def test_fallback_on_no_findings():
    from debrief.dsp.metrics import FlightMetrics

    empty_metrics = FlightMetrics(axes={}, throttle_chop_count=0, flat={})
    report = render_fallback_narrative([], empty_metrics)
    assert report.items == []
    assert "No findings" in report.summary
