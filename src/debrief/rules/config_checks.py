"""Config-only checks: run before any DSP, purely against the parsed
header config. These catch "obviously missing" setup regardless of how
the flight itself went (a mistuned quad flies fine right up until it
doesn't) -- e.g. bidirectional DShot on but RPM filtering off.

Each check is a plain function (header.HeaderConfig) -> Finding | None,
registered in CONFIG_CHECKS. Source: Betaflight tuning wiki conventions
as of BF 4.3-4.5-era documentation; where a threshold is a guess rather
than a documented default, it's marked TUNABLE.
"""
from __future__ import annotations

from debrief.parse.header import HeaderConfig
from debrief.rules.flag import Confidence, Finding, ParamHint, Severity

_DSHOT_PROTOCOLS = {"DSHOT150", "DSHOT300", "DSHOT600", "DSHOT1200", "PROSHOT1000"}


def check_bidir_dshot_rpm_filter(cfg: HeaderConfig) -> Finding | None:
    protocol = (cfg.motor_protocol or "").upper()
    is_dshot = any(p in protocol for p in _DSHOT_PROTOCOLS) or "DSHOT" in protocol

    if cfg.dshot_bidir and cfg.rpm_filter_enabled is False:
        return Finding(
            id="bidir_dshot_rpm_filter_off",
            title="Bidirectional DShot is on but RPM filtering is off",
            category="rpm_filter",
            severity=Severity.WARNING,
            confidence=Confidence.HIGH,
            axis=None,
            trigger_summary="dshot_bidir=ON, rpm_filter_harmonics=0",
            rationale=(
                "RPM filtering uses the eRPM telemetry that bidirectional DShot already "
                "provides to track and notch out motor noise as RPM changes -- with bidir "
                "on, enabling it is close to a free win, and the gyro noise heatmap can "
                "usually drop its RPM-linked (diagonal) noise significantly."
            ),
            suggestion="Enable RPM filtering (rpm_filter_harmonics) now that bidirectional DShot telemetry is available.",
            param_hints=[ParamHint(key_guess="rpm_filter_harmonics", direction="enable")],
            source="betaflight-wiki",
        )

    if is_dshot and not cfg.dshot_bidir and cfg.rpm_filter_enabled is not True:
        return Finding(
            id="dshot_bidir_available_unconfirmed",
            title="DShot protocol in use -- bidirectional DShot may be available but isn't confirmed on",
            category="rpm_filter",
            severity=Severity.ADVISORY,
            confidence=Confidence.LOW,
            axis=None,
            trigger_summary=f"motor_protocol={cfg.motor_protocol!r}, dshot_bidir not ON in header",
            rationale=(
                "RPM filtering needs bidirectional DShot, which needs ESC firmware support "
                "(BLHeli32/AM32/BlueJay) we can't confirm from the blackbox header alone. "
                "Worth checking if your ESCs support it -- this is a question, not a diagnosis."
            ),
            suggestion="If your ESCs support bidirectional DShot (BLHeli32/AM32/BlueJay), consider enabling it and RPM filtering.",
            source="betaflight-wiki",
        )
    return None


def check_dynamic_idle(cfg: HeaderConfig) -> Finding | None:
    if cfg.dyn_idle_min_rpm is not None and cfg.dyn_idle_min_rpm <= 0:
        return Finding(
            id="dynamic_idle_unset",
            title="Dynamic idle is not configured",
            category="config",
            severity=Severity.ADVISORY,
            confidence=Confidence.MEDIUM,
            axis=None,
            trigger_summary="dyn_idle_min_rpm=0",
            rationale=(
                "Dynamic idle holds a minimum motor RPM instead of a fixed throttle %, which "
                "keeps props spinning fast enough to stay authoritative through fast throttle "
                "drops -- helps limit desync and can reduce prop-wash bounce-back. Most useful "
                "on light/aggressive builds; less critical on heavier freestyle setups, so this "
                "is advisory rather than a clear-cut fix."
            ),
            suggestion="Consider configuring dynamic idle (needs bidirectional DShot / RPM telemetry).",
            param_hints=[ParamHint(key_guess="dyn_idle_min_rpm", direction="increase")],
            source="betaflight-wiki",
        )
    return None


