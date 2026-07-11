"""Single self-contained HTML report: all plots and styles inlined, zero
network requests when opened. The only inputs are the outputs of the
other layers (loader.Flight, dsp.FlightMetrics, rules Findings,
llm.NarrativeReport) -- this module does no diagnosis of its own.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from jinja2 import Template

from bbanalyzer import __version__
from bbanalyzer.dsp.metrics import FlightMetrics
from bbanalyzer.llm.schema import NarrativeReport
from bbanalyzer.parse.loader import Flight
from bbanalyzer.report.plots import (
    plot_filter_and_propwash_summary,
    plot_noise_heatmaps,
    plot_step_responses,
)
from bbanalyzer.rules.flag import Finding

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "report.html.j2"


def render_report(
    flight: Flight,
    metrics: FlightMetrics,
    findings: list[Finding],
    narrative: NarrativeReport,
    output_path: str | Path,
    log_filename: str = "",
    version_mismatch_warning: str | None = None,
    compare: dict | None = None,
) -> Path:
    cfg = flight.config
    template = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))

    firmware_line = f"{cfg.firmware_name or 'unknown firmware'} {'.'.join(str(v) for v in cfg.firmware_version) if cfg.firmware_version else ''} on {cfg.target or 'unknown target'}"

    html = template.render(
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
    )

    output_path = Path(output_path)
    output_path.write_text(html, encoding="utf-8")
    return output_path
