"""Turns the rules layer's recommended Findings into an actual, validated
CLI change plan. This is the only place in the codebase allowed to decide
what value a CLI key gets set to -- and every decision it makes passes
through, in order: the whitelist, the version-guard round-trip check, the
simplified-tuning guard, and the bounds clamps. Any hint that fails any of
these is dropped into `rejected`, never emitted.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from debrief.rules.flag import Finding, ParamHint
from debrief.tune.bounds import validate_filter_hz, validate_gain_change
from debrief.tune.config_model import TuneConfig
from debrief.tune.whitelist import (
    FEEDFORWARD_KEYS,
    PID_KEYS,
    SIMPLIFIED_GOVERNED_KEYS,
    is_whitelisted,
)

# TUNABLE: default value to set when a hint says "enable" a filter/harmonic
# count that's currently off -- these are the commonly-suggested Betaflight
# starting points, not the pilot's tuned value.
ENABLE_DEFAULTS = {
    "rpm_filter_harmonics": "3",
    "dyn_notch_count": "3",
}
DEFAULT_MAGNITUDE_PCT = 10.0
_FILTER_HZ_KEYS = {"gyro_lowpass_hz", "gyro_lowpass2_hz", "dterm_lowpass_hz", "dterm_lowpass2_hz"}


@dataclass
class CLIChange:
    key: str
    old_value: str | None
    new_value: str
    reason: str
    finding_id: str
    confidence: str
    axis: str | None = None


@dataclass
class RejectedChange:
    key: str
    finding_id: str
    reason: str


@dataclass
class TuneGeneratorResult:
    stages: list[list[CLIChange]] = field(default_factory=list)
    rollback: list[CLIChange] = field(default_factory=list)
    rejected: list[RejectedChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    simplified_tuning_active: bool = False
    source: str = ""


def _translate_to_slider(key: str) -> str | None:
    if key in PID_KEYS:
        if key.startswith("d_"):
            return "simplified_d_gain"
        if key.startswith("f_"):
            return "simplified_feedforward_gain"
        return "simplified_pi_gain"  # p_<axis> and i_<axis>
    if key in {"gyro_lowpass_hz", "gyro_lowpass2_hz"}:
        return "simplified_gyro_filter_multiplier"
    if key in {"dterm_lowpass_hz", "dterm_lowpass2_hz"}:
        return "simplified_dterm_filter_multiplier"
    if key in FEEDFORWARD_KEYS:
        return "simplified_feedforward_gain"
    return None


def _resolve_new_value(key: str, hint: ParamHint, current_str: str | None) -> tuple[str | None, str | None]:
    """Returns (new_value, rejection_reason) -- exactly one is not None."""
    if hint.direction in ("enable", "disable"):
        default = ENABLE_DEFAULTS.get(key)
        if hint.direction == "enable" and default is not None:
            return default, None
        if hint.direction == "disable":
            return "0", None
        return None, f"no default value known for enabling {key!r} -- needs a human to pick a starting value"
    if hint.direction == "investigate":
        return None, "informational only (direction=investigate) -- no CLI change to propose"
    if current_str is None:
        return None, "current value unavailable"
    try:
        current_f = float(current_str)
    except ValueError:
        return None, f"current value of {key} ({current_str!r}) isn't numeric"
    pct = hint.magnitude_pct if hint.magnitude_pct is not None else DEFAULT_MAGNITUDE_PCT
    sign = 1 if hint.direction == "increase" else -1
    new_f = current_f * (1 + sign * pct / 100.0)
    return str(round(new_f)), None


def _check_bounds(key: str, current_str: str | None, new_str: str, loop_rate_hz: float | None) -> tuple[bool, str | None]:
    try:
        new_f = float(new_str)
    except ValueError:
        return True, None  # non-numeric (e.g. ON/OFF) -- nothing to bounds-check
    if key in _FILTER_HZ_KEYS:
        return validate_filter_hz(new_f, loop_rate_hz)
    if current_str is not None:
        try:
            current_f = float(current_str)
            return validate_gain_change(current_f, new_f)
        except ValueError:
            return True, None
    return True, None


def generate_tune_plan(
    findings: list[Finding],
    tune_cfg: TuneConfig,
    loop_rate_hz: float | None = None,
    disable_simplified_first: bool = False,
    allow_rates: bool = False,
) -> TuneGeneratorResult:
    recommended = [f for f in findings if f.recommended]
    simplified_active = tune_cfg.simplified_tuning_active
    emit_raw = not simplified_active or disable_simplified_first

    stages: list[list[CLIChange]] = []
    rejected: list[RejectedChange] = []
    rollback_map: dict[str, str] = {}

    if simplified_active and disable_simplified_first:
        old = tune_cfg.get("simplified_pids_mode")
        stages.append(
            [
                CLIChange(
                    key="simplified_pids_mode",
                    old_value=old,
                    new_value="OFF",
                    reason="explicitly disabling simplified tuning so the raw PID/filter changes below aren't silently overridden on save",
                    finding_id="_disable_simplified",
                    confidence="high",
                )
            ]
        )
        if old is not None:
            rollback_map["simplified_pids_mode"] = old

    for finding in recommended:
        stage_changes: list[CLIChange] = []
        for hint in finding.param_hints:
            key = hint.key_guess.lower()

            if not is_whitelisted(key, allow_rates=allow_rates):
                rejected.append(RejectedChange(key, finding.id, "not in the tuning whitelist"))
                continue

            emit_key = key
            if simplified_active and not emit_raw and key in SIMPLIFIED_GOVERNED_KEYS:
                translated = _translate_to_slider(key)
                if translated is None:
                    rejected.append(
                        RejectedChange(
                            key, finding.id,
                            "simplified tuning is active and no slider-equivalent exists for this key "
                            "(pass disable_simplified_first to override)",
                        )
                    )
                    continue
                emit_key = translated

            if not tune_cfg.has(emit_key):
                rejected.append(
                    RejectedChange(emit_key, finding.id, f"key not found in the source config ({tune_cfg.source}) -- may not exist on this firmware version")
                )
                continue

            current_str = tune_cfg.get(emit_key)
            new_value, reject_reason = _resolve_new_value(emit_key, hint, current_str)
            if reject_reason:
                rejected.append(RejectedChange(emit_key, finding.id, reject_reason))
                continue

            # enable/disable are direct assignments to a known default, not a
            # percentage move off the current value -- the gain-move cap and
            # filter-Nyquist check don't apply to them.
            if hint.direction not in ("enable", "disable"):
                ok, bound_reason = _check_bounds(emit_key, current_str, new_value, loop_rate_hz)
                if not ok:
                    rejected.append(RejectedChange(emit_key, finding.id, bound_reason))
                    continue

            if emit_key not in rollback_map and current_str is not None:
                rollback_map[emit_key] = current_str

            stage_changes.append(
                CLIChange(
                    key=emit_key, old_value=current_str, new_value=new_value,
                    reason=finding.title, finding_id=finding.id, confidence=finding.confidence.value, axis=hint.axis,
                )
            )

        if stage_changes:
            stages.append(stage_changes)

    rollback = [
        CLIChange(key=k, old_value=None, new_value=v, reason="restore pre-change value", finding_id="_rollback", confidence="high")
        for k, v in rollback_map.items()
    ]

    return TuneGeneratorResult(
        stages=stages,
        rollback=rollback,
        rejected=rejected,
        warnings=[],
        simplified_tuning_active=simplified_active,
        source=tune_cfg.source,
    )
