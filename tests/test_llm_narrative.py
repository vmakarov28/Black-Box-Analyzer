from pathlib import Path

from bbanalyzer.dsp import compute_flight_metrics
from bbanalyzer.llm.narrative import _build_prompt, _parse_response, build_narrative
from bbanalyzer.parse import load
from bbanalyzer.rules import diagnose

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


def test_parse_response_fills_missing_recommended_items_from_template():
    findings, m, cfg = _real_findings_and_metrics()
    recommended = [f for f in findings if f.recommended]
    assert recommended
    # model returns findings for none of them
    report = _parse_response({"summary": "ok", "findings": []}, findings, cli_diff_by_finding=None)
    assert len(report.items) == len(recommended)
