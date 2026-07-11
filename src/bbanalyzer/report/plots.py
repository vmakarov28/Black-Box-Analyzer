"""Matplotlib figures -> inline base64 PNG data URIs. Kept strictly
separate from the DSP layer (which returns numbers, never plots) per the
Phase 2 design requirement -- this module is the only place that imports
matplotlib.pyplot for rendering. Agg backend only: no display, no network,
nothing written outside the returned data URI string.
"""
from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from bbanalyzer.dsp.metrics import AxisResult, FlightMetrics  # noqa: E402

_AXIS_COLORS = {"roll": "#2b6cb0", "pitch": "#c05621", "yaw": "#276749"}


def _fig_to_data_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def plot_step_responses(m: FlightMetrics) -> str:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.2), sharey=True)
    for ax_plot, axis in zip(axes, ("roll", "pitch", "yaw")):
        result: AxisResult | None = m.axes.get(axis)
        color = _AXIS_COLORS[axis]
        ax_plot.axhline(1.0, color="#999", linestyle="--", linewidth=1)
        ax_plot.axhspan(0.9, 1.1, color="#999", alpha=0.08)
        if result is not None and result.step_response.response is not None:
            sr = result.step_response
            ax_plot.plot(sr.time_s, sr.response, color=color, linewidth=1.8, label="all-input")
            if sr.response_low is not None:
                ax_plot.plot(sr.time_s, sr.response_low, color=color, linewidth=1, alpha=0.5, label="low-input")
            if sr.response_high is not None:
                ax_plot.plot(sr.time_s, sr.response_high, color=color, linewidth=1, alpha=0.5, linestyle=":", label="high-input")
            title = f"{axis} (rise {sr.rise_time_s*1000:.0f}ms, OS {sr.overshoot_pct:.0f}%)" if sr.rise_time_s else axis
        else:
            title = f"{axis} (unavailable)"
            ax_plot.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax_plot.transAxes, color="#999")
        ax_plot.set_title(title, fontsize=10)
        ax_plot.set_xlabel("time (s)")
        ax_plot.set_ylim(-0.3, 1.6)
        ax_plot.grid(alpha=0.2)
    axes[0].set_ylabel("normalized response")
    axes[0].legend(fontsize=7, loc="lower right")
    fig.suptitle("Step response (setpoint -> gyro, Wiener deconvolution)", fontsize=11)
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def plot_noise_heatmaps(m: FlightMetrics) -> str:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    for ax_plot, axis in zip(axes, ("roll", "pitch", "yaw")):
        result = m.axes.get(axis)
        hm = result.noise if result is not None else None
        if hm is not None and hm.psd.size > 0:
            data = np.clip(hm.psd, 1e-6, None)
            mesh = ax_plot.pcolormesh(
                hm.throttle_pct, hm.freq_hz, data, shading="auto", cmap="viridis",
                norm=matplotlib.colors.LogNorm(vmin=max(data.min(), 1e-3), vmax=data.max()),
            )
            ax_plot.set_ylim(0, min(1000, hm.freq_hz.max()))
            fig.colorbar(mesh, ax=ax_plot, fraction=0.046, pad=0.04)
            if result.diagonal_trace is not None:
                ax_plot.text(
                    0.02, 0.98, f"RPM-linked (r={result.diagonal_trace.correlation:.2f})",
                    transform=ax_plot.transAxes, va="top", color="white", fontsize=7,
                )
            for band in result.horizontal_bands[:1]:
                ax_plot.axhline(band.freq_hz, color="red", linestyle="--", linewidth=0.8, alpha=0.7)
        else:
            ax_plot.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax_plot.transAxes, color="#999")
        ax_plot.set_title(axis, fontsize=10)
        ax_plot.set_xlabel("throttle (%)")
    axes[0].set_ylabel("frequency (Hz)")
    fig.suptitle("Gyro noise: throttle vs frequency", fontsize=11)
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

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(12, 2.8))
    x = np.arange(len(axes_names))
    colors = [_AXIS_COLORS[a] for a in axes_names]
    ax1.bar(x, noise_reduction, color=colors)
    ax1.set_title("Filter noise reduction (dB)", fontsize=9)
    ax2.bar(x, latency, color=colors)
    ax2.set_title("Est. filter latency (ms)", fontsize=9)
    ax3.bar(x, propwash_rms, color=colors)
    ax3.set_title("Peak propwash RMS error (deg/s)", fontsize=9)
    for a in (ax1, ax2, ax3):
        a.set_xticks(x)
        a.set_xticklabels(axes_names)
        a.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    return _fig_to_data_uri(fig)


def plot_step_response_comparison(before: FlightMetrics, after: FlightMetrics, before_label: str, after_label: str) -> str:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.2), sharey=True)
    for ax_plot, axis in zip(axes, ("roll", "pitch", "yaw")):
        color = _AXIS_COLORS[axis]
        ax_plot.axhline(1.0, color="#999", linestyle="--", linewidth=1)
        ax_plot.axhspan(0.9, 1.1, color="#999", alpha=0.08)
        b_sr = before.axes.get(axis).step_response if before.axes.get(axis) else None
        a_sr = after.axes.get(axis).step_response if after.axes.get(axis) else None
        if b_sr is not None and b_sr.response is not None:
            ax_plot.plot(b_sr.time_s, b_sr.response, color=color, linewidth=1.4, linestyle="--", alpha=0.6, label=before_label)
        if a_sr is not None and a_sr.response is not None:
            ax_plot.plot(a_sr.time_s, a_sr.response, color=color, linewidth=1.8, label=after_label)
        ax_plot.set_title(axis, fontsize=10)
        ax_plot.set_xlabel("time (s)")
        ax_plot.set_ylim(-0.3, 1.6)
        ax_plot.grid(alpha=0.2)
    axes[0].set_ylabel("normalized response")
    axes[0].legend(fontsize=7, loc="lower right")
    fig.suptitle("Step response: before vs after", fontsize=11)
    fig.tight_layout()
    return _fig_to_data_uri(fig)
