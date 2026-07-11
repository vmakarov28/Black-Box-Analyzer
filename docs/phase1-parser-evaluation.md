# Phase 1: parser backend evaluation

Two local, offline options were evaluated for decoding `.bbl`/`.bfl` frame
data: **orangebox** (pure-Python parser) and **blackbox_decode** (the C
binary from `betaflight/blackbox-tools`, wrapped via subprocess). Header/CLI
config parsing is handled separately by neither of these — see below.

## Method

`tools/eval_parsers.py` runs both backends against the same two sample logs
(from Plasmatree/PID-Analyzer's example set) and compares frame counts,
timing, and per-cell numeric agreement.

- `tests/data/good_tune.BBL` — single embedded flight, 154,311 frames, BF 3.1.5.
- `tests/data/stock_tune.BFL` — **14** embedded flights in one file: 13 are
  empty arm-blip stub segments (armed for under a second, no useful data)
  and 1 is a real 520,342-frame flight. This file was not hand-picked for
  being messy — it's the stock example log — and turned out to be a good
  real-world corruption/multi-flight test case for free.

## Results

| | orangebox 0.5.0 | blackbox_decode (betaflight/blackbox-tools, built locally) |
|---|---|---|
| `good_tune.BBL` parse time | 3.0s (154,311 frames) | 1.2s (154,311 frames, via subprocess+CSV) |
| `good_tune.BBL` value agreement | 154,306/154,306 aligned frames, 0 mismatches on 30 shared numeric columns (excluding `rcCommand[3]`, see note) | reference |
| `stock_tune.BFL` (14 embedded logs, 13 corrupt/empty stubs) | **Crashes**: `ValueError: read length must be non-negative or -1` while sizing the final segment. Whole file unreadable, including the one good flight. | Decodes all 14 segments cleanly; reports "0 frames" for the 13 stubs and correctly extracts the 520,342-frame real flight. Exit code 0. |
| Header/config access | Structured header dict built in | None (writes CSV only) — not used for this reason; see below |
| Runtime dependency | `pip install orangebox` (has a broken `entry_points` metadata that spams a `pip install` error line, though the import itself works) | one-time local `make` build from `betaflight/blackbox-tools` source |

Note on `rcCommand[3]` (throttle) mismatches in the value-agreement check:
these are integer-vs-rounded-float display differences in the raw comparison
script, not decode divergence — every other of the 30 shared numeric columns
matched exactly to 1e-6 across all 154,306 aligned frames.

## Decision: blackbox_decode

1. **It's what the validation-gate reference already uses.** Plasmatree
   PID-Analyzer (`vendor/PID-Analyzer/PID-Analyzer.py`, `BB_log.decode()`)
   shells out to `blackbox_decode` and reads its CSV with pandas. Wrapping
   the same binary means Phase 2's step-response/spectral reconciliation
   compares against literally the same decoded frames PID-Analyzer sees —
   any discrepancy found there is provably in the DSP math, not a second,
   independently-buggy decode.
2. **It survived the real corrupt/multi-flight file; orangebox did not.**
   An uncaught `ValueError` that aborts the entire file on one bad segment
   is disqualifying for a tool whose Phase 1 requirement is "handle
   multi-flight logs and corrupt logs gracefully" — one arm-blip should
   never take down the whole log.
3. **Unit conversion is offloaded to the reference implementation.**
   `--unit-rotation deg/s` etc. let blackbox_decode apply `gyro_scale` and
   friends correctly instead of us re-deriving raw-ADC scaling per firmware
   version.
4. Speed is a wash at these sizes (low single-digit seconds either way);
   not a deciding factor.

The one thing blackbox_decode does *not* give us is the header/config
dict — it only writes frame CSVs. That turned out not to matter: the
header is a run of plain-text `H key:value` lines at the start of each
embedded log (see raw bytes below), trivial to parse directly with zero
dependency (`debrief/parse/header.py`). So the final design uses
**neither parser's header handling** — it reads the header text itself,
and uses blackbox_decode purely for frame data.

```
H Product:Blackbox flight data recorder by Nicholas Sherlock
H Data version:2
H I interval:32
H Field I name:loopIteration,time,axisP[0],...
...
H rollPID:19,12,18
...
```

A raw multi-flight file literally repeats this whole block once per
embedded log (verified: `stock_tune.BFL` has exactly 14 occurrences of
`H Product:`, matching blackbox_decode's own count of 14 logs, in the same
order) — so splitting by header offset gives a 1:1, order-preserving
correspondence with blackbox_decode's `--index` numbering for free.

## Licensing note

`blackbox-tools` is GPLv3. debrief invokes it as a separate subprocess
(never linked, never bundled in this repo) — the same "mere aggregation via
subprocess" pattern used by countless MIT/BSD tools that shell out to GPL
CLIs (ffmpeg being the canonical example). `scripts/setup.sh` clones and
builds it locally on first setup; it is never redistributed as a binary
inside this repo (`vendor/` is gitignored).

## Setpoint reconstruction

The Phase 1 dataframe deliverable includes `setpoint[0..2]`. Rather than
reimplementing Betaflight's rates-curve formula (which differs across rates
types and firmware versions), we reconstruct setpoint the same way
PID-Analyzer does, straight from logged fields:

```
axisP[axis] = P_gain * 0.032029 * (setpoint - gyro)
  =>  setpoint = gyro + axisP[axis] / (0.032029 * P_gain)
```

See `debrief/parse/setpoint.py`. This needs only the logged P-term,
gyro, and the header's P gain — no rates-formula bookkeeping, and it
reflects what the flight controller's PID loop actually targeted (RC
smoothing/interpolation included).
