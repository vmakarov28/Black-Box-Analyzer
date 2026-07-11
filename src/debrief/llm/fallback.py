"""REQUIRED FALLBACK (--no-llm): renders the exact same NarrativeReport
shape as narrative.py, purely from string templates -- no model, no
network, works on any machine with nothing but this repo installed.

This is not a lesser option kept around for offline demos -- it's the
floor every LLM output is measured against, and the CLI defaults to it
whenever no local model is available.
"""
from __future__ import annotations

from debrief.dsp.metrics import FlightMetrics
from debrief.llm.schema import FindingNarrative, NarrativeReport
from debrief.rules.flag import Confidence, Finding, Severity

_TEST_PROCEDURE_BY_CATEGORY = {
    "pid": (
        "Make only this change, save, then fly a short (3-5 min) test flight repeating the "
        "same kind of stick movements as this log (sharp stick snaps and a few throttle chops "
        "on {axis}). Re-run this tool on the new log and compare against this one before "
        "trying a second change."
    ),
    "filtering": (
        "Make only this change, save, then fly a short test flight including some throttle "
        "punches and hovering at a few different throttle levels, so the noise heatmap has "
        "enough data across the throttle range. Compare the new noise heatmap against this one."
    ),
    "rpm_filter": (
        "Make only this change, save, then fly a short test flight covering low, mid, and high "
        "throttle. Check the RPM-linked noise finding on the new log to confirm it actually "
        "dropped."
    ),
    "hardware": (
        "This is a physical/hardware check, not a CLI change -- inspect it on the bench before "
        "your next flight rather than testing it in the air."
    ),
    "config": (
        "Review this before your next flight; if you change it, treat it like any other single "
        "change -- one test flight, then compare."
    ),
}
_DEFAULT_PROCEDURE = (
    "Make only this one change, then fly a short test flight and re-run this tool to confirm "
    "it had the intended effect before making another change."
)


def _procedure_for(finding: Finding) -> str:
    template = _TEST_PROCEDURE_BY_CATEGORY.get(finding.category, _DEFAULT_PROCEDURE)
    return template.format(axis=finding.axis or "all axes")


def _whats_wrong(finding: Finding, as_question: bool) -> str:
    if as_question:
        return f"{finding.title}. Is this actually a problem, or expected for this setup?"
    return finding.title


def _why(finding: Finding, as_question: bool) -> str:
    # first sentence of rationale, kept short -- "one sentence a hobbyist understands"
    first_sentence = finding.rationale.split(". ")[0].strip().rstrip(".") + "."
    if as_question:
        return f"Possibly because {first_sentence[0].lower()}{first_sentence[1:]} Worth checking?"
    return first_sentence


def _cli_diff_for(finding: Finding, cli_diff_by_finding: dict[str, list[str]] | None) -> list[str]:
    if cli_diff_by_finding and finding.id in cli_diff_by_finding:
        return cli_diff_by_finding[finding.id]
    if not finding.param_hints:
        return []
    # No validated tune-generator diff was supplied -- describe the direction only,
    # explicitly marked as unvalidated, never a fabricated `set` command.
    hints = ", ".join(f"{h.key_guess} ({h.direction})" for h in finding.param_hints)
    return [f"# not yet validated against your config -- run the tune generator for an exact diff: {hints}"]


def _finding_narrative(finding: Finding, cli_diff_by_finding: dict[str, list[str]] | None) -> FindingNarrative:
    as_question = finding.confidence == Confidence.LOW
    return FindingNarrative(
        finding_id=finding.id,
        title=finding.title,
        whats_wrong=_whats_wrong(finding, as_question),
        why_plain_english=_why(finding, as_question),
        cli_diff=_cli_diff_for(finding, cli_diff_by_finding),
        test_flight_procedure=_procedure_for(finding),
        is_question=as_question,
    )


def _summary(findings: list[Finding], m: FlightMetrics) -> str:
    if not findings:
        return "No findings triggered -- nothing in this flight's metrics crossed a diagnostic threshold."
    n_critical = sum(1 for f in findings if f.severity == Severity.CRITICAL)
    n_warning = sum(1 for f in findings if f.severity == Severity.WARNING)
    n_recommended = sum(1 for f in findings if f.recommended)
    parts = [f"{len(findings)} finding(s) from this flight"]
    if n_critical:
        parts.append(f"{n_critical} critical")
    if n_warning:
        parts.append(f"{n_warning} warning-level")
    summary = ", ".join(parts) + f". {n_recommended} recommended for the next test flight."
    return summary


def render_fallback_narrative(
    findings: list[Finding],
    m: FlightMetrics,
    cli_diff_by_finding: dict[str, list[str]] | None = None,
) -> NarrativeReport:
    recommended = [f for f in findings if f.recommended]
    others = [f for f in findings if not f.recommended]
    return NarrativeReport(
        summary=_summary(findings, m),
        items=[_finding_narrative(f, cli_diff_by_finding) for f in recommended],
        other_observations=[f"{f.title} ({f.severity.value}/{f.confidence.value})" for f in others],
        generated_by="template-fallback",
    )
