"""Phase 2 validation gate: run the real Plasmatree PID-Analyzer on a sample
log and numerically reconcile our step-response/noise output against it.

Requires vendor/PID-Analyzer (see scripts/setup.sh --with-validator) --
dev-only, never imported by bbanalyzer itself at runtime.

Usage (from repo root, inside the WSL venv):
    python tools/validate_step_response.py tests/data/good_tune.BBL
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bbanalyzer.dsp.step_response import _extract_step_metrics  # noqa: E402
from bbanalyzer.parse import load as bb_load  # noqa: E402
from bbanalyzer.dsp.metrics import _throttle_pct  # noqa: E402


def _shim_legacy_numpy_api():
    """PID-Analyzer.py (2018) calls np.histogram/np.histogram2d with the
    'normed' kwarg, removed in numpy>=1.24 in favor of 'density'. Patched
    here rather than editing the vendored reference file, and only for the
    duration of running it -- never applied to bbanalyzer's own code.
    """
    orig_hist = np.histogram
    orig_hist2d = np.histogram2d

    def hist(*args, **kwargs):
        if "normed" in kwargs:
            kwargs["density"] = kwargs.pop("normed")
        return orig_hist(*args, **kwargs)

    def hist2d(*args, **kwargs):
        kwargs.pop("normed", None)
        # Py2->3 relic: some call sites pass bins=[101, len(freq)/4], a float
        # in Py3 (true division). numpy now requires integer bin counts.
        if "bins" in kwargs and isinstance(kwargs["bins"], (list, tuple)):
            kwargs["bins"] = [int(round(b)) for b in kwargs["bins"]]
        elif len(args) >= 5 and isinstance(args[4], (list, tuple)):
            args = list(args)
            args[4] = [int(round(b)) for b in args[4]]
        return orig_hist2d(*args, **kwargs)

    np.histogram = hist
    np.histogram2d = hist2d


def _load_reference_module():
    _shim_legacy_numpy_api()
    spec = importlib.util.spec_from_file_location(
        "pid_analyzer_ref", ROOT / "vendor" / "PID-Analyzer" / "PID-Analyzer.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pid_analyzer_ref"] = mod
    spec.loader.exec_module(mod)
    return mod


def run_reference(pidmod, bbl_path: Path, blackbox_decode: Path):
    """Drives PID-Analyzer's real decode -> CSV read -> Trace(roll/pitch/yaw)
    pipeline directly, deliberately bypassing CSV_log.__init__'s plotting
    calls (plot_all_resp/plot_all_noise) -- those hit an unrelated
    matplotlib API mismatch (this reference script is from 2018) and we
    only need the numeric Trace objects, not a rendered figure.
    """
    bb = pidmod.BB_log.__new__(pidmod.BB_log)
    bb.blackbox_decode_bin_path = str(blackbox_decode)
    bb.tmp_dir = str(bbl_path.parent / "validate")
    Path(bb.tmp_dir).mkdir(parents=True, exist_ok=True)
    bb.name = "validate"
    bb.show = "N"
    bb.noise_bounds = [[1.0, 10.1], [1.0, 100.0], [1.0, 100.0], [0.0, 4.0]]

    loglist = bb.decode(str(bbl_path))
    heads = bb.beheader(loglist)
    head = heads[0]
    csv_path = head["tempFile"][:-3] + "01.csv"

    csvlog = pidmod.CSV_log.__new__(pidmod.CSV_log)
    csvlog.file = csv_path
    csvlog.name = "validate"
    csvlog.headdict = head
    csvlog.data = csvlog.readcsv(csv_path)
    csvlog.traces = csvlog.find_traces(csvlog.data)
    roll, pitch, yaw = (pidmod.Trace(t) for t in csvlog.traces)
    csvlog.roll, csvlog.pitch, csvlog.yaw = roll, pitch, yaw
    return csvlog


def compare_curves(name: str, ours_t, ours_y, ref_t, ref_y) -> dict:
    if ours_y is None or ref_y is None:
        return {"name": name, "comparable": False}
    ref_interp = np.interp(ours_t, ref_t, ref_y)
    diff = ours_y - ref_interp
    corr = float(np.corrcoef(ours_y, ref_interp)[0, 1]) if np.std(ours_y) > 0 and np.std(ref_interp) > 0 else None
    return {
        "name": name,
        "comparable": True,
        "correlation": corr,
        "max_abs_diff": float(np.max(np.abs(diff))),
        "rmse": float(np.sqrt(np.mean(diff**2))),
        "our_peak": float(np.max(ours_y)),
        "ref_peak": float(np.max(ref_interp)),
    }


def main():
    bbl_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "data" / "good_tune.BBL"
    blackbox_decode = ROOT / "vendor" / "blackbox-tools" / "obj" / "blackbox_decode"
    pid_analyzer_src = ROOT / "vendor" / "PID-Analyzer" / "PID-Analyzer.py"
    if not pid_analyzer_src.is_file():
        print("vendor/PID-Analyzer not present. Run: scripts/setup.sh --with-validator")
        sys.exit(1)

    pidmod = _load_reference_module()

    with tempfile.TemporaryDirectory(prefix="pidval_") as tmp:
        bbl_copy = Path(tmp) / bbl_arg.name
        shutil.copy(bbl_arg, bbl_copy)
        print(f"== Running reference PID-Analyzer on {bbl_arg.name} ==")
        ref_csvlog = run_reference(pidmod, bbl_copy, blackbox_decode)

    print(f"== Running our loader + DSP on {bbl_arg.name} ==")
    lf = bb_load(bbl_arg)
    flight = lf.flights[0]
    df = flight.df
    time_s = df["time_s"].to_numpy(dtype=np.float64)
    throttle_pct = _throttle_pct(df, flight.header)

    from bbanalyzer.dsp.step_response import compute_step_response

    axis_map = {"roll": ref_csvlog.roll, "pitch": ref_csvlog.pitch, "yaw": ref_csvlog.yaw}
    print(f"\n{'axis':6s} {'metric':22s} {'ours':>10s} {'reference (derived)':>20s}")
    for axis, idx in [("roll", 0), ("pitch", 1), ("yaw", 2)]:
        setpoint = df[f"setpoint[{idx}]"].to_numpy(dtype=np.float64)
        gyro = df[f"gyro[{idx}]"].to_numpy(dtype=np.float64)
        ours = compute_step_response(time_s, setpoint, gyro, throttle_pct, axis=axis)

        ref_trace = axis_map[axis]
        ref_time = ref_trace.time_resp
        ref_resp_low = ref_trace.resp_low[0]
        ref_resp_high = ref_trace.resp_high[0] if hasattr(ref_trace, "resp_high") else None

        cmp_low = compare_curves("response (low input)", ours.time_s, ours.response_low, ref_time, ref_resp_low)
        print(f"\n--- {axis} ---")
        print("low-input response curve comparison:", cmp_low)

        ref_metrics = _extract_step_metrics(ref_time, ref_resp_low)
        print(f"{axis:6s} {'rise_time_s':22s} {str(ours.rise_time_s):>10s} {str(ref_metrics['rise_time_s']):>20s}")
        print(f"{axis:6s} {'overshoot_pct':22s} {str(ours.overshoot_pct):>10s} {str(ref_metrics['overshoot_pct']):>20s}")
        print(f"{axis:6s} {'settling_time_s':22s} {str(ours.settling_time_s):>10s} {str(ref_metrics['settling_time_s']):>20s}")

        # also compare the ALL-input averaged curve (ours) against reference's
        # low-input curve isn't quite apples to apples if high-input windows
        # exist; report both so discrepancies are legible, not hidden.
        cmp_all_vs_low = compare_curves("ours(all) vs ref(low)", ours.time_s, ours.response, ref_time, ref_resp_low)
        print("ours(all-input) vs ref(low-input) curve comparison:", cmp_all_vs_low)

    from bbanalyzer.dsp.noise import compute_noise_heatmap

    print("\n=== Noise heatmap (throttle x frequency) ===")
    for axis, idx in [("roll", 0), ("pitch", 1), ("yaw", 2)]:
        gyro = df[f"gyro[{idx}]"].to_numpy(dtype=np.float64)
        ours_hm = compute_noise_heatmap(time_s, gyro, throttle_pct, axis=axis)
        ref_trace = axis_map[axis]
        ref_ng = ref_trace.noise_gyro

        ours_energy = float(ours_hm.psd.sum())
        ref_energy = float(ref_ng["hist2d_sm"].sum())
        ours_mean_f = float(np.average(np.tile(ours_hm.freq_hz[:, None], (1, ours_hm.psd.shape[1])), weights=np.clip(ours_hm.psd, 0, None)))
        ref_freq_axis = ref_ng["freq_axis"]
        ref_hist = ref_ng["hist2d_sm"]
        ref_mean_f = float(
            np.average(np.tile(ref_freq_axis[: ref_hist.shape[0], None], (1, ref_hist.shape[1])), weights=np.clip(ref_hist, 0, None))
        )
        print(
            f"{axis:6s} total_energy ours={ours_energy:.3e} ref={ref_energy:.3e} | "
            f"energy-weighted mean freq ours={ours_mean_f:.1f}Hz ref={ref_mean_f:.1f}Hz"
        )


if __name__ == "__main__":
    main()
