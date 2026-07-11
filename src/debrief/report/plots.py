"""Matplotlib figures -> inline base64 PNG data URIs. Kept strictly
separate from the DSP layer (which returns numbers, never plots) per the
Phase 2 design requirement -- this module is the only place that imports
matplotlib.pyplot for rendering. Agg backend only: no display, no network,
nothing written outside the returned data URI string.

Palette matches the report's HTML theme, which is pulled from the real
betaflight-configurator source (src/css/theme.css, .dark block) rather
than an approximation -- see report/templates/report.html.j2's CSS
variables for the same values. The axis trio (roll/pitch/yaw) and the
amber sequential ramp were both run through the dataviz skill's
CVD-safety validator before being adopted.
"""
from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from debrief.dsp.metrics import AxisResult, FlightMetrics  # noqa: E402

# betaflight-configurator .dark theme surfaces/text
_BG = "#1a1a1a"          # matches the report's --panel (plots sit inside a panel card)
_GRID = "#3d3d3d"        # --border-2
_TEXT = "#f2f2f2"        # --text
_MUTED = "#9c9c9c"       # --muted

# validated (dataviz skill validator, dark mode, 3 categorical slots, all checks pass)
_AXIS_COLORS = {"roll": "#3987e5", "pitch": "#199e70", "yaw": "#9085e9"}

_ERROR = "#e2123f"

# Sequential "heat" ramp built from betaflight-configurator's own amber/gold
# primary scale (--primary-950 .. --primary-100), dark->light as the
# dataviz skill's sequential rule requires -- a single hue, not a rainbow.
_BF_AMBER_CMAP = matplotlib.colors.LinearSegmentedColormap.from_list(
    "bf_amber",
    ["#1a1204", "#482100", "#7c400b", "#bb6502", "#e29000", "#ffbb00", "#ffc526", "#ffea46", "#fffac5"],
)


def _style_axes(ax) -> None:
    ax.set_facecolor(_BG)
    ax.tick_params(colors=_MUTED, labelsize=8)
    ax.title.set_color(_TEXT)
    ax.xaxis.label.set_color(_MUTED)
    ax.yaxis.label.set_color(_MUTED)
    for spine in ax.spines.values():
        spine.set_color(_GRID)


def _new_fig(n: int, figsize, sharey=False):
    fig, axes = plt.subplots(1, n, figsize=figsize, sharey=sharey, facecolor=_BG)
    axes_list = axes if n > 1 else [axes]
    for ax in axes_list:
        _style_axes(ax)
    return fig, axes


