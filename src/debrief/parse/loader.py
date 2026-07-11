"""Phase 1 loader: .bbl/.bfl -> list[Flight] (dataframe + header) per file.

One input file can contain multiple embedded flights (Betaflight starts a
new log segment on every arm by default). Each segment gets its own header
block and is decoded/loaded independently, so a corrupt or empty segment
(a stub arm-blip, a truncated final write) never prevents the rest of the
file from loading -- it is recorded in ``LogFile.skipped`` with a reason
instead of raising.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from debrief.parse import header as header_mod
from debrief.parse import setpoint as setpoint_mod
from debrief.parse.backend import run_blackbox_decode
from debrief.parse.errors import LogParseError

_COLNAME_RE = re.compile(r"^(?P<name>.*?)\s*(?:\((?P<unit>[^)]*)\))?$")


@dataclass
class Flight:
    index: int
    df: pd.DataFrame
    header: dict[str, str]
    config: header_mod.HeaderConfig
    duration_s: float
    n_frames: int
    sample_rate_hz: float | None
    column_units: dict[str, str]
    setpoint_axes: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class LogFile:
    path: Path
    flights: list[Flight]
    n_declared_logs: int
    skipped: list[dict]
    decoder_stderr: str

    def __repr__(self) -> str:
        return (
            f"LogFile(path={self.path.name!r}, flights={len(self.flights)}/"
            f"{self.n_declared_logs}, skipped={len(self.skipped)})"
        )


def _split_columns(df: pd.DataFrame) -> dict[str, str]:
    """Rename '<name> (<unit>)' columns to bare names in place; return units map."""
    units: dict[str, str] = {}
    rename = {}
    for col in df.columns:
        m = _COLNAME_RE.match(col.strip())
        name = m.group("name").strip() if m else col.strip()
        unit = m.group("unit") if m else None
        rename[col] = name
        if unit:
            units[name] = unit
    df.rename(columns=rename, inplace=True)
    return units


def _add_friendly_aliases(df: pd.DataFrame, setpoint_axes: list[str]) -> None:
    for i in range(3):
        src = f"gyroADC[{i}]"
        if src in df.columns:
            df[f"gyro[{i}]"] = df[src]
    axis_to_idx = {"roll": 0, "pitch": 1, "yaw": 2}
    for axis in setpoint_axes:
        df[f"setpoint[{axis_to_idx[axis]}]"] = df[f"setpoint_{axis}"]
    if "rcCommand[3]" in df.columns:
        df["throttle"] = df["rcCommand[3]"]
    if "time" in df.columns:
        df["time_s"] = (df["time"] - df["time"].iloc[0]) / 1e6


def load(path: str | Path, output_dir: str | Path | None = None, keep_csv: bool = False) -> LogFile:
    path = Path(path)
    if not path.is_file():
        raise LogParseError(f"no such file: {path}")

    raw = path.read_bytes()
    offsets = header_mod.find_header_offsets(raw)
    if not offsets:
        raise LogParseError(
            f"{path.name}: no 'H Product:' header block found -- not a Betaflight blackbox log"
        )
    n_declared = len(offsets)
    raw_headers = [header_mod.parse_header_block(raw, off) for off in offsets]

    tmp_ctx = None
    if output_dir is not None:
        out_dir = Path(output_dir)
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="debrief_")
        out_dir = Path(tmp_ctx.name)

    try:
        proc = run_blackbox_decode(path, out_dir)

        flights: list[Flight] = []
        skipped: list[dict] = []
        for idx in range(1, n_declared + 1):
            csv_path = out_dir / f"{path.stem}.{idx:02d}.csv"
            if not csv_path.is_file():
                skipped.append({"index": idx, "reason": "decoder produced no CSV for this segment"})
                continue
            try:
                df = pd.read_csv(csv_path, header=0, skipinitialspace=True, low_memory=False)
            except Exception as e:  # malformed/truncated CSV
                skipped.append({"index": idx, "reason": f"CSV read failed: {type(e).__name__}: {e}"})
                continue
            if len(df) == 0:
                skipped.append({"index": idx, "reason": "0 frames decoded (arm blip / stub segment)"})
                continue

            units = _split_columns(df)
            raw_h = raw_headers[idx - 1]
            config = header_mod.normalize(raw_h)
            setpoint_axes = setpoint_mod.add_setpoint_columns(df, config.pid_gains)
            _add_friendly_aliases(df, setpoint_axes)

            warnings: list[str] = []
            if not setpoint_axes:
                warnings.append("setpoint reconstruction unavailable (no P-gain/axisP/gyroADC match)")

            t = df["time"].to_numpy(dtype=np.float64) if "time" in df.columns else None
            if t is not None and len(t) > 1:
                duration_s = float((t[-1] - t[0]) / 1e6)
                dt = np.diff(t)
                median_dt_us = float(np.median(dt))
                sample_rate_hz = 1e6 / median_dt_us if median_dt_us > 0 else None
                gap_thresh = median_dt_us * 20
                n_gaps = int(np.sum(dt > gap_thresh)) if median_dt_us > 0 else 0
                if n_gaps:
                    warnings.append(
                        f"{n_gaps} time gap(s) > 20x median sample interval "
                        f"({median_dt_us:.0f}us) within this segment"
                    )
            else:
                duration_s, sample_rate_hz = 0.0, None

            flights.append(
                Flight(
                    index=idx,
                    df=df,
                    header=raw_h,
                    config=config,
                    duration_s=duration_s,
                    n_frames=len(df),
                    sample_rate_hz=sample_rate_hz,
                    column_units=units,
                    setpoint_axes=setpoint_axes,
                    warnings=warnings,
                )
            )

        if not flights and not skipped:
            # subprocess produced nothing at all and every index missing -> hard failure
            raise LogParseError(
                f"{path.name}: blackbox_decode produced no usable output "
                f"(exit={proc.returncode}); stderr tail:\n"
                + "\n".join(proc.stderr.strip().splitlines()[-10:])
            )

        return LogFile(
            path=path,
            flights=flights,
            n_declared_logs=n_declared,
            skipped=skipped,
            decoder_stderr=proc.stderr,
        )
    finally:
        if tmp_ctx is not None and not keep_csv:
            tmp_ctx.cleanup()
