"""CLI entrypoint: debrief analyze mylog.bbl -o report.html

Everything after parsing is a thin orchestration of the independently
testable layers (parse -> pipeline -> report/tune). This module contains
no diagnostic logic of its own -- see pipeline.py for the shared
analysis sequencing also used by the local web app.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from debrief import __version__
from debrief.llm.ollama_client import DEFAULT_HOST
from debrief.parse import LogParseError, load
from debrief.parse.loader import Flight
from debrief.pipeline import (
    DEFAULT_MODEL,
    FlightIndexNotFoundError,
    NoUsableFlightError,
    run_analysis,
    select_flight,
)
from debrief.report import render_compare_report, render_report


class CLIError(Exception):
    """A user-facing, non-programming-error CLI failure. main() catches
    exactly this, prints it, and returns exit code 1 -- every other
    exception is a real bug and should propagate with a traceback.
    """


def _load_and_select(path: Path, flight_index: int | None) -> Flight:
    try:
        lf = load(path)
    except LogParseError as e:
        raise CLIError(str(e)) from e
    try:
        flight, messages = select_flight(lf, flight_index)
    except (NoUsableFlightError, FlightIndexNotFoundError) as e:
        raise CLIError(str(e)) from e
    for m in messages:
        print(m, file=sys.stderr)
    return flight


def cmd_compare(args: argparse.Namespace) -> int:
    before_path, after_path = args.compare
    before_flight = _load_and_select(before_path, None)
    after_flight = _load_and_select(after_path, None)

    from debrief.dsp import compute_flight_metrics
    from debrief.tune.compare import compare_flights

    before_metrics = compute_flight_metrics(before_flight)
    after_metrics = compute_flight_metrics(after_flight)
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

    config_diff_text = None
    if args.config_diff:
        config_diff_text = args.config_diff.read_text(encoding="utf-8", errors="replace")

    result = run_analysis(
        flight,
        no_llm=args.no_llm,
        model=args.model,
        ollama_host=args.ollama_host,
        config_diff_text=config_diff_text,
        use_header_as_tune_source=bool(args.tune_output_dir) and not args.config_diff,
        allow_disable_simplified_tuning=args.allow_disable_simplified_tuning,
        rates=args.rates,
    )
    for w in result.tune_warnings:
        print(f"warning: {w}", file=sys.stderr)

    if args.tune_output_dir and result.tune_plan is not None:
        from debrief.tune import write_tune_files

        written = write_tune_files(result.tune_plan, args.tune_output_dir)
        print(f"Tune files written to {args.tune_output_dir}: {', '.join(p.name for p in written.values())}")

    out = render_report(
        flight, result.metrics, result.findings, result.narrative, args.output,
        log_filename=str(args.log),
        version_mismatch_warning=" ".join(result.tune_warnings) if result.tune_warnings else None,
        tune_plan=result.tune_plan,
        tune_warnings=result.tune_warnings,
        rates_report=result.rates_report,
    )
    print(f"Report written to {out}")
    print(
        f"({len(result.findings)} findings, "
        f"{sum(1 for f in result.findings if f.recommended)} recommended, "
        f"narrative: {result.narrative.generated_by})"
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        from debrief.web.app import create_app
    except ImportError as e:
        raise CLIError(
            "the web UI needs Flask -- install it with: pip install 'debrief[web]'"
        ) from e

    app = create_app(default_model=args.model, ollama_host=args.ollama_host)
    url = f"http://{args.host}:{args.port}"
    print(f"Debrief running at {url} (Ctrl+C to stop)")
    if args.host not in ("127.0.0.1", "localhost"):
        print(f"warning: bound to {args.host}, not just localhost -- reachable from other devices on your network", file=sys.stderr)
    app.run(host=args.host, port=args.port, debug=False)
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
    analyze.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model tag for the narrative")
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

    serve = sub.add_parser("serve", help="Run the local web UI (upload/download buttons, no terminal commands needed)")
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1, this machine only)")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--model", default=DEFAULT_MODEL, help="Default Ollama model tag offered in the UI")
    serve.add_argument("--ollama-host", default=DEFAULT_HOST)
    serve.set_defaults(func=cmd_serve)

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