def _fig_to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=_BG)
    plt.close(fig)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def plot_step_responses(m: FlightMetrics) -> str:
    fig, axes = _new_fig(3, (12, 3.2), sharey=True)
    for ax_plot, axis in zip(axes, ("roll", "pitch", "yaw")):
        result: AxisResult | None = m.axes.get(axis)
        color = _AXIS_COLORS[axis]
        ax_plot.axhline(1.0, color=_MUTED, linestyle="--", linewidth=1)
        ax_plot.axhspan(0.9, 1.1, color=_MUTED, alpha=0.12)
        if result is not None and result.step_response.response is not None:
            sr = result.step_response
            ax_plot.plot(sr.time_s, sr.response, color=color, linewidth=2, label="all-input")
            if sr.response_low is not None:
                ax_plot.plot(sr.time_s, sr.response_low, color=color, linewidth=1, alpha=0.5, label="low-input")
            if sr.response_high is not None:
                ax_plot.plot(sr.time_s, sr.response_high, color=color, linewidth=1, alpha=0.5, linestyle=":", label="high-input")
            title = f"{axis} (rise {sr.rise_time_s*1000:.0f}ms, OS {sr.overshoot_pct:.0f}%)" if sr.rise_time_s else axis
        else:
            title = f"{axis} (unavailable)"
            ax_plot.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax_plot.transAxes, color=_MUTED)
        ax_plot.set_title(title, fontsize=10)
        ax_plot.set_xlabel("time (s)")
        ax_plot.set_ylim(-0.3, 1.6)
        ax_plot.grid(alpha=0.25, color=_GRID)
    axes[0].set_ylabel("normalized response", color=_MUTED)
    leg = axes[0].legend(fontsize=7, loc="lower right", facecolor=_BG, edgecolor=_GRID)
    for text in leg.get_texts():
        text.set_color(_MUTED)
    fig.suptitle("Step response (setpoint -> gyro, Wiener deconvolution)", fontsize=11, color=_TEXT)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def plot_noise_heatmaps(m: FlightMetrics) -> str:
    fig, axes = _new_fig(3, (12, 3.6))
    for ax_plot, axis in zip(axes, ("roll", "pitch", "yaw")):
        result = m.axes.get(axis)
        hm = result.noise if result is not None else None
        if hm is not None and hm.psd.size > 0:
            data = np.clip(hm.psd, 1e-6, None)
            mesh = ax_plot.pcolormesh(
                hm.throttle_pct, hm.freq_hz, data, shading="auto", cmap=_BF_AMBER_CMAP,
                norm=matplotlib.colors.LogNorm(vmin=max(data.min(), 1e-3), vmax=data.max()),
            )
            ax_plot.set_ylim(0, min(1000, hm.freq_hz.max()))
            cbar = fig.colorbar(mesh, ax=ax_plot, fraction=0.046, pad=0.04)
            cbar.ax.tick_params(colors=_MUTED, labelsize=7)
            cbar.outline.set_edgecolor(_GRID)
            if result.diagonal_trace is not None:
                ax_plot.text(
                    0.02, 0.98, f"RPM-linked (r={result.diagonal_trace.correlation:.2f})",
                    transform=ax_plot.transAxes, va="top", color=_TEXT, fontsize=7,
                )
            for band in result.horizontal_bands[:1]:
                ax_plot.axhline(band.freq_hz, color=_ERROR, linestyle="--", linewidth=0.9, alpha=0.85)
        else:
            ax_plot.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax_plot.transAxes, color=_MUTED)
        ax_plot.set_title(axis, fontsize=10)
        ax_plot.set_xlabel("throttle (%)")
    axes[0].set_ylabel("frequency (Hz)", color=_MUTED)
    fig.suptitle("Gyro noise: throttle vs frequency", fontsize=11, color=_TEXT)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def plot_filter_and_propwash_summary(m: FlightMetrics) -> str:
    axes_names = ("roll", "pitch", "yaw")
    noise_reduction = []
    latency = []
    propwash_rms = []
    for axis in axes_names:
        result = m.axes.get(axis)
        fc = result.filter_comparison if result else None
        noise_reduction.append(fc.noise_reduction_db if fc and fc.available and fc.noise_reduction_db else 0)
        latency.append((fc.estimated_latency_s or 0) * 1000.0 if fc and fc.available else 0)
        rms_vals = [p.rms_error_degps for p in result.propwash_scores] if result else []
        propwash_rms.append(max(rms_vals) if rms_vals else 0)

    fig, (ax1, ax2, ax3) = _new_fig(3, (12, 2.8))
    x = np.arange(len(axes_names))
    colors = [_AXIS_COLORS[a] for a in axes_names]
    ax1.bar(x, noise_reduction, color=colors, width=0.55)
    ax1.set_title("Filter noise reduction (dB)", fontsize=9)
    ax2.bar(x, latency, color=colors, width=0.55)
    ax2.set_title("Est. filter latency (ms)", fontsize=9)
    ax3.bar(x, propwash_rms, color=colors, width=0.55)
    ax3.set_title("Peak propwash RMS error (deg/s)", fontsize=9)
    for a in (ax1, ax2, ax3):
        a.set_xticks(x)
        a.set_xticklabels(axes_names)
        a.grid(alpha=0.25, axis="y", color=_GRID)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def plot_step_response_comparison(before: FlightMetrics, after: FlightMetrics, before_label: str, after_label: str) -> str:
    fig, axes = _new_fig(3, (12, 3.2), sharey=True)
    for ax_plot, axis in zip(axes, ("roll", "pitch", "yaw")):
        color = _AXIS_COLORS[axis]
        ax_plot.axhline(1.0, color=_MUTED, linestyle="--", linewidth=1)
        ax_plot.axhspan(0.9, 1.1, color=_MUTED, alpha=0.12)
        b_sr = before.axes.get(axis).step_response if before.axes.get(axis) else None
        a_sr = after.axes.get(axis).step_response if after.axes.get(axis) else None
        if b_sr is not None and b_sr.response is not None:
            ax_plot.plot(b_sr.time_s, b_sr.response, color=color, linewidth=1.4, linestyle="--", alpha=0.6, label=before_label)
        if a_sr is not None and a_sr.response is not None:
            ax_plot.plot(a_sr.time_s, a_sr.response, color=color, linewidth=2, label=after_label)
        ax_plot.set_title(axis, fontsize=10)
        ax_plot.set_xlabel("time (s)")
        ax_plot.set_ylim(-0.3, 1.6)
        ax_plot.grid(alpha=0.25, color=_GRID)
    axes[0].set_ylabel("normalized response", color=_MUTED)
    leg = axes[0].legend(fontsize=7, loc="lower right", facecolor=_BG, edgecolor=_GRID)
    for text in leg.get_texts():
        text.set_color(_MUTED)
    fig.suptitle("Step response: before vs after", fontsize=11, color=_TEXT)
    fig.tight_layout()
    return _fig_to_data_uri(fig)
