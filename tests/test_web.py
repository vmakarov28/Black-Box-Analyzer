import io
import re
from pathlib import Path

import pytest

from debrief.web.app import create_app

DATA = Path(__file__).parent / "data"


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_index_renders_upload_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Debrief" in html
    assert 'name="log_file"' in html
    assert not re.search(r"{{.*?}}", html)  # no unrendered Jinja leaked through
    for bad in ("http://", "https://", "//cdn."):
        assert bad not in html.lower()


def test_analyze_no_llm_happy_path(client):
    with open(DATA / "good_tune.BBL", "rb") as f:
        resp = client.post(
            "/analyze",
            data={"log_file": (f, "good_tune.BBL"), "no_llm": "on"},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert not re.search(r"{{.*?}}", html)
    assert html.count("data:image/png;base64,") >= 3
    for bad in ("http://", "https://", "//cdn."):
        assert bad not in html.lower()


def test_analyze_with_config_diff_shows_tune_section_and_downloads(client):
    diff_text = (
        "# Betaflight / OMNIBUSF4 (OMNI) 3.1.5 Feb  7 2017 / 22:20:12 (norevision)\n"
        "set p_roll = 19\nset i_roll = 12\nset d_roll = 18\n"
        "set p_pitch = 24\nset i_pitch = 15\nset d_pitch = 23\n"
        "set p_yaw = 70\nset i_yaw = 20\nset d_yaw = 20\n"
        "set gyro_lowpass_hz = 90\nsave\n"
    )
    with open(DATA / "good_tune.BBL", "rb") as f:
        resp = client.post(
            "/analyze",
            data={
                "log_file": (f, "good_tune.BBL"),
                "config_diff_file": (io.BytesIO(diff_text.encode()), "diff.txt"),
                "no_llm": "on",
                "rates": "on",
            },
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Tune generator" in html
    assert "Rates (preference-based" in html
    # rollback/changelog are always offered once a tune plan exists
    assert "data:text/plain" in html or "data:text/markdown" in html


def test_analyze_no_file_returns_friendly_error(client):
    resp = client.post("/analyze", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "No log file selected" in resp.get_data(as_text=True)


def test_analyze_garbage_file_returns_friendly_error_not_a_traceback(client):
    resp = client.post(
        "/analyze",
        data={"log_file": (io.BytesIO(b"not a real blackbox log" * 20), "garbage.bbl"), "no_llm": "on"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    html = resp.get_data(as_text=True)
    assert "Debrief" in html
    assert "Traceback" not in html


def test_analyze_bad_flight_index_returns_friendly_error(client):
    with open(DATA / "good_tune.BBL", "rb") as f:
        resp = client.post(
            "/analyze",
            data={"log_file": (f, "good_tune.BBL"), "flight_index": "99", "no_llm": "on"},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 400


def test_compare_happy_path(client):
    with open(DATA / "good_tune.BBL", "rb") as f1, open(DATA / "good_tune.BBL", "rb") as f2:
        resp = client.post(
            "/compare",
            data={"before_file": (f1, "before.BBL"), "after_file": (f2, "after.BBL")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Compare:" in html
    assert not re.search(r"{{.*?}}", html)


def test_compare_missing_one_file_returns_friendly_error(client):
    with open(DATA / "good_tune.BBL", "rb") as f1:
        resp = client.post(
            "/compare",
            data={"before_file": (f1, "before.BBL")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 400
    assert "before" in resp.get_data(as_text=True).lower()


def test_analyze_multiflight_file_recovers_the_real_flight(client):
    with open(DATA / "stock_tune.BFL", "rb") as f:
        resp = client.post(
            "/analyze",
            data={"log_file": (f, "stock_tune.BFL"), "no_llm": "on"},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200
