# debrief

A local-only Betaflight blackbox log analyzer: DSP metrics in, PID-tuning
diagnosis out, with a local LLM writing the plain-English report. Nothing
phones home, ever -- after a one-time offline setup (building a decoder,
pulling a local model), it runs with zero network access.

```
debrief analyze mylog.bbl -o report.html
```

opens as a single self-contained HTML file: every plot and style inlined,
zero network requests when you open it.

## Why

Betaflight blackbox logs already contain everything needed to diagnose a
tune -- rise time, overshoot, noise spectra, propwash behavior. Existing
tools (PID-Analyzer, blackbox_explorer) plot it; this tool also *explains*
it and, if you supply your current CLI config, proposes a validated,
staged set of changes to test one at a time.

## Architecture

Four strictly separated layers, each independently testable:

```
parse/  .bbl/.bfl -> per-flight dataframe + header config          (Phase 1)
dsp/    pure functions: dataframe -> ~50 named metrics, no plots    (Phase 2)
rules/  metrics -> ordered Findings (the diagnostic logic lives here) (Phase 3)
llm/    Findings -> plain-English narrative, local model or template (Phase 4)
report/ Findings + narrative -> one self-contained HTML file         (Phase 5)
tune/   Findings + pilot's config -> validated, staged CLI changes   (Phase 6)
```

The rules layer is the only place a "this is wrong" judgment is made. The
LLM never sees raw samples -- only the metrics dict, the triggered
Findings, and the log's header -- and it never decides *what* to change,
only how to explain a change the rules/tune layers already computed.

## Setup (one-time, needs network; nothing after this does)

```bash
git clone <this repo>
cd fpv-blackbox-analyzer
./scripts/setup.sh --with-llm          # builds blackbox_decode, sets up the venv
ollama pull llama3.1:8b-instruct-q4_K_M   # or see docs/phase4-llm-benchmark.md for alternatives
```

Requires a C compiler (to build `betaflight/blackbox-tools` locally) and,
for the LLM narrative, [Ollama](https://ollama.com) with a local model
pulled. Everything works without the LLM too -- pass `--no-llm` and the
exact same report structure renders from templates, zero model required.

## Usage

```bash
# Basic report, local LLM narrative
debrief analyze mylog.bbl -o report.html

# No model installed / don't want to wait -- identical report structure
debrief analyze mylog.bbl -o report.html --no-llm

# With your current tune (paste-ready `diff` output from Betaflight
# Configurator) -- unlocks the tune generator's staged CLI files
debrief analyze mylog.bbl -o report.html \
    --config-diff my_current_diff.txt --tune-output-dir ./tune_out

# Include a rates-usage report (measured vs configured, preference only)
debrief analyze mylog.bbl -o report.html --rates

# Verify a staged change actually helped
debrief analyze --compare before.bbl after.bbl -o compare.html
```

`--tune-output-dir` writes `stage1.txt`, `stage2.txt`, ... (each a
complete, standalone paste-ready `set`...`save` block, at most 3
changes each), `rollback.txt` (restores every touched key), and
`changelog.md`. There is never a single "apply everything" file --
one stage, one test flight, always.

## Safety design (Phase 6)

This tool's output can end up flashed to a real, physical aircraft.
Structural guarantees, not just conventions:

- **Whitelist**: only tuning-domain keys (PID/FF/filters/RPM
  filter/dynamic idle/TPA/anti-gravity) can ever be emitted. Motor
  protocol, failsafe, arming, mode assignments, ports, OSD, and VTX keys
  are never enumerated in the whitelist to begin with -- there's no
  filter to bypass, no code path that touches them.
- **Version guard**: every emitted key must exist, byte-for-byte, in the
  pilot's actual source config (their CLI diff, or the log's own header
  as a fallback) before it can be emitted. This structurally prevents
  ever suggesting a setting name from the wrong firmware version.
- **Simplified-tuning guard**: if `simplified_pids_mode` is active,
  PID/filter/feedforward changes are translated to the slider-equivalent
  key (global, approximate, clearly noted) instead of a raw key that
  would be silently overridden on save -- unless explicitly told to
  disable simplified tuning first, in which case that's stage 1 with a
  stated reason. Raw and slider keys are never mixed in the same output.
- **Bounds clamps**: no gain move over 30% in one stage; filter cutoffs
  checked against the logged loop rate's Nyquist limit. An out-of-bounds
  request is rejected outright and flagged for a human -- never silently
  reduced to "close enough".
- **Rates honesty**: rates changes are gated behind an explicit `--rates`
  flag, always labeled preference-based, and the "configured max rate" is
  only ever shown when computable with confidence for that rates format
  -- never a guessed number.

See `docs/phase2-validation-gate.md` and `docs/phase4-llm-benchmark.md`
for two real bugs this project's own validation/benchmarking process
caught and fixed (a filtering false-positive, and an LLM inventing an
unvalidated numeric PID target) -- kept as a record of how the
conservative-bias rule earns its keep in practice, not just a claim.

## Testing

```bash
pytest tests/ -v
```

~85 tests across all six layers, run against real sample logs (from
Plasmatree/PID-Analyzer's example set) plus synthetic edge cases (short
segments, idle flight, corrupt/truncated files, multi-flight logs).

`tools/validate_step_response.py` and `tools/eval_parsers.py` are dev-only
validation scripts that compare this tool's output against the real
Plasmatree PID-Analyzer and orangebox, respectively -- see
`docs/phase1-parser-evaluation.md` and `docs/phase2-validation-gate.md`
for what they found. They need `./scripts/setup.sh --with-validator`
first and are never imported by `debrief` itself.

## Design notes / phase docs

- `docs/phase1-parser-evaluation.md` -- why `blackbox_decode` over
  `orangebox` for frame decoding (with numbers from a real corrupt log).
- `docs/phase2-validation-gate.md` -- step response validated to ~1e-12
  against the reference implementation; noise heatmap to ~1-2%; one real
  bug found and fixed in each of the noise smoothing axis and the
  filtered-vs-unfiltered comparison (a false positive with 0.0ms latency).
- `docs/phase4-llm-benchmark.md` -- 3-model local LLM comparison and the
  fabricated-PID-value bug it caught.

## What this tool will never do

- Make a network request after initial setup.
- Emit a CLI key outside the tuning whitelist.
- Emit a key that doesn't verifiably exist in your actual firmware/config.
- Present a heuristic threshold as measured fact -- anything not sourced
  from a documented Betaflight default is marked `TUNABLE` in the code
  and in its rationale text.
- Bundle a rendered report, log, or config that phones home when opened.

## License

MIT (see `LICENSE`). `betaflight/blackbox-tools` (GPLv3) is invoked as a
separate local subprocess, never bundled or linked -- see
`docs/phase1-parser-evaluation.md` for the licensing note.
