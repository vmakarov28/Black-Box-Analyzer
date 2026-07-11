"""CLI entrypoint: bbanalyzer analyze mylog.bbl -o report.html

Everything after parsing is a thin orchestration of the independently
testable layers (parse -> dsp -> rules -> llm/fallback -> report). This
module contains no diagnostic logic of its own.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bbanalyzer import __version__
from bbanalyzer.dsp import compute_flight_metrics
from bbanalyzer.llm.fallback import render_fallback_narrative
from bbanalyzer.llm.ollama_client import DEFAULT_HOST
from bbanalyzer.parse import LogParseError, load
from bbanalyzer.parse.loader import Flight, LogFile
from bbanalyzer.report import render_report
from bbanalyzer.rules import diagnose


def _select_flight(lf: LogFile, index: int | None) -> Flight:
    if not lf.flights:
        reasons = "; ".join(f"#{s['index']}: {s['reason']}" for s in lf.skipped)
        raise SystemExit(
            f"No usable flight data in {lf.path} (all {lf.n_declared_logs} segment(s) empty/corrupt). {reasons}"
        )
    if index is not None:
        match = next((f for f in lf.flights if f.index == index), None)
        if match is None:
            available = [f.index for f in lf.flights]
            raise SystemExit(f"--flight-index {index} not found in this file; available: {available}")
        return match
    if len(lf.flights) > 1:
        chosen = max(lf.flights, key=lambda f: f.duration_s)
        summary = ", ".join(f"#{f.index} ({f.duration_s:.1f}s)" for f in lf.flights)
        print(
            f"Multiple flights found ({summary}); using #{chosen.index} (longest). "
            f"Pass --flight-index to pick another.",
            file=sys.stderr,
        )
        return chosen
    return lf.flights[0]


def cmd_analyze(args: argparse.Namespace) -> int:
    try:
        lf = load(args.log)
    except LogParseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    flight = _select_flight(lf, args.flight_index)
    for w in flight.warnings:
        print(f"warning: {w}", file=sys.stderr)

    metrics = compute_flight_metrics(flight)
    findings = diagnose(metrics, flight.config)

    if args.no_llm:
        narrative = render_fallback_narrative(findings, metrics)
    else:
        from bbanalyzer.llm.narrative import build_narrative

        narrative = build_narrative(findings, metrics, flight.config, model=args.model, host=args.ollama_host)

    out = render_report(flight, metrics, findings, narrative, args.output, log_filename=str(args.log))
    print(f"Report written to {out}")
    print(f"({len(findings)} findings, {sum(1 for f in findings if f.recommended)} recommended, narrative: {narrative.generated_by})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bbanalyzer", description="Local Betaflight blackbox log analyzer")
    p.add_argument("--version", action="version", version=f"bbanalyzer {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a blackbox log and write an HTML report")
    analyze.add_argument("log", type=Path, help="Path to a .bbl/.bfl log file")
    analyze.add_argument("-o", "--output", type=Path, default=Path("report.html"))
    analyze.add_argument("--flight-index", type=int, default=None, help="Which embedded flight to analyze (default: longest)")
    analyze.add_argument("--no-llm", action="store_true", help="Skip the local LLM; render the report from templates only")
    analyze.add_argument("--model", default="llama3.1:8b-instruct-q4_K_M", help="Ollama model tag for the narrative")
    analyze.add_argument("--ollama-host", default=DEFAULT_HOST)
    analyze.set_defaults(func=cmd_analyze)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
