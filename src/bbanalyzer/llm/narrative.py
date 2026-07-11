"""Builds the LLM-backed NarrativeReport. The model receives only computed
metrics, triggered findings, and the log's config header -- never raw
samples (the caller is responsible for that; this module only ever touches
what's passed to it, and nothing here reads a dataframe).

Any failure at any stage (server unreachable, model missing, bad JSON,
timeout) falls back to the deterministic template renderer rather than
raising -- an LLM hiccup must never take down report generation.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from bbanalyzer.dsp.metrics import FlightMetrics
from bbanalyzer.llm import fallback as fallback_mod
from bbanalyzer.llm.ollama_client import DEFAULT_HOST, OllamaClient, OllamaUnavailableError
from bbanalyzer.llm.schema import FindingNarrative, NarrativeReport
from bbanalyzer.parse.header import HeaderConfig
from bbanalyzer.rules.flag import Confidence, Finding

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "narrative_prompt.j2"


def _header_summary(cfg: HeaderConfig) -> str:
    lines = [
        f"Firmware: {cfg.firmware_name} {'.'.join(str(v) for v in cfg.firmware_version) if cfg.firmware_version else '?'} on {cfg.target or 'unknown target'}",
        f"Craft name: {cfg.craft_name or 'unnamed'}",
        f"Gyro/PID loop rate: {cfg.gyro_rate_hz or '?'}Hz / {cfg.pid_loop_rate_hz or '?'}Hz",
        f"Simplified tuning active: {cfg.simplified_tuning_active}",
        f"RPM filter enabled: {cfg.rpm_filter_enabled}",
        f"Dynamic notch enabled: {cfg.dyn_notch_enabled}",
    ]
    for axis, gains in cfg.pid_gains.items():
        lines.append(f"{axis} PID: P={gains.P} I={gains.I} D={gains.D} F={gains.F}")
    return "\n".join(lines)


def _finding_dict(f: Finding, cli_diff_by_finding: dict[str, list[str]] | None) -> dict:
    diff = fallback_mod._cli_diff_for(f, cli_diff_by_finding)
    return {
        "finding_id": f.id,
        "title": f.title,
        "category": f.category,
        "severity": f.severity.value,
        "confidence": f.confidence.value,
        "axis": f.axis,
        "trigger_summary": f.trigger_summary,
        "rationale": f.rationale,
        "suggestion": f.suggestion,
        "recommended": f.recommended,
        "validated_cli_diff": diff if (cli_diff_by_finding and f.id in cli_diff_by_finding) else None,
    }


def _build_prompt(
    findings: list[Finding], m: FlightMetrics, cfg: HeaderConfig, cli_diff_by_finding: dict[str, list[str]] | None
) -> str:
    from jinja2 import Template

    template = Template(_PROMPT_PATH.read_text(encoding="utf-8"))
    recommended_ids = [f.id for f in findings if f.recommended]
    return template.render(
        header_summary=_header_summary(cfg),
        metrics_json=json.dumps(m.flat, indent=2, default=str),
        findings_json=json.dumps([_finding_dict(f, cli_diff_by_finding) for f in findings], indent=2),
        recommended_ids=json.dumps(recommended_ids),
    )


def _coerce_question(text: str, fallback_text: str) -> str:
    """Safety net for the "low confidence -> phrased as a question" rule:
    if the model didn't actually produce a question, fall back to the
    deterministic question phrasing for just this field rather than trust
    the model's compliance with the prompt instruction.
    """
    return text if "?" in text else fallback_text


# Safety net for the "never propose a specific numeric target value" prompt
# rule -- caught in practice during the Phase 4 benchmark: llama3.1:8b wrote
# "raise D from 18 to 21" in test_flight_procedure despite the instruction
# not to, computed from a current value it *was* given in the header
# summary. A prompt instruction alone isn't reliable enough for a number
# that could get typed into a real flight controller, so any field is
# checked and, if it looks like a fabricated target value, replaced with
# the deterministic template phrasing for that field instead.
_FABRICATED_VALUE_RE = re.compile(
    r"\bfrom\s+[-+]?\d+(\.\d+)?\s+to\s+[-+]?\d+(\.\d+)?\b"  # "from 18 to 21"
    r"|\bset\s+\w+\s*(=|to)\s*[-+]?\d+(\.\d+)?\b"  # "set d_roll = 21" / "set d_roll to 21"
    r"|\b\w+\s*=\s*[-+]?\d+(\.\d+)?\s*(->|→)\s*[-+]?\d+(\.\d+)?\b",  # "D=18 -> 21"
    re.IGNORECASE,
)


def _scrub_fabricated_values(text: str, fallback_text: str, has_validated_diff: bool) -> str:
    if has_validated_diff:
        return text  # a validated diff was supplied -- the model was allowed to quote it
    return fallback_text if _FABRICATED_VALUE_RE.search(text) else text


def _parse_response(
    parsed: dict, findings: list[Finding], cli_diff_by_finding: dict[str, list[str]] | None
) -> NarrativeReport:
    by_id = {f.id: f for f in findings}
    recommended = [f for f in findings if f.recommended]
    model_items = {item.get("finding_id"): item for item in parsed.get("findings", []) if isinstance(item, dict)}

    items: list[FindingNarrative] = []
    for f in recommended:
        as_question = f.confidence == Confidence.LOW
        model_item = model_items.get(f.id)
        if model_item is None:
            logger.warning("model omitted recommended finding %r; using template phrasing for it", f.id)
            fb = fallback_mod._finding_narrative(f, cli_diff_by_finding)
            items.append(fb)
            continue
        whats_wrong = str(model_item.get("whats_wrong", "")).strip() or f.title
        why = str(model_item.get("why_plain_english", "")).strip() or f.rationale.split(". ")[0]
        procedure = str(model_item.get("test_flight_procedure", "")).strip() or fallback_mod._procedure_for(f)
        if as_question:
            whats_wrong = _coerce_question(whats_wrong, fallback_mod._whats_wrong(f, True))
            why = _coerce_question(why, fallback_mod._why(f, True))

        has_diff = bool(cli_diff_by_finding and f.id in cli_diff_by_finding)
        whats_wrong = _scrub_fabricated_values(whats_wrong, fallback_mod._whats_wrong(f, as_question), has_diff)
        why = _scrub_fabricated_values(why, fallback_mod._why(f, as_question), has_diff)
        procedure = _scrub_fabricated_values(procedure, fallback_mod._procedure_for(f), has_diff)
        items.append(
            FindingNarrative(
                finding_id=f.id,
                title=f.title,
                whats_wrong=whats_wrong,
                why_plain_english=why,
                cli_diff=fallback_mod._cli_diff_for(f, cli_diff_by_finding),
                test_flight_procedure=procedure,
                is_question=as_question,
            )
        )

    summary = str(parsed.get("summary", "")).strip() or fallback_mod._summary(findings, None)
    others = [f"{f.title} ({f.severity.value}/{f.confidence.value})" for f in findings if not f.recommended]
    return NarrativeReport(summary=summary, items=items, other_observations=others, generated_by="llm")


def build_narrative(
    findings: list[Finding],
    m: FlightMetrics,
    cfg: HeaderConfig,
    model: str,
    cli_diff_by_finding: dict[str, list[str]] | None = None,
    host: str = DEFAULT_HOST,
) -> NarrativeReport:
    try:
        client = OllamaClient(host=host)
        if not client.is_available():
            raise OllamaUnavailableError(f"Ollama server not reachable at {host}")
        if not client.has_model(model):
            raise OllamaUnavailableError(f"model {model!r} not pulled locally (try: ollama pull {model})")
        prompt = _build_prompt(findings, m, cfg, cli_diff_by_finding)
        parsed = client.generate_json(model, prompt)
        report = _parse_response(parsed, findings, cli_diff_by_finding)
        meta = parsed.get("_meta")
        if meta is not None:
            report.generated_by = f"llm:{meta.model} ({meta.total_duration_s:.1f}s, {meta.eval_count} tokens)"
        return report
    except Exception as e:
        logger.warning("LLM narrative generation failed (%s); falling back to templates", e)
        report = fallback_mod.render_fallback_narrative(findings, m, cli_diff_by_finding)
        report.generated_by = f"template-fallback (LLM unavailable: {e})"
        return report
