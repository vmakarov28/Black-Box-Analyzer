"""The tuning-domain whitelist. This is the structural safety boundary for
everything this package emits: TUNING_WHITELIST is the complete set of CLI
keys the generator is capable of writing, full stop. There is no code path
anywhere in tune/ that can emit a key outside this set -- motor protocol,
failsafe, arming, mode assignments, ports, OSD, and VTX keys are not just
excluded by a filter, they were never enumerated here to filter *from*.
"""
from __future__ import annotations

PID_KEYS = {f"{gain}_{axis}" for gain in ("p", "i", "d", "f") for axis in ("roll", "pitch", "yaw")} | {
    "d_min_roll", "d_min_pitch", "d_min_yaw", "d_min_gain", "d_max_gain",
}

FILTER_KEYS = {
    "gyro_lowpass_hz", "gyro_lowpass2_hz", "gyro_lowpass_type", "gyro_lowpass2_type",
    "dterm_lowpass_hz", "dterm_lowpass2_hz", "dterm_lowpass_type", "dterm_lowpass2_type",
    "dyn_notch_min_hz", "dyn_notch_max_hz", "dyn_notch_count", "dyn_notch_q",
    "gyro_notch_hz", "gyro_notch_cutoff", "dterm_notch_hz", "dterm_notch_cutoff",
}

FEEDFORWARD_KEYS = {
    "feedforward_transition", "feedforward_boost", "feedforward_smooth_factor",
    "feedforward_jitter_factor", "feedforward_averaging",
}

# Keys whose *direct* `set` is what simplified_pids_mode overrides on save --
# the simplified-tuning guard only applies to these three groups.
SIMPLIFIED_GOVERNED_KEYS = PID_KEYS | FILTER_KEYS | FEEDFORWARD_KEYS

RPM_FILTER_KEYS = {"rpm_filter_harmonics", "rpm_filter_min_hz", "rpm_filter_q", "rpm_filter_fade_range_hz"}

DYN_IDLE_KEYS = {
    "dyn_idle_min_rpm", "dyn_idle_p_gain", "dyn_idle_i_gain", "dyn_idle_d_gain",
    "dyn_idle_max_increase", "dyn_idle_start_increase",
}

TPA_KEYS = {"tpa_rate", "tpa_breakpoint", "tpa_mode", "tpa_low_rate", "tpa_low_breakpoint", "tpa_low_always"}

ANTI_GRAVITY_KEYS = {
    "anti_gravity_gain", "anti_gravity_p_gain", "anti_gravity_mode",
    "iterm_relax", "iterm_relax_type", "iterm_relax_cutoff",
}

SIMPLIFIED_SLIDER_KEYS = {
    "simplified_pids_mode", "simplified_master_multiplier", "simplified_roll_pitch_ratio",
    "simplified_pi_gain", "simplified_i_gain", "simplified_d_gain", "simplified_dmax_gain",
    "simplified_feedforward_gain",
    "simplified_dterm_filter", "simplified_dterm_filter_multiplier",
    "simplified_gyro_filter", "simplified_gyro_filter_multiplier",
}

# Gated behind the explicit --rates flag (see tune/rates_report.py) -- never
# emitted as part of a diagnostic "recommended change".
RATES_KEYS = {
    "rc_rate", "rc_rate_yaw", "rc_expo", "rc_expo_yaw",
    "roll_rc_rate", "pitch_rc_rate", "yaw_rc_rate",
    "roll_expo", "pitch_expo", "yaw_expo",
    "roll_srate", "pitch_srate", "yaw_srate",
    "rates_type", "thr_expo", "thr_mid",
}

TUNING_WHITELIST = (
    PID_KEYS | FILTER_KEYS | FEEDFORWARD_KEYS | RPM_FILTER_KEYS
    | DYN_IDLE_KEYS | TPA_KEYS | ANTI_GRAVITY_KEYS | SIMPLIFIED_SLIDER_KEYS
)


def is_whitelisted(key: str, allow_rates: bool = False) -> bool:
    k = key.lower()
    if k in TUNING_WHITELIST:
        return True
    return allow_rates and k in RATES_KEYS
