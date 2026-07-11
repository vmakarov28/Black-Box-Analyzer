#!/usr/bin/env bash
# One-time, offline-afterwards setup. Run from WSL2 (or any Linux/macOS shell).
#
# What this fetches from the network (once):
#   - betaflight/blackbox-tools source, built locally into a native binary
#     that debrief shells out to for frame decoding.
#   - (dev only, --with-validator) PID-Analyzer source, used purely as a
#     Phase 2 validation-gate reference -- never imported at runtime.
# Nothing here is a runtime dependency of debrief itself; after this
# script finishes, `debrief analyze ...` makes zero network requests.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VENV_DIR="${DEBRIEF_VENV:-$HOME/.venvs/fpvbb}"
WITH_VALIDATOR=0
WITH_LLM=0
WITH_WEB=0
for arg in "$@"; do
  case "$arg" in
    --with-validator) WITH_VALIDATOR=1 ;;
    --with-llm) WITH_LLM=1 ;;
    --with-web) WITH_WEB=1 ;;
  esac
done

echo "== Python venv ($VENV_DIR) =="
python3 -m venv "$VENV_DIR" --upgrade-deps
"$VENV_DIR/bin/pip" install -e ".[dev]"
if [ "$WITH_LLM" = "1" ]; then
  "$VENV_DIR/bin/pip" install -e ".[llm]"
fi
if [ "$WITH_WEB" = "1" ]; then
  "$VENV_DIR/bin/pip" install -e ".[web]"
fi

echo "== blackbox-tools (frame decoder) =="
mkdir -p vendor
if [ ! -d vendor/blackbox-tools ]; then
  git clone --depth 1 https://github.com/betaflight/blackbox-tools vendor/blackbox-tools
fi
make -C vendor/blackbox-tools -j"$(nproc)"
"$VENV_DIR/bin/python" - <<'PY'
import subprocess, pathlib
b = pathlib.Path("vendor/blackbox-tools/obj/blackbox_decode")
assert b.is_file(), "build did not produce obj/blackbox_decode"
subprocess.run([str(b), "--help"], check=True, stdout=subprocess.DEVNULL)
print("blackbox_decode OK:", b)
PY

if [ "$WITH_VALIDATOR" = "1" ]; then
  echo "== PID-Analyzer (Phase 2 validation-gate reference, not a runtime dep) =="
  if [ ! -d vendor/PID-Analyzer ]; then
    git clone --depth 1 https://github.com/Plasmatree/PID-Analyzer vendor/PID-Analyzer
  fi
  "$VENV_DIR/bin/pip" install matplotlib
fi

if [ "$WITH_LLM" = "1" ]; then
  echo "== Ollama =="
  if ! command -v ollama >/dev/null 2>&1; then
    echo "Ollama not found. Install it (one-time, needs network) with:"
    echo "    curl -fsSL https://ollama.com/install.sh | sh"
    echo "then re-run with --with-llm to pull a model."
  else
    echo "Ollama already installed: $(ollama --version)"
  fi
fi

echo
echo "Setup complete. Activate with: source $VENV_DIR/bin/activate"
echo "Try:  debrief analyze tests/data/good_tune.BBL -o /tmp/report.html"
if [ "$WITH_WEB" = "1" ]; then
  echo "Or:   debrief serve   (opens a local web UI at http://127.0.0.1:8765 -- upload/download buttons, no CLI needed)"
fi
