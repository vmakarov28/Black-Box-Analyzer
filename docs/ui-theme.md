# Report UI theme

The HTML report (`report/templates/report.html.j2`, `compare.html.j2`) and
the inlined matplotlib plots (`report/plots.py`) are themed after
Betaflight Configurator's actual dark theme -- pulled directly from
`betaflight/betaflight-configurator`'s source
(`src/css/theme.css`, the `.dark` block), not approximated from memory.

## Palette (with source)

| Role | Value | Source variable |
|---|---|---|
| Page background | `#0a0a0a` | `--surface-50` (dark) |
| Panel background | `#141414` – `#1a1a1a` | `--surface-100`/`200` (dark) |
| Border | `#333333` / `#3d3d3d` | `--surface-400`/`500` (dark) |
| Text | `#f2f2f2` | `--text` (dark) |
| Muted text | `#9c9c9c` / `#737373` | `--surface-800`/`700` (dark) |
| Primary/brand (amber-gold) | `#ffbb00` | `--primary-500` |
| Success (save/connect/recommended) | `#96e212` | `--success-500` -- a lime green, not the generic green initially assumed |
| Error (critical) | `#e2123f` | `--error-500` |
| Warning | `#ff6600` | `--warning-500` |
| Font | `"Open Sans", "Segoe UI", Tahoma, sans-serif` | `main.less` |
| Corner radius | 3px small elements, 6px cards, 999px pills | `main.less` (`border-radius: 3px` / `0.35rem`–`0.5rem` / `999px`) |

Severity maps onto the real status colors: critical -> error red, warning
-> warning orange, advisory -> primary amber, info -> muted gray.
"Recommended" badges use the success lime-green, matching Configurator's
own save/connect/action color.

## Chart colors

Axis trio (roll/pitch/yaw) and the noise-heatmap colormap are **not**
picked from the theme.css status colors (those are reserved for
severity/status in the UI, and reusing them for series identity would
blur "this is a bad finding" with "this is the roll axis"). Instead:

- **roll/pitch/yaw**: blue `#3987e5` / aqua `#199e70` / violet `#9085e9`,
  drawn from the dataviz skill's own validated dark-mode categorical set
  (`references/palette.md`), re-validated as a 3-color subset via
  `scripts/validate_palette.js "#3987e5,#199e70,#9085e9" --mode dark`
  -- lightness band, chroma floor, CVD separation, and contrast all pass.
- **Noise heatmap**: a custom sequential ramp built from Betaflight's own
  amber primary scale (`--primary-950` through `--primary-100`, dark to
  light), so the "hotter = brighter gold" reading is both intuitive and
  on-brand, rather than a generic viridis/plasma colormap.

Matplotlib figures use a dark facecolor matching the report's panel color
so the plots blend into the page instead of showing as white rectangles
inside dark cards.

## Light/dark toggle and print stylesheet

Configurator itself ships both a dark and a light theme (plus "amber" and
"contrast" variants), so the report gets a real toggle too, not just a
dark-only page: a pill button in the top nav flips an `html[data-theme]`
attribute between `dark` (default) and `light`, with inline (no external
file) vanilla JS -- no network call, best-effort `localStorage` persistence
wrapped in try/catch since `file://` origins can restrict it in some
browsers (falls back to always-dark-on-open if blocked, never breaks).
Brand/status colors (amber, lime-green, crimson, orange) stay constant
across both themes; only surfaces and text swap, using Configurator's own
light-theme values from the same `theme.css` (the `:root` block before
`.dark` is applied).

Two element classes are deliberately **exempt** from the toggle and stay
fixed-dark in both themes: `pre.diff`/the raw-header `<pre>` (a
"terminal", like Configurator's own always-dark CLI tab) and `.plot-card`
(the inlined PNGs bake their matplotlib facecolor into the pixels at
render time, so a card that flipped to a white background around a
dark-background image would look broken, not themed).

A `@media print` block hides the nav/toggle and forces light, high-contrast
colors regardless of the on-screen theme, so a report prints or exports to
PDF cleanly for a pilot's workshop notes.

## Reproducing / updating

```bash
curl -s https://raw.githubusercontent.com/betaflight/betaflight-configurator/master/src/css/theme.css
```

is the ground truth if Configurator's palette changes -- re-pull and
diff against the table above before updating `report/templates/*.j2` and
`report/plots.py`'s color constants.
