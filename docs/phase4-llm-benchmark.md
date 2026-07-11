# Phase 4: local LLM benchmark

Ran the same findings JSON (`tests/data/good_tune.BBL`, 7 findings / 2
recommended) through three candidates on the dev machine (WSL2, RTX 5080
16GB) via `tools/benchmark_llm.py`. All three fit comfortably in VRAM
simultaneously.

| Model | Size (Q4_K_M) | Wall time (warm) | Wall time (cold load) | Tokens |
|---|---|---|---|---|
| llama3.1:8b-instruct | 4.9 GB | 2.6s | 46.0s | ~290 |
| gemma2:9b-instruct | 5.8 GB | 9.1s | 26.7s | ~320 |
| qwen2.5:14b-instruct | 9.0 GB | 16.0s | 28.3s | ~310 |

"Cold load" is the first call after `ollama serve` starts (model weights
loaded from disk into VRAM); every call after that on the same model is
"warm". In practice a pilot runs this tool repeatedly across a session, so
warm-time is the number that matters most for UX.

## A real fabrication bug, caught here

The first benchmark pass (before the fix below) had llama3.1:8b write, in
`test_flight_procedure`:

> "Try raising the D term for roll by 2-3 points (e.g., from P=19.0
> I=12.0 D=18.0 to P=19.0 I=12.0 D=21.0)"

The `18.0 -> 21.0` is a specific, unvalidated numeric target the model
computed itself from the current PID values it had access to in the
aircraft-summary context -- despite the prompt explicitly saying not to
invent CLI values. This is a real instance of exactly what the whole
project's "never fabricate a metric or heuristic" rule exists to prevent:
a plausible-looking number, never bounds-checked, dressed up as advice,
one copy-paste away from a real flight controller.

Note this was never at risk of reaching the *actual* CLI diff -- the
`cli_diff` field is never sourced from model text at all (see
`test_parse_response_never_fabricates_cli_diff_from_model_text`). But
free-text fields (`whats_wrong`, `why_plain_english`,
`test_flight_procedure`) were still being trusted, and a number stated
confidently in prose reads as authoritative to a pilot even outside a
formal diff block.

Fixed two ways (`bbanalyzer/llm/narrative.py`, `prompts/narrative_prompt.j2`):

1. **Prompt**: added an explicit rule with a worked WRONG/RIGHT example,
   specifically calling out that seeing a current value does not license
   proposing a new one.
2. **Code (defense in depth)**: `_scrub_fabricated_values` regex-checks
   every free-text field for "from X to Y" / "set KEY = N" / "KEY=X->Y"
   patterns and replaces the field with the deterministic template
   phrasing if no *validated* CLI diff was supplied for that finding and
   the pattern matches. A prompt instruction alone isn't reliable enough
   for a value that could get typed into a real aircraft -- confirmed by
   this benchmark run being the counterexample.

Re-running llama3.1:8b after the fix, the same finding now reads "raise
the D gain for roll by a bit" -- correct behavior, no invented number.
Verified with `test_parse_response_scrubs_fabricated_numeric_target_values`
(regression test pinned to this exact failure) and
`test_parse_response_allows_numbers_when_validated_diff_supplied` (the
scrub must NOT fire when a real bounds-checked diff is present).

## Decision: llama3.1:8b-instruct-q4_K_M as the default

All three, post-fix, produced accurate, well-grounded, appropriately
qualitative output (no fabricated values), correctly cited the actual
numbers they *were* given (e.g. qwen2.5 correctly quoted "329 degrees per
second" and the measured correlation from the findings JSON), and wrote
genuinely hobbyist-readable one-sentence explanations.

With quality roughly comparable across all three post-fix, warm-call speed
is the deciding factor for a tool meant to be re-run after every flight:
llama3.1:8b is ~3-6x faster than the other two on this hardware. Set as
the CLI default (`--model llama3.1:8b-instruct-q4_K_M`); `qwen2.5:14b`
gives marginally more detail for anyone willing to trade speed for it, and
`gemma2:9b` is a reasonable middle ground -- both are one `--model` flag
away.

## Reproducing

```
ollama pull llama3.1:8b-instruct-q4_K_M
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull gemma2:9b-instruct-q4_K_M
python tools/benchmark_llm.py tests/data/good_tune.BBL
```
