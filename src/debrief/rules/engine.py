"""Combines config-only checks and metric-driven rules into one ordered
findings list, then selects up to `max_recommended` of them as the
"recommended changes" for the next test flight.

Selection rules, straight from the Phase 3 spec:
  - at most `max_recommended` (default 3) findings marked recommended
  - never two recommended findings that touch the same CLI key on the
    same axis (avoid double-adjusting e.g. roll P from two different
    findings in the same round)
  - informational findings, and findings with nothing actionable
    (no param_hints -- e.g. "go check your frame screws"), are never
    "recommended" even if severe; they stay visible in the ordered list.
"""
from __future__ import annotations

from debrief.dsp.metrics import FlightMetrics
from debrief.parse.header import HeaderConfig
from debrief.rules.catalog import run_metric_rules
from debrief.rules.config_checks import run_config_checks
from debrief.rules.flag import Finding, Severity


def diagnose(m: FlightMetrics, cfg: HeaderConfig, max_recommended: int = 3) -> list[Finding]:
    findings = run_config_checks(cfg) + run_metric_rules(m, cfg)
    findings.sort(key=lambda f: (f.severity.rank(), f.confidence.rank()), reverse=True)

    recommended_count = 0
    claimed_keys: set[tuple[str, str | None]] = set()
    for f in findings:
        if recommended_count >= max_recommended:
            break
        if f.severity == Severity.INFO or not f.param_hints:
            continue
        hint_keys = {(h.key_guess, h.axis) for h in f.param_hints}
        if hint_keys & claimed_keys:
            continue
        f.recommended = True
        claimed_keys |= hint_keys
        recommended_count += 1

    return findings
