"""Locates and invokes the blackbox_decode binary.

Why blackbox_decode (C binary, subprocess) over orangebox (pure Python), per
the Phase 1 evaluation (see docs/phase1-parser-evaluation.md for the full
writeup with numbers):

* It is the exact tool Plasmatree PID-Analyzer shells out to. Wrapping it
  means our Phase 2 validation gate compares against the same decoded
  frames PID-Analyzer sees, not a second independent (and possibly
  divergent) decode -- any discrepancy we find is provably in the DSP math,
  not in decoding.
* On a real-world multi-segment .BFL (14 embedded logs, several truncated
  arm-blip stubs), blackbox_decode decoded every segment cleanly and kept
  going. orangebox 0.5.0 raised an uncaught ValueError
  ("read length must be non-negative or -1") while sizing the final
  segment and aborted the whole file.
* It's a one-time local build (`make` in vendor/blackbox-tools), not a
  runtime network dependency -- consistent with the "nothing phones home
  at runtime" requirement.

The header/config dict is NOT read from blackbox_decode's output at all --
see header.py, which parses the plain-text "H key:value" lines straight out
of the raw log bytes. That sidesteps picking a decoder for the one part of
the file (the header) that's trivial to read ourselves with zero dependency.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from debrief.parse.errors import LogParseError

_REPO_DEFAULT = Path(__file__).resolve().parents[3] / "vendor" / "blackbox-tools" / "obj" / "blackbox_decode"


def find_blackbox_decode() -> Path:
    """Resolve the blackbox_decode binary, in priority order:
    1. $DEBRIEF_BLACKBOX_DECODE
    2. vendor/blackbox-tools/obj/blackbox_decode next to a repo checkout (dev)
    3. blackbox_decode on $PATH
    """
    env = os.environ.get("DEBRIEF_BLACKBOX_DECODE")
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise LogParseError(f"DEBRIEF_BLACKBOX_DECODE={env!r} does not point to a file")

    if _REPO_DEFAULT.is_file():
        return _REPO_DEFAULT

    on_path = shutil.which("blackbox_decode")
    if on_path:
        return Path(on_path)

    raise LogParseError(
        "blackbox_decode binary not found. Run scripts/setup.sh once to clone+build "
        "betaflight/blackbox-tools, or set DEBRIEF_BLACKBOX_DECODE to an existing binary."
    )


def run_blackbox_decode(input_path: Path, output_dir: Path) -> subprocess.CompletedProcess:
    """Decode every embedded log in *input_path* into output_dir/<stem>.NN.csv.

    Never raises on a non-zero/partial-corruption exit -- the caller decides
    per-flight what to do with whatever CSVs actually landed on disk plus
    the captured stderr.
    """
    binary = find_blackbox_decode()
    output_dir.mkdir(parents=True, exist_ok=True)
    args = [
        str(binary),
        "--unit-rotation", "deg/s",
        "--unit-frame-time", "us",
        "--unit-vbat", "V",
        "--unit-amperage", "A",
        "--unit-acceleration", "g",
        "--output-dir", str(output_dir),
        str(input_path),
    ]
    return subprocess.run(args, capture_output=True, text=True, timeout=600)
