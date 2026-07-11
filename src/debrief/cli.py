"""CLI entrypoint: debrief analyze mylog.bbl -o report.html

Everything after parsing is a thin orchestration of the independently
testable layers (parse -> dsp -> rules -> llm/fallback -> report/tune).
This module contains no diagnostic logic of its own.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from debrief import __version__
from debrief.dsp import compute_flight_metrics
from debrief.llm.fallback import render_fallback_narrative
from debrief.llm.ollama_client import DEFAULT_HOST
from debrief.parse import LogParseError, load
from debrief.parse.loader import Flight, LogFile
from debrief.report import render_compare_report, render_report
from debrief.rules import diagnose


class CLIError(Exception):
    """A user-facing, non-programming-error CLI failure. main() catches
    exactly this, prints it, and returns exit code 1 -- every other
    exception is a real bug and should propagate with a traceback.
    """


def _select_flight(lf: LogFile, index: int | None) -> Flight:
    if not lf.flights:
        reasons = "; ".join(f"#{s['index']}: {s['reason']}" for s in lf.skipped)
        raise CLIError(
            f"No usable flight data in {lf.path} (all {lf.n_declared_logs} segment(s) empty/corrupt). {reasons}"
        )
    if index is not None:
        match = next((f for f in lf.flights if f.index == index), None)
        if match is None:
            available = [f.index for f in lf.flights]
            raise CLIError(f"--flight-index {index} not found in this file; available: {available}")
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


def _load_and_select(path: Path, flight_index: int | None) -> Flight:
    try:
        lf = load(path)
    except LogParseError as e:
        raise CLIError(str(e)) from e
    flight = _select_flight(lf, flight_index)
    for w in flight.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return flight


def cmd_compare(args: argparse.Namespace) -> int:
    before_path, after_path = args.compare
    before_flight = _load_and_select(before_path, None)
    after_flight = _load_and_select(after_path, None)
    before_metrics = compute_flight_metrics(before_flight)
    after_metrics = compute_flight_metrics(after_flight)

    from debrief.tune.compare import compare_flights

    deltas = compare_flights(before_metrics, after_metrics)
    out = render_compare_report(
        before_metrics, after_metrics, deltas,
        before_label=before_path.name, after_label=after_path.name,
        output_path=args.output,
    )
    print(f"Compare report written to {out}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    if args.compare:
        return cmd_compare(args)

    flight = _load_and_select(args.log, args.flight_index)
    metrics = compute_flight_metrics(flight)
    findings = diagnose(metrics, flight.config)

    if args.no_llm:
        narrative = render_fallback_narrative(findings, metrics)
    else:
        from debrief.llm.narrative import build_narrative

        narrative = build_narrative(findings, metrics, flight.config, model=args.model, host=args.ollama_host)

    tune_plan = None
    tune_warnings: list[str] = []
    rates_report = None

    if args.config_diff or args.tune_output_dir:
        from debrief.tune import (
            check_diff_vs_header_agreement,
            from_header,
            generate_tune_plan,
            parse_cli_diff_file,
            write_tune_files,
        )

        if args.config_diff:
            tune_cfg = parse_cli_diff_file(args.config_diff)
            tune_warnings = check_diff_vs_header_agreement(tune_cfg, flight.config)
            for w in tune_warnings:
                print(f"warning: {w}", file=sys.stderr)
        else:
            tune_cfg = from_header(flight.config)
            tune_warnings = [
                "No --config-diff supplied; using the blackbox log's own header as the source "
                "config (less reliable than a fresh CLI diff -- it reflects the tune as flown, "
                "which may already differ from your current settings)."
            ]

        tune_plan = generate_tune_plan(
            findings, tune_cfg,
            loop_rate_hz=flight.config.pid_loop_rate_hz,
            disable_simplified_first=args.allow_disable_simplified_tuning,
            allow_rates=args.rates,
        )
        if args.tune_output_dir:
            written = write_tune_files(tune_plan, args.tune_output_dir)
            print(f"Tune files written to {args.tune_output_dir}: {', '.join(p.name for p in written.values())}")

    if args.rates:
        from debrief.tune.rates_report import build_rates_report

        rates_report = build_rates_report(metrics, flight.config)

    out = render_report(
        flight, metrics, findings, narrative, args.output,
        log_filename=str(args.log),
        version_mismatch_warning=" ".join(tune_warnings) if tune_warnings else None,
        tune_plan=tune_plan,
        tune_warnings=tune_warnings,
        rates_report=rates_report,
    )
    print(f"Report written to {out}")
    print(f"({len(findings)} findings, {sum(1 for f in findings if f.recommended)} recommended, narrative: {narrative.generated_by})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="debrief", description="Local Betaflight blackbox log analyzer")
    p.add_argument("--version", action="version", version=f"debrief {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a blackbox log and write an HTML report")
    analyze.add_argument("log", type=Path, nargs="?", help="Path to a .bbl/.bfl log file (omit when using --compare)")
    analyze.add_argument("-o", "--output", type=Path, default=Path("report.html"))
    analyze.add_argument("--flight-index", type=int, default=None, help="Which embedded flight to analyze (default: longest)")
    analyze.add_argument("--no-llm", action="store_true", help="Skip the local LLM; render the report from templates only")
    analyze.add_argument("--model", default="llama3.1:8b-instruct-q4_K_M", help="Ollama model tag for the narrative")
    analyze.add_argument("--ollama-host", default=DEFAULT_HOST)
    analyze.add_argument("--config-diff", type=Path, default=None, help="Pilot's current CLI diff/dump file (Phase 6 tune generator source config)")
    analyze.add_argument("--tune-output-dir", type=Path, default=None, help="Write stageN.txt/rollback.txt/changelog.md here")
    analyze.add_argument(
        "--allow-disable-simplified-tuning", action="store_true",
        help="If simplified tuning is active, allow explicitly disabling it (stage 1) so raw PID/filter "
        "keys can be used instead of slider translation",
    )
    analyze.add_argument("--rates", action="store_true", help="Include a rates-usage report (preference-based, never auto-recommended)")
    analyze.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), type=Path, default=None, help="Compare two logs instead of analyzing one")
    analyze.set_defaults(func=cmd_analyze)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "analyze" and not args.compare and args.log is None:
        parser.error("the log argument is required unless --compare is given")
    try:
        return args.func(args)
    except CLIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
