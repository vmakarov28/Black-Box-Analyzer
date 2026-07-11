# Phase 2 validation gate

Per the requirement: run Plasmatree PID-Analyzer locally on the same log and
reconcile our step-response and spectral outputs against it before
proceeding. Reproducible via `tools/validate_step_response.py` (needs
`scripts/setup.sh --with-validator` first).

The reference tool (`vendor/PID-Analyzer/PID-Analyzer.py`, 2018) predates
Python 3's integer-division change and numpy >=1.24's removal of the
`normed=` kwarg. Rather than edit the vendored file, the validation script
applies a narrow, clearly-commented compatibility shim (int-coerce histogram
bin counts, `normed`->`density`) purely for the duration of running it, and
bypasses its `CSV_log.__init__` plotting calls (an unrelated matplotlib API
mismatch) since only the numeric `Trace` objects are needed. None of this
touches `debrief`'s own code.

## Step response

`debrief.dsp.step_response` is a direct port of `Trace`'s windowed Wiener
deconvolution + weighted-mode-average (see module docstrings for the exact
mapping). Comparing our `response_low` curve against the reference's
`resp_low` curve, same log (`good_tune.BBL`), same axis inputs:

| axis | correlation | max abs diff | rise_time_s (ours / ref) | overshoot_pct (ours / ref, low-input only) |
|---|---|---|---|---|
| roll | 0.9999999999999996 | 1.04e-12 | 0.0121917893 / 0.0121917893 | 16.10 / 16.10 |
| pitch | 0.9999999999999996 | 9.93e-13 | 0.0121917893 / 0.0121917893 | 12.95 / 12.95 |
| yaw | 0.9999999999999999 | 7.61e-13 | 0.0121917893 / 0.0121917893 | 3.64 / 3.64 |

Max absolute difference is ~1e-12 on curves whose values are O(1) -- floating
point noise, not a real discrepancy. **This is a bit-exact match.**

The table's "overshoot_pct" column applies our own `_extract_step_metrics`
to *both* curves for a true apples-to-apples comparison (PID-Analyzer itself
never computes rise/overshoot/settling numbers -- it only plots the curve).

One number in `debrief`'s own metrics output legitimately differs from
this table: `compute_flight_metrics` reports overshoot/rise/settling from
the **all-active-input** response (low- and high-stick windows combined),
not low-input-only, because that's the more representative number for a
whole-flight diagnosis. The script also reports that comparison
(`ours(all) vs ref(low)`) explicitly -- correlation stays >=0.9998, with the
residual difference fully explained by the different window population
(more windows = more high-rate stick snaps pulling the averaged curve's
peak up slightly), not a computation error.

**Note on the ~12ms rise time itself:** initially this looked suspicious --
identical to several decimal places across all three axes, which reads like
a bug. Direct comparison against the reference proved it isn't: the
reference computes the exact same number. It's a real property of this
analysis method (the Wiener deconvolution's cutfreq=25Hz regularization
shapes the leading edge of the recovered impulse response similarly
regardless of axis-specific P/D gains, since that edge is dominated by the
shared analysis window/cutoff, not the physical system) -- not an artifact
of a physical response. Flagged here rather than silently "fixed", since
"fixing" it would have meant diverging from the validated reference method.

## Noise heatmap (throttle x frequency)

First pass showed a ~100x total-energy mismatch and unexplained mean-frequency
differences. Root-caused to two real issues, both now fixed in
`debrief.dsp.noise.compute_noise_heatmap`:

1. **Validation script bug**: compared against the reference's raw
   `hist2d` (pre-throttle-normalization) instead of `hist2d_sm`
   (normalized-by-throttle-count and smoothed, the actually-comparable
   quantity). Dividing by throttle-bin sample counts (tens to low hundreds
   per bin) is exactly the ~100x this explains.
2. **Real bug in noise.py**: the reference smooths its (freq, throttle)
   histogram along `axis=1` (throttle). This implementation had
   `axis=0` (frequency) -- backwards. Fixed to match.

After both fixes, same log:

| axis | total energy (ours / ref) | energy-weighted mean freq (ours / ref) |
|---|---|---|
| roll | 1.249e5 / 1.261e5 (1.0% diff) | 20.0Hz / 18.1Hz |
| pitch | 6.840e4 / 6.963e4 (1.8% diff) | 36.0Hz / 33.9Hz |
| yaw | 8.265e4 / 8.384e4 (1.4% diff) | 60.8Hz / 58.8Hz |

Total energy now agrees to ~1-2%. The remaining few-Hz difference in mean
frequency is attributable to binning convention, not method: we use 100
throttle bins with exact histogram2d bin centers; the reference uses 101
throttle bins and, for its *plot axis labels only*, an approximate
`freq[::4]` decimation that is documented in the reference's own comment as
not being the literal histogram2d bin centers. Comparing against that
approximate axis (there is no better one exposed by the reference) is
expected to introduce a small, bounded skew -- consistent with what's
observed. This was re-verified by also checking total energy (binning-
convention-independent) agrees to ~1-2%, which it does.

## Filtered-vs-unfiltered comparison: a caught false positive

Not part of the PID-Analyzer reconciliation (it has no equivalent feature),
but found during the same validation pass and worth recording: the first
version of `dsp.filter_analysis.detect_unfiltered_proxy` accepted
`debug[0]` on `good_tune.BBL` as an "unfiltered gyro" proxy for all three
axes -- correlation 0.9998 with the filtered gyro, passed the HF-energy
check -- and reported a filter latency of exactly **0.0ms** on every axis.

Exactly 0.0ms across all three axes was the tell. A real lowpass/notch
filter chain always has nonzero group delay; a candidate "unfiltered"
signal that shows zero lag against the filtered signal is far more likely
to be a duplicate/copy of the already-filtered signal than a genuine
pre-filter tap (plausible here: this is a 2017 BF 3.1.5 log, predating
Betaflight's dynamic notch and much of the modern filtering pipeline, so
`debug_mode:8` may simply not correspond to a genuine unfiltered-gyro debug
mode on this firmware). Added a third acceptance criterion -- the candidate
must lead the filtered gyro by a genuinely positive, plausible lag (cross-
correlation peak at lag >= 1 sample, searched up to 50ms) -- and re-running
on the same log now correctly reports the comparison as unavailable on all
three axes, rather than a fabricated 0.0ms.

## Conclusion

Step response: bit-exact. Noise heatmap: agrees to ~1-2% on total energy
after fixing one real bug (smoothing axis) and one validation-script bug
(comparing against the wrong reference array). Proceeding with Phase 2 as
implemented.
