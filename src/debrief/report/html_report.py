"""Single self-contained HTML report: all plots and styles inlined, zero
network requests when opened. The only inputs are the outputs of the
other layers (loader.Flight, dsp.FlightMetrics, rules Findings,
llm.NarrativeReport) -- this module does no diagnosis of its own.

render_report_html() does the pure rendering (str in, str out -- no
filesystem I/O), so both the CLI (render_report(), which writes it to
disk) and the local web app (which streams the string straight back in
an HTTP response) share one rendering path.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from jinja2 import Template

from debrief import __version__
from debrief.dsp.metrics import FlightMetrics
from debrief.llm.schema import NarrativeReport
from debrief.parse.loader import Flight
from debrief.report.plots import (
    plot_filter_and_propwash_summary,
    plot_noise_heatmaps,
    plot_step_responses,
)
from debrief.rules.flag import Finding
from debrief.theme import THEME_CSS, THEME_SCRIPT_HEAD, THEME_SCRIPT_SYNC_LABEL

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "report.html.j2"


def render_report_html(
    flight: Flight,
    metrics: FlightMetrics,
    findings: list[Finding],
    narrative: NarrativeReport,
    log_filename: str = "",
    version_mismatch_warning: str | None = None,
    compare: dict | None = None,
    tune_plan=None,
    tune_warnings: list[str] | None = None,
    rates_report: list | None = None,
    tune_downloads: dict | None = None,
    home_url: str | None = None,
    download_filename: str | None = None,
) -> str:
    cfg = flight.config
    template = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))

    firmware_line = f"{cfg.firmware_name or 'unknown firmware'} {'.'.join(str(v) for v in cfg.firmware_version) if cfg.firmware_version else ''} on {cfg.target or 'unknown target'}"
    tune_downloads = tune_downloads or {}

    return template.render(
        theme_css=THEME_CSS,
        theme_script_head=THEME_SCRIPT_HEAD,
        theme_script_sync=THEME_SCRIPT_SYNC_LABEL,
        home_url=home_url,
        download_filename=download_filename,
        craft_name=cfg.craft_name or "Unnamed craft",
        firmware_line=firmware_line,
        log_filename=log_filename or flight.header.get("_source", ""),
        generated_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        version_mismatch_warning=version_mismatch_warning,
        duration_s=f"{flight.duration_s:.1f}",
        n_frames=flight.n_frames,
        sample_rate_hz=f"{flight.sample_rate_hz:.0f}" if flight.sample_rate_hz else "?",
        throttle_chop_count=metrics.throttle_chop_count,
        n_findings=len(findings),
        n_recommended=sum(1 for f in findings if f.recommended),
        narrative_summary=narrative.summary,
        narrative_items=[
            {
                "title": item.title,
                "severity": next((f.severity.value for f in findings if f.id == item.finding_id), "info"),
                "confidence": next((f.confidence.value for f in findings if f.id == item.finding_id), "low"),
                "is_question": item.is_question,
                "whats_wrong": item.whats_wrong,
                "why_plain_english": item.why_plain_english,
                "cli_diff": item.cli_diff,
                "test_flight_procedure": item.test_flight_procedure,
            }
            for item in narrative.items
        ],
        other_observations=narrative.other_observations,
        step_response_plot=plot_step_responses(metrics),
        noise_heatmap_plot=plot_noise_heatmaps(metrics),
        filter_propwash_plot=plot_filter_and_propwash_summary(metrics),
        compare=compare,
        all_findings=[
            {
                "severity": f.severity.value,
                "confidence": f.confidence.value,
                "axis": f.axis,
                "title": f.title,
                "trigger_summary": f.trigger_summary,
            }
            for f in findings
        ],
        raw_header=flight.header,
        version=__version__,
        generated_by=narrative.generated_by,
        tune_plan=(
            {
                "stages": tune_plan.stages,
                "rejected": tune_plan.rejected,
                "warnings": tune_warnings or [],
                "source": tune_plan.source,
                "simplified_tuning_active": tune_plan.simplified_tuning_active,
                "downloads": tune_downloads.get("stages"),
                "rollback_download": tune_downloads.get("rollback"),
                "changelog_download": tune_downloads.get("changelog"),
            }
            if tune_plan is not None
            else None
        ),
        rates_report=(
            [
                {
                    "axis": r.axis,
                    "measured_p95_degps": f"{r.measured_p95_degps:.0f} deg/s" if r.measured_p95_degps is not None else "-",
                    "configured_max_degps": f"{r.configured_max_degps:.0f} deg/s" if r.configured_max_degps is not None else None,
                    "configured_max_note": r.configured_max_note,
                }
                for r in rates_report
            ]
            if rates_report
            else None
        ),
    )


def render_report(
    flight: Flight,
    metrics: FlightMetrics,
    findings: list[Finding],
    narrative: NarrativeReport,
    output_path: str | Path,
    log_filename: str = "",
    version_mismatch_warning: str | None = None,
    compare: dict | None = None,
    tune_plan=None,
    tune_warnings: list[str] | None = None,
    rates_report: list | None = None,
) -> Path:
    html = render_report_html(
        flight, metrics, findings, narrative,
        log_filename=log_filename,
        version_mismatch_warning=version_mismatch_warning,
        compare=compare,
        tune_plan=tune_plan,
        tune_warnings=tune_warnings,
        rates_report=rates_report,
    )
    output_path = Path(output_path)
    output_path.write_text(html, encoding="utf-8")
    return output_path
