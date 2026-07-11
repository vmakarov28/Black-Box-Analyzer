from pathlib import Path

from debrief.dsp import compute_flight_metrics
from debrief.parse import header as header_mod
from debrief.parse import load
from debrief.rules import diagnose
from debrief.rules.config_checks import run_config_checks
from debrief.rules.flag import Severity

DATA = Path(__file__).parent / "data"


def _cfg(**overrides):
    raw = {}
    cfg = header_mod.normalize(raw)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def test_bidir_dshot_on_rpm_filter_off_fires_warning():
    cfg = _cfg(dshot_bidir=True, rpm_filter_enabled=False, rpm_filter_harmonics=0)
    findings = run_config_checks(cfg)
    ids = [f.id for f in findings]
    assert "bidir_dshot_rpm_filter_off" in ids
    f = next(f for f in findings if f.id == "bidir_dshot_rpm_filter_off")
    assert f.severity == Severity.WARNING


def test_bidir_dshot_on_rpm_filter_on_does_not_fire():
    cfg = _cfg(dshot_bidir=True, rpm_filter_enabled=True, rpm_filter_harmonics=3)
    findings = run_config_checks(cfg)
    ids = [f.id for f in findings]
    assert "bidir_dshot_rpm_filter_off" not in ids


def test_dynamic_idle_unset_fires():
    cfg = _cfg(dyn_idle_min_rpm=0)
    findings = run_config_checks(cfg)
    assert "dynamic_idle_unset" in [f.id for f in findings]


def test_dynamic_notch_disabled_fires():
    cfg = _cfg(dyn_notch_enabled=False)
    findings = run_config_checks(cfg)
    assert "dynamic_notch_disabled" in [f.id for f in findings]


def test_simplified_tuning_active_is_info_only():
    cfg = _cfg(simplified_tuning_active=True)
    findings = run_config_checks(cfg)
    f = next(f for f in findings if f.id == "simplified_tuning_active")
    assert f.severity == Severity.INFO
    assert f.param_hints == []  # never a "recommended change" candidate


def test_no_findings_on_clean_config():
    cfg = _cfg(
        dshot_bidir=True,
        rpm_filter_enabled=True,
        rpm_filter_harmonics=3,
        motor_poles=14,
        dyn_idle_min_rpm=550,
        dyn_notch_enabled=True,
        simplified_tuning_active=False,
        gyro_lowpass_hz=100,
    )
    findings = run_config_checks(cfg)
    assert findings == []


def test_diagnose_on_real_log_end_to_end():
    lf = load(DATA / "good_tune.BBL")
    f = lf.flights[0]
    m = compute_flight_metrics(f)
    findings = diagnose(m, f.config)

    assert len(findings) > 0
    # sorted descending by (severity, confidence)
    ranks = [(x.severity.rank(), x.confidence.rank()) for x in findings]
    assert ranks == sorted(ranks, reverse=True)

    recommended = [x for x in findings if x.recommended]
    assert len(recommended) <= 3
    assert all(x.param_hints for x in recommended)
    assert all(x.severity != Severity.INFO for x in recommended)

    # no two recommended findings claim the same (key, axis)
    claimed = []
    for x in recommended:
        for h in x.param_hints:
            claimed.append((h.key_guess, h.axis))
    assert len(claimed) == len(set(claimed))

    # this specific log has severe roll propwash bounce-back (rms ~329 deg/s,
    # bounce_back_rate ~0.95, both well past the CRITICAL thresholds) -- must surface
    ids = [x.id for x in findings]
    assert "propwash_bounce_back_roll" in ids
    propwash = next(x for x in findings if x.id == "propwash_bounce_back_roll")
    assert propwash.severity == Severity.CRITICAL


def test_diagnose_on_corrupt_flight_does_not_raise():
    lf = load(DATA / "stock_tune.BFL")
    f = lf.flights[0]
    m = compute_flight_metrics(f)
    findings = diagnose(m, f.config)
    assert isinstance(findings, list)
