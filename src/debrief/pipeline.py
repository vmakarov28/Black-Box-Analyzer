"""Shared orchestration between the two front ends (cli.py, web/app.py):
loaded Flight -> metrics -> findings -> narrative -> optional tune plan /
rates report. Neither front end should re-implement this sequencing --
they differ only in how they get input (file args vs HTTP upload) and
what they do with the output (write to disk vs stream an HTTP response).
"""
from __future__ import annotations

from dataclasses import dataclass

from debrief.dsp import compute_flight_metrics
from debrief.dsp.metrics import FlightMetrics
from debrief.llm.fallback import render_fallback_narrative
from debrief.llm.ollama_client import DEFAULT_HOST
from debrief.llm.schema import NarrativeReport
from debrief.parse.loader import Flight, LogFile
from debrief.rules import diagnose
from debrief.rules.flag import Finding
from debrief.tune.generator import TuneGeneratorResult
from debrief.tune.rates_report import AxisRatesInfo

DEFAULT_MODEL = "llama3.1:8b-instruct-q4_K_M"


class NoUsableFlightError(Exception):
    """Every embedded segment in this file was empty/corrupt."""


class FlightIndexNotFoundError(Exception):
    pass


def select_flight(lf: LogFile, index: int | None) -> tuple[Flight, list[str]]:
    """Returns (flight, info_messages). Never prints -- the caller decides
    whether messages go to stderr, an HTTP response, or nowhere.
    """
    if not lf.flights:
        reasons = "; ".join(f"#{s['index']}: {s['reason']}" for s in lf.skipped)
        raise NoUsableFlightError(
            f"No usable flight data in {lf.path} (all {lf.n_declared_logs} segment(s) empty/corrupt). {reasons}"
        )
    messages: list[str] = []
    if index is not None:
        match = next((f for f in lf.flights if f.index == index), None)
        if match is None:
            available = [f.index for f in lf.flights]
            raise FlightIndexNotFoundError(f"flight index {index} not found in this file; available: {available}")
        flight = match
    elif len(lf.flights) > 1:
        flight = max(lf.flights, key=lambda f: f.duration_s)
        summary = ", ".join(f"#{f.index} ({f.duration_s:.1f}s)" for f in lf.flights)
        messages.append(f"Multiple flights found ({summary}); using #{flight.index} (longest).")
    else:
        flight = lf.flights[0]
    messages.extend(f"warning: {w}" for w in flight.warnings)
    return flight, messages


@dataclass
class AnalysisResult:
    metrics: FlightMetrics
    findings: list[Finding]
    narrative: NarrativeReport
    tune_plan: TuneGeneratorResult | None
    tune_warnings: list[str]
    rates_report: list[AxisRatesInfo] | None


def run_analysis(
    flight: Flight,
    *,
    no_llm: bool = False,
    model: str = DEFAULT_MODEL,
    ollama_host: str = DEFAULT_HOST,
    config_diff_text: str | None = None,
    use_header_as_tune_source: bool = False,
    allow_disable_simplified_tuning: bool = False,
    rates: bool = False,
) -> AnalysisResult:
    """Pure with respect to the filesystem (aside from load() having already
    happened to produce `flight`) -- no writes, no subprocess calls beyond
    whatever build_narrative's Ollama HTTP call does.
    """
    metrics = compute_flight_metrics(flight)
    findings = diagnose(metrics, flight.config)

    if no_llm:
        narrative = render_fallback_narrative(findings, metrics)
    else:
        from debrief.llm.narrative import build_narrative

        narrative = build_narrative(findings, metrics, flight.config, model=model, host=ollama_host)

    tune_plan = None
    tune_warnings: list[str] = []
    if config_diff_text is not None or use_header_as_tune_source:
        from debrief.tune import (
            check_diff_vs_header_agreement,
            from_header,
            generate_tune_plan,
            parse_cli_diff,
        )

        if config_diff_text is not None:
            tune_cfg = parse_cli_diff(config_diff_text)
            tune_warnings = check_diff_vs_header_agreement(tune_cfg, flight.config)
        else:
            tune_cfg = from_header(flight.config)
            tune_warnings = [
                "No CLI diff supplied; using the blackbox log's own header as the source config "
                "(less reliable than a fresh CLI diff -- it reflects the tune as flown, which may "
                "already differ from your current settings)."
            ]

        tune_plan = generate_tune_plan(
            findings, tune_cfg,
            loop_rate_hz=flight.config.pid_loop_rate_hz,
            disable_simplified_first=allow_disable_simplified_tuning,
            allow_rates=rates,
        )

    rates_report = None
    if rates:
        from debrief.tune.rates_report import build_rates_report

        rates_report = build_rates_report(metrics, flight.config)

    return AnalysisResult(
        metrics=metrics,
        findings=findings,
        narrative=narrative,
        tune_plan=tune_plan,
        tune_warnings=tune_warnings,
        rates_report=rates_report,
    )
