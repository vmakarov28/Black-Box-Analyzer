"""Shared CSS/JS for every HTML surface Debrief renders (the analyze
report, the compare report, and the local web app's pages) -- one source
of truth so the product looks like one thing, not three separately themed
pages. Palette is sourced from the real betaflight-configurator dark/light
themes (see docs/ui-theme.md), not approximated.

Kept as plain Python string constants (not a Jinja partial) so both the
Jinja-template-based report renderers and Flask's render_template_string
calls can embed the same bytes without needing a shared template loader
search path across two different packages.
"""
from __future__ import annotations

THEME_CSS = """
:root {
  --bg: #0a0a0a; --bg-alt: #141414; --panel: #1a1a1a; --panel-2: #212121;
  --border: #333333; --border-2: #3d3d3d;
  --text: #f2f2f2; --muted: #9c9c9c; --muted-2: #737373;

  --primary: #ffbb00; --primary-light: #ffc526; --primary-lighter: #ffea46;
  --primary-dark: #e29000; --primary-darker: #bb6502;
  --primary-tint: rgba(255, 187, 0, 0.1); --primary-glow: rgba(255, 187, 0, 0.35);

  --success: #96e212; --success-light: #adf042; --success-dark: #79b210;
  --error: #e2123f; --error-light: #ee2b55; --error-dark: #c10f36;
  --warning: #ff6600; --warning-light: #ff8533; --warning-dark: #e65c00;

  --crit: var(--error); --warn: var(--warning); --adv: var(--primary); --info: var(--muted);
  --radius: 6px; --radius-sm: 3px; --radius-lg: 10px;
  --shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
html[data-theme="light"] {
  --bg: #ffffff; --bg-alt: #fafafa; --panel: #f7f7f7; --panel-2: #f0f0f0;
  --border: #d6d6d6; --border-2: #bfbfbf;
  --text: #0a0a0a; --muted: #595959; --muted-2: #757575;
  --primary-tint: rgba(255, 187, 0, 0.12); --shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  background:
    radial-gradient(1200px 500px at 15% -10%, var(--primary-tint), transparent 60%),
    var(--bg);
  color: var(--text);
  font-family: "Open Sans", "Segoe UI", Tahoma, sans-serif;
  margin: 0; padding: 0; line-height: 1.55; font-size: 14px;
}
a { color: var(--primary-light); }
code { font-family: "SF Mono", "Cascadia Mono", Consolas, monospace; }

.topbar {
  background: color-mix(in srgb, var(--bg-alt) 88%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 10;
}
.topbar-inner {
  max-width: 1180px; margin: 0 auto; padding: 0 24px;
  display: flex; align-items: center; gap: 4px; overflow-x: auto;
}
.topbar .brand {
  display: flex; align-items: center; gap: 9px; padding: 12px 16px 12px 0;
  margin-right: 8px; border-right: 1px solid var(--border); white-space: nowrap;
  text-decoration: none; color: var(--text);
}
.topbar .brand .dot {
  width: 9px; height: 9px; border-radius: 50%; background: var(--success);
  box-shadow: 0 0 8px var(--success);
}
.topbar .brand b { font-size: 0.9rem; letter-spacing: .01em; font-weight: 700; }
.topbar nav { display: flex; align-items: center; }
.topbar nav a {
  color: var(--muted); text-decoration: none; font-size: 0.8rem; font-weight: 600;
  padding: 14px 12px; border-bottom: 2px solid transparent; white-space: nowrap;
  transition: color .15s ease;
}
.topbar nav a:hover { color: var(--text); }

.theme-toggle {
  margin-left: auto; background: none; border: 1px solid var(--border-2); color: var(--muted);
  border-radius: 999px; padding: 5px 12px; font-size: 0.75rem; font-weight: 600; cursor: pointer;
  font-family: inherit; white-space: nowrap; transition: all .15s ease;
}
.theme-toggle:hover { color: var(--text); border-color: var(--muted); }

.btn {
  display: inline-flex; align-items: center; gap: 8px; border: none; border-radius: var(--radius);
  padding: 10px 18px; font-size: 0.85rem; font-weight: 700; font-family: inherit; cursor: pointer;
  text-decoration: none; transition: transform .1s ease, box-shadow .15s ease;
}
.btn:active { transform: translateY(1px); }
.btn-primary { background: var(--primary); color: #1a1204; box-shadow: 0 0 0 rgba(255,187,0,0); }
.btn-primary:hover { box-shadow: 0 4px 20px var(--primary-glow); }
.btn-ghost { background: var(--panel); color: var(--text); border: 1px solid var(--border-2); }
.btn-ghost:hover { border-color: var(--primary); color: var(--primary-light); }
.btn-success { background: var(--success); color: #0a1400; }
.btn:disabled { opacity: 0.45; cursor: not-allowed; box-shadow: none; }

.badge {
  font-size: 0.65rem; text-transform: uppercase; letter-spacing: .04em; font-weight: 700;
  padding: 3px 10px; border-radius: 999px; border: 1px solid var(--border-2); color: var(--muted);
}
.badge.recommended { background: var(--success); color: #0a0a0a; border-color: var(--success); }
.badge.question { background: transparent; border-color: var(--warning); color: var(--warning-light); }
.badge.sev-critical { border-color: var(--error); color: var(--error-light); }
.badge.sev-warning { border-color: var(--warning); color: var(--warning-light); }
.badge.sev-advisory { border-color: var(--primary); color: var(--primary-light); }

table.metrics { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
table.metrics td, table.metrics th { padding: 8px 12px; border-bottom: 1px solid var(--border); text-align: left; }
table.metrics th { color: var(--muted-2); font-weight: 600; font-size: 0.7rem; text-transform: uppercase; letter-spacing: .05em; }
table.metrics tbody tr:hover { background: var(--panel-2); }
table.metrics code { color: var(--primary-light); font-size: 0.82em; }

footer {
  color: var(--muted-2); font-size: 0.78rem; margin-top: 40px; border-top: 1px solid var(--border);
  padding-top: 16px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px;
}
footer .dot { color: var(--success); }

.warn-banner {
  background: rgba(255, 102, 0, 0.1); border: 1px solid var(--warning); color: var(--warning-light);
  border-radius: var(--radius); padding: 12px 16px; margin-bottom: 16px; font-size: 0.88rem;
}
.err-banner {
  background: rgba(226, 18, 63, 0.1); border: 1px solid var(--error); color: var(--error-light);
  border-radius: var(--radius); padding: 16px 18px; margin-bottom: 16px; font-size: 0.92rem;
}

@media print {
  .topbar, .theme-toggle, .btn { display: none !important; }
  html[data-theme] {
    --bg: #fff; --bg-alt: #fff; --panel: #fff; --panel-2: #f5f5f5; --text: #000;
    --muted: #444; --muted-2: #555; --border: #ccc; --border-2: #bbb;
  }
  body { background: #fff; padding: 0; }
  a { color: inherit; text-decoration: underline; }
}
"""

THEME_SCRIPT_HEAD = """
(function () {
  var t = "dark";
  try { t = localStorage.getItem("debrief-theme") || "dark"; } catch (e) {}
  document.documentElement.setAttribute("data-theme", t);
})();
function bbToggleTheme() {
  var html = document.documentElement;
  var next = html.getAttribute("data-theme") === "light" ? "dark" : "light";
  html.setAttribute("data-theme", next);
  try { localStorage.setItem("debrief-theme", next); } catch (e) {}
  var btn = document.getElementById("themeToggle");
  if (btn) btn.textContent = next === "light" ? "Dark mode" : "Light mode";
}
"""

THEME_SCRIPT_SYNC_LABEL = """
(function () {
  var btn = document.getElementById("themeToggle");
  if (btn && document.documentElement.getAttribute("data-theme") === "light") { btn.textContent = "Dark mode"; }
})();
"""
