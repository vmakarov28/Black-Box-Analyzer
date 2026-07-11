"""DSP-metric-driven rules: metrics.flat pattern -> Finding. Seeded from
Betaflight tuning wiki heuristics and widely-repeated community tuning
guidance (UAV Tech / Chris Rosser style step-response and noise-heatmap
reading conventions). Every numeric threshold that isn't a documented
Betaflight default is marked TUNABLE in the Finding it produces -- these
are reasonable starting points, not measured facts.

Each rule is (axis, metrics, config) -> Finding | None for per-axis rules,
or (metrics, config) -> Finding | None for whole-flight rules. Kept as
plain functions rather than a declarative DSL so every trigger condition
is ordinary, testable, greppable Python.
"""
from __future__ import annotations

from bbanalyzer.dsp.metrics import FlightMetrics
from bbanalyzer.parse.header import HeaderConfig
from bbanalyzer.rules.flag import Confidence, Finding, ParamHint, Severity

# TUNABLE thresholds -- see individual rule rationale for why each was chosen.
OVERSHOOT_WARN_PCT = 30.0
OVERSHOOT_CRITICAL_PCT = 60.0
RISE_TIME_SLUGGISH_S = 0.05
MIN_WINDOWS_FOR_CONFIDENCE = 200      # below this, downgrade confidence -- too little stick input logged
DIAGONAL_CORR_HIGH = 0.8
NOISE_REDUCTION_LOW_DB = 3.0
FILTER_LATENCY_HIGH_MS = 4.0
PROPWASH_RMS_WARN_DEGPS = 60.0
PROPWASH_RMS_CRITICAL_DEGPS = 120.0
PROPWASH_BOUNCE_RATE_WARN = 0.5
MIN_PROPWASH_EVENTS_FOR_CONFIDENCE = 5


def _confidence_from_sample_size(base: Confidence, n_windows: int) -> Confidence:
    if n_windows < MIN_WINDOWS_FOR_CONFIDENCE and base == Confidence.HIGH:
        return Confidence.MEDIUM
    return base


def rule_step_response_unstable(axis: str, m: FlightMetrics, cfg: HeaderConfig) -> Finding | None:
    ax = m.axes.get(axis)
    if ax is None or ax.step_response.stable is not False:
        return None
    sr = ax.step_response
    return Finding(
        id=f"step_response_unstable_{axis}",
        title=f"{axis.capitalize()} step response looks unstable",
        category="pid",
        severity=Severity.CRITICAL,
        confidence=_confidence_from_sample_size(Confidence.HIGH, sr.n_windows),
        axis=axis,
        trigger_summary=f"overshoot={sr.overshoot_pct:.0f}% settling_time={'unsettled' if sr.settling_time_s is None else f'{sr.settling_time_s*1000:.0f}ms'}",
        rationale=(
            "The reconstructed step response doesn't settle within the analysis window and/or "
            "overshoots heavily -- consistent with P and/or D set too high for this frame, or a "
            "filter/notch letting through noise that's exciting the loop. This is the single "
            "most safety-relevant finding this tool produces."
        ),
        suggestion=f"Reduce {axis} P (and/or D) before the next flight; re-check the noise heatmap for a filtering root cause first.",
        param_hints=[ParamHint(key_guess=f"p_{axis}", direction="decrease", magnitude_pct=10, axis=axis)],
        source="betaflight-wiki",
    )


def rule_step_response_overshoot(axis: str, m: FlightMetrics, cfg: HeaderConfig) -> Finding | None:
    ax = m.axes.get(axis)
    if ax is None or ax.step_response.overshoot_pct is None:
        return None
    pct = ax.step_response.overshoot_pct
    if pct < OVERSHOOT_WARN_PCT:
        return None
    severity = Severity.CRITICAL if pct >= OVERSHOOT_CRITICAL_PCT else Severity.WARNING
    return Finding(
        id=f"step_response_overshoot_{axis}",
        title=f"{axis.capitalize()} step response overshoots by {pct:.0f}%",
        category="pid",
        severity=severity,
        confidence=_confidence_from_sample_size(Confidence.MEDIUM, ax.step_response.n_windows),
        axis=axis,
        trigger_summary=f"overshoot_pct={pct:.1f}",
        rationale=(
            "Overshoot past the commanded setpoint before settling usually points to P too high "
            "relative to D, or D too low to damp it -- but the same shape can come from D-term "
            "noise being filtered out along with the damping it provides, so check the filter "
            "and noise findings for this axis before changing PIDs."
        ),
        suggestion=f"Consider lowering {axis} P slightly or raising D slightly; verify it isn't a filtering issue first.",
        param_hints=[ParamHint(key_guess=f"p_{axis}", direction="decrease", magnitude_pct=8, axis=axis)],
        source="betaflight-wiki",
        tunable_note=f"the {OVERSHOOT_WARN_PCT:.0f}%/{OVERSHOOT_CRITICAL_PCT:.0f}% thresholds are heuristic, not documented defaults",
    )


