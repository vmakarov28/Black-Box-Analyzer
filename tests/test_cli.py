from pathlib import Path

import pandas as pd

from debrief.cli import main
from debrief.parse.header import HeaderConfig
from debrief.parse.loader import Flight, LogFile
from debrief.pipeline import select_flight

DATA = Path(__file__).parent / "data"


def _dummy_flight(index: int, duration_s: float) -> Flight:
    return Flight(
        index=index,
        df=pd.DataFrame({"time_s": [0.0]}),
        header={},
        config=HeaderConfig(raw={}),
        duration_s=duration_s,
        n_frames=1,
        sample_rate_hz=1000.0,
        column_units={},
        setpoint_axes=[],
    )


def test_select_flight_picks_longest_when_multiple():
    lf = LogFile(path=Path("dummy.bbl"), flights=[_dummy_flight(1, 5.0), _dummy_flight(2, 40.0)], n_declared_logs=2, skipped=[], decoder_stderr="")
    chosen, messages = select_flight(lf, index=None)
    assert chosen.index == 2
    assert any("Multiple flights found" in m for m in messages)


def test_select_flight_honors_explicit_index():
    lf = LogFile(path=Path("dummy.bbl"), flights=[_dummy_flight(1, 5.0), _dummy_flight(2, 40.0)], n_declared_logs=2, skipped=[], decoder_stderr="")
    chosen, messages = select_flight(lf, index=1)
    assert chosen.index == 1
    assert messages == []


def test_cli_analyze_no_llm(tmp_path, capsys):
    out = tmp_path / "report.html"
    rc = main(["analyze", str(DATA / "good_tune.BBL"), "-o", str(out), "--no-llm"])
    assert rc == 0
    assert out.is_file()
    captured = capsys.readouterr()
    assert "Report written to" in captured.out


def test_cli_analyze_corrupt_multisegment_file_recovers_the_real_flight(tmp_path, capsys):
    # stock_tune.BFL has 14 embedded segments, 13 empty arm-blips and one
    # real flight (#12) -- only one lands in lf.flights, so this exercises
    # the "skip corrupt segments, analyze what's left" path end to end,
    # not the multi-valid-flight selection message (see test_loader.py for
    # that split).
    out = tmp_path / "report.html"
    rc = main(["analyze", str(DATA / "stock_tune.BFL"), "-o", str(out), "--no-llm"])
    assert rc == 0
    assert out.is_file()


def test_cli_analyze_garbage_file(tmp_path, capsys):
    garbage = tmp_path / "not_a_log.bbl"
    garbage.write_bytes(b"nope" * 100)
    out = tmp_path / "report.html"
    rc = main(["analyze", str(garbage), "-o", str(out), "--no-llm"])
    assert rc == 1
    assert not out.exists()
    captured = capsys.readouterr()
    assert "error:" in captured.err


def test_cli_analyze_bad_flight_index(tmp_path, capsys):
    out = tmp_path / "report.html"
    rc = main(["analyze", str(DATA / "good_tune.BBL"), "-o", str(out), "--no-llm", "--flight-index", "99"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
