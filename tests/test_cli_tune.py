from pathlib import Path

from bbanalyzer.cli import main

DATA = Path(__file__).parent / "data"

# Matches good_tune.BBL's actual header PID gains (see test_loader.py) so the
# reconcile check finds agreement rather than firing a mismatch warning.
MATCHING_DIFF = """\
# Betaflight / OMNIBUSF4 (OMNI) 3.1.5 Feb  7 2017 / 22:20:12 (norevision)
set p_roll = 19
set i_roll = 12
set d_roll = 18
set p_pitch = 24
set i_pitch = 15
set d_pitch = 23
set p_yaw = 70
set i_yaw = 20
set d_yaw = 20
set gyro_lowpass_hz = 90
save
"""


def test_cli_analyze_with_config_diff_writes_tune_files(tmp_path, capsys):
    diff_path = tmp_path / "diff.txt"
    diff_path.write_text(MATCHING_DIFF)
    tune_dir = tmp_path / "tune"
    out = tmp_path / "report.html"

    rc = main([
        "analyze", str(DATA / "good_tune.BBL"), "-o", str(out), "--no-llm",
        "--config-diff", str(diff_path), "--tune-output-dir", str(tune_dir),
    ])
    assert rc == 0
    assert out.is_file()
    # rollback.txt and changelog.md always written, even if zero stages
    assert (tune_dir / "rollback.txt").is_file()
    assert (tune_dir / "changelog.md").is_file()
    assert not (tune_dir / "apply_all.txt").exists()


def test_cli_analyze_with_mismatched_config_diff_warns_loudly(tmp_path, capsys):
    mismatched = MATCHING_DIFF.replace("p_roll = 19", "p_roll = 90")
    diff_path = tmp_path / "diff.txt"
    diff_path.write_text(mismatched)
    out = tmp_path / "report.html"

    rc = main(["analyze", str(DATA / "good_tune.BBL"), "-o", str(out), "--no-llm", "--config-diff", str(diff_path)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "mismatch" in err.lower()
    html = out.read_text(encoding="utf-8")
    assert "mismatch" in html.lower()  # loud warning surfaces in the report itself, not just stderr


def test_cli_analyze_rates_flag_adds_rates_section(tmp_path):
    out = tmp_path / "report.html"
    rc = main(["analyze", str(DATA / "good_tune.BBL"), "-o", str(out), "--no-llm", "--rates"])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "Rates (preference-based" in html


def test_cli_analyze_without_rates_flag_omits_rates_section(tmp_path):
    out = tmp_path / "report.html"
    rc = main(["analyze", str(DATA / "good_tune.BBL"), "-o", str(out), "--no-llm"])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "Rates (preference-based" not in html


def test_cli_compare_mode(tmp_path):
    out = tmp_path / "compare.html"
    rc = main(["analyze", "--compare", str(DATA / "good_tune.BBL"), str(DATA / "good_tune.BBL"), "-o", str(out)])
    assert rc == 0
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    assert "Compare:" in html


def test_cli_requires_log_unless_compare(capsys):
    rc = None
    try:
        main(["analyze"])
    except SystemExit as e:
        rc = e.code
    assert rc not in (0, None)
