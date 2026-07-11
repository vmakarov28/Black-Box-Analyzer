from pathlib import Path

from debrief.dsp import compute_flight_metrics
from debrief.llm.narrative import _build_prompt, _parse_response, build_narrative
from debrief.parse import load
from debrief.rules import diagnose

DATA = Path(__file__).parent / "data"


def _real_findings_and_metrics():
    lf = load(DATA / "good_tune.BBL")
    f = lf.flights[0]
    m = compute_flight_metrics(f)
    findings = diagnose(m, f.config)
    return findings, m, f.config


def test_build_prompt_renders_and_contains_no_raw_samples():
    findings, m, cfg = _real_findings_and_metrics()
    prompt = _build_prompt(findings, m, cfg, None)
    assert "Firmware:" in prompt
    assert "summary" in prompt
    # only aggregate metrics, never a raw per-sample array, should appear
    assert "gyroADC" not in prompt
    assert "loopIteration" not in prompt


def test_build_narrative_falls_back_when_ollama_unreachable():
    findings, m, cfg = _real_findings_and_metrics()
    report = build_narrative(findings, m, cfg, model="llama3.1:8b", host="http://127.0.0.1:1")
    assert report.generated_by.startswith("template-fallback")
    assert report.summary


def test_parse_response_never_fabricates_cli_diff_from_model_text():
    findings, m, cfg = _real_findings_and_metrics()
    recommended = [f for f in findings if f.recommended]
    assert recommended
    fake_model_output = {
        "summary": "Test summary.",
        "findings": [
            {
                "finding_id": f.id,
                "whats_wrong": "Something is wrong, maybe set p_roll = 999 to fix it.",
                "why_plain_english": "Because the gyro is noisy.",
                "test_flight_procedure": "Fly around a bit.",
            }
            for f in recommended
        ],
    }
    report = _parse_response(fake_model_output, findings, cli_diff_by_finding=None)
    for item in report.items:
        # even though the model's free text mentions a set command, cli_diff
        # itself must only ever come from fallback._cli_diff_for, never the model
        for line in item.cli_diff:
            assert line.startswith("#")


def test_parse_response_scrubs_fabricated_numeric_target_values():
    """Regression test for a real observed failure: llama3.1:8b wrote
    'raise D from 18 to 21' in test_flight_procedure during the Phase 4
    benchmark, despite the prompt instruction not to -- it computed a
    plausible-looking but unvalidated target value from the current value
    in the header summary. This must be caught even when the prompt rule
    is followed imperfectly.
    """
    findings, m, cfg = _real_findings_and_metrics()
    recommended = [f for f in findings if f.recommended]
    assert recommended
    target = recommended[0]
    fake_model_output = {
        "summary": "Test summary.",
        "findings": [
            {
                "finding_id": target.id,
                "whats_wrong": "The response is off.",
                "why_plain_english": "Because the gain is off.",
                "test_flight_procedure": "Raise D from 18 to 21 and fly again.",
            }
        ],
    }
    report = _parse_response(fake_model_output, findings, cli_diff_by_finding=None)
    item = next(i for i in report.items if i.finding_id == target.id)
    assert "18" not in item.test_flight_procedure
    assert "21" not in item.test_flight_procedure


def test_parse_response_allows_numbers_when_validated_diff_supplied():
    findings, m, cfg = _real_findings_and_metrics()
    recommended = [f for f in findings if f.recommended]
    assert recommended
    target = recommended[0]
    diff_map = {target.id: ["set d_roll = 21"]}
    fake_model_output = {
        "summary": "Test summary.",
        "findings": [
            {
                "finding_id": target.id,
                "whats_wrong": "The response is off.",
                "why_plain_english": "Because the gain is off.",
                "test_flight_procedure": "Apply the change from 18 to 21 shown above and fly again.",
            }
        ],
    }
    report = _parse_response(fake_model_output, findings, cli_diff_by_finding=diff_map)
    item = next(i for i in report.items if i.finding_id == target.id)
    assert "from 18 to 21" in item.test_flight_procedure  # allowed: a validated diff backs this finding


def test_parse_response_fills_missing_recommended_items_from_template():
    findings, m, cfg = _real_findings_and_metrics()
    recommended = [f for f in findings if f.recommended]
    assert recommended
    # model returns findings for none of them
    report = _parse_response({"summary": "ok", "findings": []}, findings, cli_diff_by_finding=None)
    assert len(report.items) == len(recommended)
