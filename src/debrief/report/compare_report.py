"""analyze --compare before.bbl after.bbl -> a focused before/after HTML
report. Separate from the main single-flight report template on purpose:
different shape of content (two flights, one delta table), not worth
overloading report.html.j2's context for.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from debrief import __version__
from debrief.dsp.metrics import FlightMetrics
from debrief.report.plots import plot_step_response_comparison
from debrief.tune.compare import MetricDelta

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "compare.html.j2"


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.3g}"
    return str(v)


def render_compare_report(
    before_metrics: FlightMetrics,
    after_metrics: FlightMetrics,
    deltas: list[MetricDelta],
    before_label: str,
    after_label: str,
    output_path: str | Path,
) -> Path:
    template = Template(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    html = template.render(
        before_label=before_label,
        after_label=after_label,
        step_response_plot=plot_step_response_comparison(before_metrics, after_metrics, before_label, after_label),
        rows=[
            {"name": d.name, "before": _fmt(d.before), "after": _fmt(d.after), "delta": _fmt(d.delta) if d.delta is not None else _fmt(d.improved), "improved": d.improved}
            for d in deltas
        ],
        version=__version__,
    )
    output_path = Path(output_path)
    output_path.write_text(html, encoding="utf-8")
    return output_path