def check_dynamic_notch(cfg: HeaderConfig) -> Finding | None:
    if cfg.dyn_notch_enabled is False:
        return Finding(
            id="dynamic_notch_disabled",
            title="Dynamic notch filtering is disabled",
            category="filtering",
            severity=Severity.WARNING,
            confidence=Confidence.MEDIUM,
            axis=None,
            trigger_summary="dyn_notch_count=0",
            rationale=(
                "The dynamic notch tracks and filters the dominant noise peaks as they move "
                "with RPM/flight condition, which a fixed-frequency filter can't do. Disabling "
                "it is sometimes intentional on a very clean, well-balanced RPM-filtered build, "
                "so this is a warning to check, not an automatic verdict."
            ),
            suggestion="If not intentionally disabled for a clean RPM-filtered build, consider re-enabling the dynamic notch.",
            param_hints=[ParamHint(key_guess="dyn_notch_count", direction="enable")],
            source="betaflight-wiki",
        )
    return None


def check_simplified_tuning_active(cfg: HeaderConfig) -> Finding | None:
    if cfg.simplified_tuning_active:
        return Finding(
            id="simplified_tuning_active",
            title="Simplified tuning sliders are active",
            category="config",
            severity=Severity.INFO,
            confidence=Confidence.HIGH,
            axis=None,
            trigger_summary="simplified_pids_mode=ON",
            rationale=(
                "With simplified tuning on, PID/filter/D-max values are computed from the "
                "slider settings; raw `set` commands for those keys may be silently overridden "
                "on save. Any recommendation below that touches a PID/filter key must be "
                "expressed as a slider change (or explicitly turn simplified tuning off first) "
                "-- this finding exists so that guard is visible, not to flag a problem."
            ),
            suggestion="No action needed by itself -- informs how other findings' CLI changes must be expressed.",
            source="config-check",
        )
    return None


def check_gyro_filter_wide_open(cfg: HeaderConfig) -> Finding | None:
    # TUNABLE: 300Hz is a rough "basically unfiltered for a typical small
    # prop" heuristic, not a documented Betaflight default -- flagged as
    # low confidence and phrased as investigation, not a verdict, because
    # the right cutoff genuinely depends on prop size/loop rate/RPM filter
    # presence, none of which we can fully resolve from the header alone.
    threshold_hz = 300.0
    if cfg.gyro_lowpass_hz is not None and cfg.gyro_lowpass_hz >= threshold_hz and not cfg.rpm_filter_enabled:
        return Finding(
            id="gyro_lowpass_very_high",
            title=f"Gyro lowpass cutoff is very high ({cfg.gyro_lowpass_hz:.0f}Hz) with no RPM filter",
            category="filtering",
            severity=Severity.ADVISORY,
            confidence=Confidence.LOW,
            axis=None,
            trigger_summary=f"gyro_lowpass_hz={cfg.gyro_lowpass_hz}, rpm_filter_enabled=False",
            rationale=(
                "A very high (or effectively disabled) gyro lowpass leaves more raw motor/prop "
                "noise in the loop, which is usually fine only when RPM filtering is doing the "
                "real noise rejection. Without RPM filtering active, this is worth a second look "
                "-- check the noise heatmap findings below for actual measured noise."
            ),
            suggestion="Check whether this cutoff was intentional; the noise heatmap findings below are the real evidence either way.",
            source="community-heuristic",
            tunable_note=f"the {threshold_hz:.0f}Hz threshold is a rough heuristic, not a documented default",
        )
    return None


def check_motor_poles_for_rpm_filter(cfg: HeaderConfig) -> Finding | None:
    if cfg.rpm_filter_enabled and not cfg.motor_poles:
        return Finding(
            id="rpm_filter_motor_poles_unset",
            title="RPM filtering is on but motor pole count isn't set in the header",
            category="rpm_filter",
            severity=Severity.ADVISORY,
            confidence=Confidence.MEDIUM,
            axis=None,
            trigger_summary="rpm_filter_harmonics>0, motor_poles not present/zero",
            rationale=(
                "RPM filter notch placement is computed from eRPM using the configured motor "
                "pole count; if it's wrong, the notches land at the wrong frequency and the "
                "filter does little or actively hurts. We can't verify correctness from a "
                "blackbox header, only that it's set."
            ),
            suggestion="Double check motor_poles matches your actual motors (commonly 14 for most 5\" builds, but verify against your motor's spec).",
            param_hints=[ParamHint(key_guess="motor_poles", direction="investigate")],
            source="betaflight-wiki",
        )
    return None


CONFIG_CHECKS = [
    check_bidir_dshot_rpm_filter,
    check_dynamic_idle,
    check_dynamic_notch,
    check_simplified_tuning_active,
    check_gyro_filter_wide_open,
    check_motor_poles_for_rpm_filter,
]


def run_config_checks(cfg: HeaderConfig) -> list[Finding]:
    findings = []
    for check in CONFIG_CHECKS:
        result = check(cfg)
        if result is not None:
            findings.append(result)
    return findings