def rule_step_response_sluggish(axis: str, m: FlightMetrics, cfg: HeaderConfig) -> Finding | None:
    ax = m.axes.get(axis)
    if ax is None:
        return None
    sr = ax.step_response
    if sr.rise_time_s is None or sr.overshoot_pct is None:
        return None
    if sr.rise_time_s < RISE_TIME_SLUGGISH_S or sr.overshoot_pct > 10.0:
        return None  # only flag "sluggish" when there's also no overshoot -- otherwise it's the overshoot rule's job
    return Finding(
        id=f"step_response_sluggish_{axis}",
        title=f"{axis.capitalize()} response is slow with no overshoot",
        category="pid",
        severity=Severity.ADVISORY,
        confidence=_confidence_from_sample_size(Confidence.MEDIUM, sr.n_windows),
        axis=axis,
        trigger_summary=f"rise_time_s={sr.rise_time_s:.3f}, overshoot_pct={sr.overshoot_pct:.1f}",
        rationale=(
            "A slow rise with essentially no overshoot suggests there's tracking headroom left "
            "-- P could likely go up without immediately risking oscillation. This is the "
            "lowest-risk kind of PID finding this tool produces."
        ),
        suggestion=f"Consider raising {axis} P slightly; response has room before overshoot becomes a concern.",
        param_hints=[ParamHint(key_guess=f"p_{axis}", direction="increase", magnitude_pct=8, axis=axis)],
        source="community-heuristic",
        tunable_note=f"the {RISE_TIME_SLUGGISH_S*1000:.0f}ms threshold is heuristic, not a documented default",
    )


def rule_noise_rpm_linked(axis: str, m: FlightMetrics, cfg: HeaderConfig) -> Finding | None:
    ax = m.axes.get(axis)
    if ax is None or ax.diagonal_trace is None:
        return None
    dt = ax.diagonal_trace
    confidence = Confidence.HIGH if dt.correlation >= DIAGONAL_CORR_HIGH else Confidence.MEDIUM
    rpm_note = (
        "RPM filtering is off, which is the most direct fix if bidirectional DShot is available."
        if cfg.rpm_filter_enabled is False
        else "RPM filtering is already on -- this may mean the harmonics count/Q needs adjusting, "
        "or a prop is imbalanced/damaged, or the motor_poles value is wrong."
    )
    return Finding(
        id=f"noise_rpm_linked_{axis}",
        title=f"RPM-linked noise on {axis} (r={dt.correlation:.2f}, {dt.slope_hz_per_pct:.1f}Hz per %throttle)",
        category="hardware" if cfg.rpm_filter_enabled else "rpm_filter",
        severity=Severity.WARNING,
        confidence=confidence,
        axis=axis,
        trigger_summary=f"correlation={dt.correlation:.2f}, freq {dt.freq_at_min_throttle_hz:.0f}-{dt.freq_at_max_throttle_hz:.0f}Hz across the throttle range",
        rationale=(
            "A noise ridge whose frequency rises with throttle tracks motor RPM -- classic "
            "signature of prop/motor noise the filtering chain isn't fully rejecting. "
            f"{rpm_note}"
        ),
        suggestion=(
            "Enable/verify RPM filtering and motor_poles."
            if cfg.rpm_filter_enabled is not True
            else "Check prop balance/condition and verify motor_poles is correct; consider raising rpm_filter_harmonics."
        ),
        source="betaflight-wiki",
    )


def rule_noise_frame_resonance(axis: str, m: FlightMetrics, cfg: HeaderConfig) -> Finding | None:
    ax = m.axes.get(axis)
    if ax is None or not ax.horizontal_bands:
        return None
    band = ax.horizontal_bands[0]
    return Finding(
        id=f"noise_frame_resonance_{axis}",
        title=f"Persistent noise near {band.freq_hz:.0f}Hz on {axis} regardless of throttle",
        category="hardware",
        severity=Severity.ADVISORY,
        confidence=Confidence.MEDIUM,
        axis=axis,
        trigger_summary=f"freq={band.freq_hz:.0f}Hz, energy_percentile={band.energy_percentile:.0f}, cv={band.coefficient_of_variation:.2f}",
        rationale=(
            "Noise that's loud at roughly the same frequency across the whole throttle range "
            "(rather than rising with throttle like RPM noise) is more consistent with frame or "
            "camera-mount resonance, a loose screw, or a damaged/soft frame arm than with the "
            "motors themselves -- this is measured, but the root cause needs a physical check, "
            "which we can't do from a log."
        ),
        suggestion=f"Check frame hardware (mounting screws, camera mount, arm condition) for a resonance near {band.freq_hz:.0f}Hz; a static notch there is a workaround, not a fix.",
        source="community-heuristic",
    )


