from pathlib import Path

from bbanalyzer.parse.header import normalize
from bbanalyzer.tune.diff_parser import parse_cli_diff
from bbanalyzer.tune.output import write_tune_files
from bbanalyzer.tune.reconcile import check_diff_vs_header_agreement
from bbanalyzer.tune.whitelist import RATES_KEYS, TUNING_WHITELIST, is_whitelisted

SAMPLE_DIFF = """\
# diff

# version
# Betaflight / STM32F405 (S405) 4.4.3 Jul 12 2023 / 09:12:34 (norevision)

# name: MyQuad

set p_roll = 45
set i_roll = 80
set d_roll = 30
set simplified_pids_mode = OFF
set gyro_lowpass_hz = 100

save
"""


def test_diff_parser_extracts_keys_and_version():
    cfg = parse_cli_diff(SAMPLE_DIFF)
    assert cfg.source == "cli_diff"
    assert cfg.keys["p_roll"] == "45"
    assert cfg.keys["gyro_lowpass_hz"] == "100"
    assert cfg.firmware_version == (4, 4, 3)
    assert cfg.firmware_target == "STM32F405"
    assert cfg.simplified_tuning_active is False


def test_diff_parser_detects_simplified_tuning_on():
    text = SAMPLE_DIFF.replace("simplified_pids_mode = OFF", "simplified_pids_mode = ON")
    cfg = parse_cli_diff(text)
    assert cfg.simplified_tuning_active is True


def test_diff_parser_ignores_comments_and_blank_lines():
    cfg = parse_cli_diff("# just a comment\n\n   \nset p_roll = 10\n")
    assert cfg.keys == {"p_roll": "10"}


# --- whitelist -------------------------------------------------------

def test_whitelist_excludes_dangerous_categories():
    dangerous = {"motor_pwm_protocol", "failsafe_delay", "vtx_freq", "osd_warnings", "serialrx_provider", "dshot_bidir"}
    for key in dangerous:
        assert not is_whitelisted(key), f"{key} must never be whitelisted"


def test_whitelist_includes_tuning_domain_keys():
    for key in ("p_roll", "d_min_roll", "gyro_lowpass_hz", "dyn_notch_min_hz", "rpm_filter_harmonics", "dyn_idle_min_rpm", "tpa_rate", "anti_gravity_gain", "simplified_pi_gain"):
        assert is_whitelisted(key), f"{key} should be in the tuning whitelist"


def test_rates_keys_only_whitelisted_with_allow_rates():
    assert not is_whitelisted("rc_rate")
    assert is_whitelisted("rc_rate", allow_rates=True)
    assert TUNING_WHITELIST.isdisjoint(RATES_KEYS)  # rates keys are gated separately, not baked into the default whitelist


# --- reconcile ---------------------------------------------------------

def _header_cfg(raw):
    return normalize(raw)


def test_reconcile_flags_pid_mismatch():
    header_cfg = _header_cfg({"rollPID": "40,12,18", "Firmware revision": "Betaflight 4.4.3 (abc1234) STM32F405"})
    diff_cfg = parse_cli_diff(SAMPLE_DIFF)  # has p_roll=45, differs from header's 40
    warnings = check_diff_vs_header_agreement(diff_cfg, header_cfg)
    assert any("P[roll]" in w for w in warnings)


def test_reconcile_no_warning_when_they_agree():
    header_cfg = _header_cfg({"rollPID": "45,80,30", "Firmware revision": "Betaflight 4.4.3 (abc1234) STM32F405"})
    diff_cfg = parse_cli_diff(SAMPLE_DIFF)
    warnings = check_diff_vs_header_agreement(diff_cfg, header_cfg)
    assert warnings == []


def test_reconcile_flags_firmware_version_mismatch():
    header_cfg = _header_cfg({"Firmware revision": "Betaflight 4.3.0 (abc1234) STM32F405"})
    diff_cfg = parse_cli_diff(SAMPLE_DIFF)  # 4.4.3
    warnings = check_diff_vs_header_agreement(diff_cfg, header_cfg)
    assert any("Firmware version mismatch" in w for w in warnings)


# --- output --------------------------------------------------------------

def test_write_tune_files_never_writes_an_apply_all_file(tmp_path):
    from bbanalyzer.tune.generator import CLIChange, TuneGeneratorResult

    result = TuneGeneratorResult(
        stages=[[CLIChange("p_roll", "40", "44", "reason 1", "f1", "high")], [CLIChange("d_roll", "20", "18", "reason 2", "f2", "medium")]],
        rollback=[CLIChange("p_roll", None, "40", "restore", "_rollback", "high"), CLIChange("d_roll", None, "20", "restore", "_rollback", "high")],
        rejected=[],
        warnings=[],
        simplified_tuning_active=False,
        source="cli_diff",
    )
    written = write_tune_files(result, tmp_path)
    names = {p.name for p in Path(tmp_path).iterdir()}
    assert names == {"stage1.txt", "stage2.txt", "rollback.txt", "changelog.md"}
    assert "apply_all" not in " ".join(names)
    assert "set p_roll = 44" in written["stage1"].read_text()
    assert "save" in written["stage1"].read_text()
    assert "set p_roll = 40" in written["rollback"].read_text()
    # comments never trail on the same line as a `set` command
    for line in written["stage1"].read_text().splitlines():
        if line.strip().startswith("set "):
            assert "#" not in line
