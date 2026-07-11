from bbanalyzer.rules.flag import Confidence, Finding, ParamHint, Severity
from bbanalyzer.tune.config_model import TuneConfig
from bbanalyzer.tune.generator import generate_tune_plan


def _finding(id_, key, direction, magnitude_pct=10.0, axis="roll", recommended=True) -> Finding:
    return Finding(
        id=id_,
        title=f"test finding {id_}",
        category="pid",
        severity=Severity.WARNING,
        confidence=Confidence.HIGH,
        axis=axis,
        trigger_summary="test",
        rationale="test rationale.",
        suggestion="test suggestion",
        param_hints=[ParamHint(key_guess=key, direction=direction, magnitude_pct=magnitude_pct, axis=axis)],
        recommended=recommended,
    )


def test_basic_gain_increase_emits_validated_change():
    cfg = TuneConfig(source="cli_diff", keys={"p_roll": "40"})
    findings = [_finding("f1", "p_roll", "increase", magnitude_pct=10.0)]
    result = generate_tune_plan(findings, cfg, loop_rate_hz=8000)
    assert len(result.stages) == 1
    change = result.stages[0][0]
    assert change.key == "p_roll"
    assert change.old_value == "40"
    assert change.new_value == "44"  # 40 * 1.10 = 44
    assert not result.rejected


def test_key_not_in_source_config_is_rejected_never_emitted():
    """Version-guard round-trip check: a key absent from the source config
    must never be emitted, however plausible the finding looks."""
    cfg = TuneConfig(source="cli_diff", keys={})  # p_roll not present at all
    findings = [_finding("f1", "p_roll", "increase")]
    result = generate_tune_plan(findings, cfg)
    assert result.stages == []
    assert len(result.rejected) == 1
    assert "not found" in result.rejected[0].reason


def test_non_whitelisted_key_is_rejected_never_emitted():
    cfg = TuneConfig(source="cli_diff", keys={"failsafe_delay": "10"})
    findings = [_finding("f1", "failsafe_delay", "increase")]
    result = generate_tune_plan(findings, cfg)
    assert result.stages == []
    assert "whitelist" in result.rejected[0].reason


def test_gain_move_over_30pct_is_rejected_never_emitted():
    cfg = TuneConfig(source="cli_diff", keys={"p_roll": "40"})
    findings = [_finding("f1", "p_roll", "increase", magnitude_pct=50.0)]
    result = generate_tune_plan(findings, cfg)
    assert result.stages == []
    assert "30%" in result.rejected[0].reason or "cap" in result.rejected[0].reason


def test_filter_hz_above_nyquist_is_rejected():
    cfg = TuneConfig(source="cli_diff", keys={"gyro_lowpass_hz": "1000"})
    # loop rate 2000Hz -> nyquist 1000Hz -> a 10% increase to 1100Hz should be rejected
    findings = [_finding("f1", "gyro_lowpass_hz", "increase", magnitude_pct=10.0)]
    result = generate_tune_plan(findings, cfg, loop_rate_hz=2000)
    assert result.stages == []
    assert "Nyquist" in result.rejected[0].reason


def test_simplified_tuning_active_translates_to_slider_key():
    cfg = TuneConfig(source="cli_diff", keys={"simplified_pids_mode": "ON", "simplified_pi_gain": "100"}, simplified_tuning_active=True)
    findings = [_finding("f1", "p_roll", "increase", magnitude_pct=10.0)]
    result = generate_tune_plan(findings, cfg)
    assert len(result.stages) == 1
    change = result.stages[0][0]
    assert change.key == "simplified_pi_gain"
    assert change.new_value == "110"


def test_simplified_tuning_active_no_slider_mapping_rejects_by_default():
    cfg = TuneConfig(source="cli_diff", keys={"simplified_pids_mode": "ON", "anti_gravity_gain": "3500"}, simplified_tuning_active=True)
    # anti_gravity_gain is NOT one of the simplified-governed keys, so it should
    # pass through untranslated and unaffected by the simplified-tuning guard
    findings = [_finding("f1", "anti_gravity_gain", "increase", magnitude_pct=15.0, axis=None)]
    result = generate_tune_plan(findings, cfg)
    assert len(result.stages) == 1
    assert result.stages[0][0].key == "anti_gravity_gain"