def rule_filter_noise_reduction_low(axis: str, m: FlightMetrics, cfg: HeaderConfig) -> Finding | None:
    ax = m.axes.get(axis)
    if ax is None or not ax.filter_comparison.available:
        return None
    fc = ax.filter_comparison
    if fc.noise_reduction_db is None or fc.noise_reduction_db >= NOISE_REDUCTION_LOW_DB:
        return None
    return Finding(
        id=f"filter_noise_reduction_low_{axis}",
        title=f"Filtering is only removing {fc.noise_reduction_db:.1f}dB of high-frequency noise on {axis}",
        category="filtering",
        severity=Severity.ADVISORY,
        confidence=Confidence.LOW,
        axis=axis,
        trigger_summary=f"noise_reduction_db={fc.noise_reduction_db:.1f} (via debug[{fc.debug_channel}] proxy, r={fc.correlation:.2f})",
        rationale=(
            "Comparing the filtered gyro against a debug-channel proxy for the unfiltered "
            "signal, this filter chain isn't removing much high-frequency energy. Low "
            "confidence: the proxy channel's exact meaning depends on debug_mode, which we "
            "can't fully verify for this firmware version."
        ),
        suggestion="Cross-check against the noise heatmap findings; if noise is genuinely elevated, filtering may need tightening.",
        source="measurement",
        tunable_note=f"the {NOISE_REDUCTION_LOW_DB:.0f}dB threshold is heuristic",
    )


def rule_filter_latency_high(axis: str, m: FlightMetrics, cfg: HeaderConfig) -> Finding | None:
    ax = m.axes.get(axis)
    if ax is None or not ax.filter_comparison.available:
        return None
    fc = ax.filter_comparison
    latency_ms = fc.estimated_latency_s * 1000.0 if fc.estimated_latency_s is not None else None
    if latency_ms is None or latency_ms < FILTER_LATENCY_HIGH_MS:
        return None
    return Finding(
        id=f"filter_latency_high_{axis}",
        title=f"Estimated filter latency on {axis} is {latency_ms:.1f}ms",
        category="filtering",
        severity=Severity.ADVISORY,
        confidence=Confidence.LOW,
        axis=axis,
        trigger_summary=f"estimated_latency_ms={latency_ms:.1f} (via debug[{fc.debug_channel}] proxy)",
        rationale=(
            "Every filter trades noise rejection for delay. This much estimated delay between "
            "the (proxy) unfiltered signal and the filtered gyro is on the high side, and "
            "filter latency shows up as sluggish/mushy feel even when the step response metrics "
            "look fine. Low confidence for the same debug-channel-meaning caveat as the noise "
            "reduction finding."
        ),
        suggestion="If the quad feels laggy despite acceptable step-response numbers, consider raising gyro/D-term lowpass cutoffs slightly.",
        source="measurement",
        tunable_note=f"the {FILTER_LATENCY_HIGH_MS:.0f}ms threshold is heuristic",
    )


def rule_propwash_bounce_back(axis: str, m: FlightMetrics, cfg: HeaderConfig) -> Finding | None:
    ax = m.axes.get(axis)
    if ax is None:
        return None
    events = ax.propwash_scores
    if len(events) < MIN_PROPWASH_EVENTS_FOR_CONFIDENCE:
        return None
    rms_vals = [e.rms_error_degps for e in events]
    max_rms = max(rms_vals)
    bounce_rate = sum(1 for e in events if e.bounce_back) / len(events)
    if max_rms < PROPWASH_RMS_WARN_DEGPS or bounce_rate < PROPWASH_BOUNCE_RATE_WARN:
        return None
    severity = Severity.WARNING if max_rms < PROPWASH_RMS_CRITICAL_DEGPS else Severity.CRITICAL
    return Finding(
        id=f"propwash_bounce_back_{axis}",
        title=f"Propwash/bounce-back after throttle chops on {axis} (peak {max_rms:.0f}deg/s error)",
        category="pid",
        severity=severity,
        confidence=Confidence.MEDIUM,
        axis=axis,
        trigger_summary=f"n_chop_events={len(events)}, bounce_back_rate={bounce_rate:.0%}, max_rms_error_degps={max_rms:.0f}",
        rationale=(
            "After a fast throttle drop, turbulent prop-wash airflow disrupts gyro tracking; "
            "oscillatory (sign-alternating) tracking error in that window, rather than a single "
            "settle-and-recover, is the community's usual signature for genuine propwash rather "
            "than a plain PID overshoot."
        ),
        suggestion="Consider raising throttle-based D or iterm-relax/anti-gravity settings; this is a nuanced area -- treat as a starting hypothesis, test one change at a time.",
        source="community-heuristic",
        tunable_note=f"the {PROPWASH_RMS_WARN_DEGPS:.0f}/{PROPWASH_RMS_CRITICAL_DEGPS:.0f}deg/s and {PROPWASH_BOUNCE_RATE_WARN:.0%} thresholds are heuristic",
    )


PER_AXIS_RULES = [
    rule_step_response_unstable,
    rule_step_response_overshoot,
    rule_step_response_sluggish,
    rule_noise_rpm_linked,
    rule_noise_frame_resonance,
    rule_filter_noise_reduction_low,
    rule_filter_latency_high,
    rule_propwash_bounce_back,
]

AXES = ("roll", "pitch", "yaw")


def run_metric_rules(m: FlightMetrics, cfg: HeaderConfig) -> list[Finding]:
    findings = []
    for axis in AXES:
        for rule in PER_AXIS_RULES:
            result = rule(axis, m, cfg)
            if result is not None:
                findings.append(result)
    return findings
