# Local web UI (`debrief serve`)

A Flask app (`src/debrief/web/`) so the tool is usable without typing CLI
flags: drag a log onto the page, get the report back in the browser with
download buttons. It is a thin routing layer over the exact same code the
CLI uses -- see `pipeline.py` (shared `select_flight()`/`run_analysis()`)
and `report/html_report.py`'s `render_report_html()` (the pure str-in/
str-out renderer both front ends call). Nothing in `web/app.py` makes a
diagnostic decision; it only handles HTTP, file uploads, and errors.

## Staying local

- Binds to `127.0.0.1` by default (`--host` to override, with a printed
  warning if you do -- e.g. to test from a phone on the same LAN).
- The only outbound network call anywhere in the app is the same
  localhost-only Ollama request `llm/narrative.py` already makes for the
  CLI path -- `OllamaClient` never talks to anything but the configured
  `ollama_host`, which defaults to `127.0.0.1:11434`.
- Uploaded files are written into a `tempfile.TemporaryDirectory()` that's
  deleted before the request finishes (needed because `load()` and the
  `blackbox_decode` subprocess both require a real path on disk) -- once
  the HTTP response is sent, no trace of the uploaded log remains on the
  machine running the server.

## Downloads without a server round-trip

The report page itself is the entire HTTP response (no separate "view"
step) -- the upload form POSTs directly to `/analyze`/`/compare` and the
browser navigates straight to the rendered report. "Download report" is
pure client-side JS (`document.documentElement.outerHTML` -> `Blob` ->
`<a download>`), and the tune generator's `stageN.txt`/`rollback.txt`/
`changelog.md` buttons are `data:` URIs built server-side from the exact
same `tune/output.py` functions (`stage_text()`/`rollback_text()`/
`changelog_text()`) the CLI's `--tune-output-dir` uses to write files to
disk -- byte-identical content, just embedded instead of written. No
second request, no server-side session state to clean up.

## Model picker

`OllamaClient.list_models()` queries the actual running server for what's
pulled and populates the dropdown from that -- never a hardcoded list of
"the 3 we benchmarked". If Ollama isn't reachable, the UI disables the
narrative controls and defaults to the (also fully-tested) template
fallback rather than presenting a broken option.

## Testing

`tests/test_web.py` drives real multipart file uploads through Flask's
test client for both routes, including the corrupt-file and
missing-file error paths (checked for a themed error page, not a raw
traceback) and the tune-generator download links. Also verified against
the actual `debrief serve` process with real `curl` uploads (not just the
test client) before shipping.