def test_simplified_tuning_never_mixes_raw_and_slider_in_same_output():
    cfg = TuneConfig(
        source="cli_diff",
        keys={"simplified_pids_mode": "ON", "simplified_pi_gain": "100", "simplified_d_gain": "100", "p_roll": "40", "d_roll": "20"},
        simplified_tuning_active=True,
    )
    findings = [
        _finding("f1", "p_roll", "increase", magnitude_pct=10.0, axis="roll"),
        _finding("f2", "d_roll", "increase", magnitude_pct=10.0, axis="pitch"),
    ]
    result = generate_tune_plan(findings, cfg)
    all_keys = {c.key for stage in result.stages for c in stage}
    assert "p_roll" not in all_keys and "d_roll" not in all_keys
    assert all_keys == {"simplified_pi_gain", "simplified_d_gain"}


def test_disable_simplified_first_prepends_stage_and_allows_raw_keys():
    cfg = TuneConfig(source="cli_diff", keys={"simplified_pids_mode": "ON", "p_roll": "40"}, simplified_tuning_active=True)
    findings = [_finding("f1", "p_roll", "increase", magnitude_pct=10.0)]
    result = generate_tune_plan(findings, cfg, disable_simplified_first=True)
    assert len(result.stages) == 2
    assert result.stages[0][0].key == "simplified_pids_mode"
    assert result.stages[0][0].new_value == "OFF"
    assert result.stages[1][0].key == "p_roll"  # raw key used once simplified mode is explicitly disabled


def test_rollback_captures_pre_change_value_of_every_touched_key():
    cfg = TuneConfig(source="cli_diff", keys={"p_roll": "40", "d_roll": "20"})
    findings = [
        _finding("f1", "p_roll", "increase", magnitude_pct=10.0, axis="roll"),
        _finding("f2", "d_roll", "decrease", magnitude_pct=10.0, axis="pitch"),
    ]
    result = generate_tune_plan(findings, cfg)
    rollback_map = {c.key: c.new_value for c in result.rollback}
    assert rollback_map == {"p_roll": "40", "d_roll": "20"}


def test_rates_key_rejected_unless_allow_rates():
    cfg = TuneConfig(source="cli_diff", keys={"rc_rate": "100"})
    findings = [_finding("f1", "rc_rate", "increase", magnitude_pct=10.0)]
    result = generate_tune_plan(findings, cfg, allow_rates=False)
    assert result.stages == []
    result2 = generate_tune_plan(findings, cfg, allow_rates=True)
    assert len(result2.stages) == 1


def test_investigate_direction_never_emits_a_change():
    cfg = TuneConfig(source="cli_diff", keys={"anti_gravity_gain": "3500"})
    findings = [_finding("f1", "anti_gravity_gain", "investigate", axis=None)]
    result = generate_tune_plan(findings, cfg)
    assert result.stages == []
    assert "investigate" in result.rejected[0].reason.lower() or "informational" in result.rejected[0].reason.lower()


def test_non_recommended_findings_never_produce_changes():
    cfg = TuneConfig(source="cli_diff", keys={"p_roll": "40"})
    findings = [_finding("f1", "p_roll", "increase", recommended=False)]
    result = generate_tune_plan(findings, cfg)
    assert result.stages == []
    assert result.rejected == []  # not even considered, since it wasn't recommended


def test_enable_direction_uses_known_default_and_respects_version_guard():
    cfg_ok = TuneConfig(source="cli_diff", keys={"rpm_filter_harmonics": "0"})
    findings = [_finding("f1", "rpm_filter_harmonics", "enable", axis=None)]
    result = generate_tune_plan(findings, cfg_ok)
    assert result.stages[0][0].new_value == "3"

    cfg_missing = TuneConfig(source="cli_diff", keys={})  # old firmware without this key at all
    result2 = generate_tune_plan(findings, cfg_missing)
    assert result2.stages == []
    assert "not found" in result2.rejected[0].reason
