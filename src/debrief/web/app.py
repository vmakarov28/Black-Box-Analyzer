"""Local web UI: upload a log in a browser, get the same report the CLI
produces, with download buttons -- no terminal required. Talks to nothing
but this machine: file uploads are handled entirely in-process (a
TemporaryDirectory that's gone before the response is sent), and the only
outbound call anywhere in this module is the same localhost-only Ollama
request narrative.py already makes for the CLI path.

Deliberately reuses pipeline.run_analysis()/select_flight() and
report.render_report_html()/render_compare_report_html() rather than
re-implementing any of that -- this file is routing and HTTP concerns
only, no diagnostic logic.
"""
from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from flask import Flask, Response, render_template, request, url_for

from debrief.llm.ollama_client import DEFAULT_HOST, OllamaClient
from debrief.parse import LogParseError, load
from debrief.pipeline import (
    DEFAULT_MODEL,
    FlightIndexNotFoundError,
    NoUsableFlightError,
    run_analysis,
    select_flight,
)
from debrief.report import render_compare_report_html, render_report_html
from debrief.theme import THEME_CSS, THEME_SCRIPT_HEAD, THEME_SCRIPT_SYNC_LABEL
from debrief.tune.output import changelog_text, rollback_text, stage_text

MAX_UPLOAD_BYTES = 250 * 1024 * 1024  # a long multi-flight log can be tens of MB; generous headroom


def _data_uri(text: str, mime: str = "text/plain") -> str:
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"data:{mime};charset=utf-8;base64,{b64}"


def _build_tune_downloads(tune_plan) -> dict:
    return {
        "stages": [_data_uri(stage_text(i, stage)) for i, stage in enumerate(tune_plan.stages, start=1)],
        "rollback": _data_uri(rollback_text(tune_plan.rollback)),
        "changelog": _data_uri(changelog_text(tune_plan), mime="text/markdown"),
    }


def create_app(default_model: str = DEFAULT_MODEL, ollama_host: str = DEFAULT_HOST) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

    def _theme_kwargs(**extra):
        return dict(
            theme_css=THEME_CSS,
            theme_script_head=THEME_SCRIPT_HEAD,
            theme_script_sync=THEME_SCRIPT_SYNC_LABEL,
            home_url=url_for("index"),
            **extra,
        )

    def _error_page(message: str, status: int = 400) -> tuple[str, int]:
        return render_template("error.html.j2", **_theme_kwargs(message=message)), status

    @app.get("/")
    def index():
        client = OllamaClient(host=ollama_host)
        ollama_up = client.is_available()
        models = client.list_models() if ollama_up else []
        return render_template(
            "upload.html.j2",
            **_theme_kwargs(
                ollama_up=ollama_up,
                models=models,
                default_model=default_model if default_model in models else (models[0] if models else default_model),
            ),
        )

    @app.post("/analyze")
    def analyze():
        log_file = request.files.get("log_file")
        if log_file is None or log_file.filename == "":
            return _error_page("No log file selected. Choose a .bbl/.bfl file and try again.")

        with tempfile.TemporaryDirectory(prefix="debrief_web_") as tmp:
            tmp_path = Path(tmp) / Path(log_file.filename).name
            log_file.save(tmp_path)
            try:
                lf = load(tmp_path)
            except LogParseError as e:
                return _error_page(str(e))

            flight_index_raw = (request.form.get("flight_index") or "").strip()
            flight_index = int(flight_index_raw) if flight_index_raw else None
            try:
                flight, messages = select_flight(lf, flight_index)
            except (NoUsableFlightError, FlightIndexNotFoundError) as e:
                return _error_page(str(e))

            no_llm = request.form.get("no_llm") == "on" or not request.form.get("model")
            model = request.form.get("model") or default_model
            rates = request.form.get("rates") == "on"
            allow_disable = request.form.get("allow_disable_simplified") == "on"

            config_diff_text = None
            diff_file = request.files.get("config_diff_file")
            if diff_file is not None and diff_file.filename:
                config_diff_text = diff_file.read().decode("utf-8", errors="replace")

            result = run_analysis(
                flight,
                no_llm=no_llm,
                model=model,
                ollama_host=ollama_host,
                config_diff_text=config_diff_text,
                allow_disable_simplified_tuning=allow_disable,
                rates=rates,
            )

            tune_downloads = _build_tune_downloads(result.tune_plan) if result.tune_plan is not None else None
            all_warnings = messages + result.tune_warnings

            html = render_report_html(
                flight, result.metrics, result.findings, result.narrative,
                log_filename=log_file.filename,
                version_mismatch_warning=" ".join(all_warnings) if all_warnings else None,
                tune_plan=result.tune_plan,
                tune_warnings=result.tune_warnings,
                rates_report=result.rates_report,
                tune_downloads=tune_downloads,
                home_url=url_for("index"),
                download_filename=f"debrief-{Path(log_file.filename).stem}.html",
            )
            return Response(html, mimetype="text/html")

    @app.post("/compare")
    def compare():
        before_file = request.files.get("before_file")
        after_file = request.files.get("after_file")
        if before_file is None or before_file.filename == "" or after_file is None or after_file.filename == "":
            return _error_page("Choose both a 'before' and an 'after' log file.")

        from debrief.dsp import compute_flight_metrics
        from debrief.tune.compare import compare_flights

        with tempfile.TemporaryDirectory(prefix="debrief_web_") as tmp:
            results = []
            for f in (before_file, after_file):
                p = Path(tmp) / Path(f.filename).name
                f.save(p)
                try:
                    lf = load(p)
                    flight, _ = select_flight(lf, None)
                except (LogParseError, NoUsableFlightError, FlightIndexNotFoundError) as e:
                    return _error_page(f"{f.filename}: {e}")
                results.append((flight, compute_flight_metrics(flight)))

            (before_flight, before_metrics), (after_flight, after_metrics) = results
            deltas = compare_flights(before_metrics, after_metrics)
            html = render_compare_report_html(
                before_metrics, after_metrics, deltas,
                before_label=before_file.filename, after_label=after_file.filename,
                home_url=url_for("index"),
                download_filename="debrief-compare.html",
            )
            return Response(html, mimetype="text/html")

    @app.errorhandler(413)
    def too_large(_e):
        return _error_page(f"File too large -- limit is {MAX_UPLOAD_BYTES // (1024*1024)}MB.", status=413)

    @app.errorhandler(500)
    def internal_error(e):
        return _error_page(f"Something went wrong analyzing this log: {e}", status=500)

    return app
