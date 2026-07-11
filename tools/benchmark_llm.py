"""Phase 4 benchmark: run the same findings JSON through 2-3 candidate
local models and compare output quality (spot-checked manually from the
printed output) and speed. Dev-only tool, not part of the package.

Usage (inside the WSL venv, after `ollama pull <model>` for each candidate):
    python tools/benchmark_llm.py tests/data/good_tune.BBL
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from debrief.dsp import compute_flight_metrics  # noqa: E402
from debrief.llm.narrative import build_narrative  # noqa: E402
from debrief.llm.ollama_client import OllamaClient  # noqa: E402
from debrief.parse import load  # noqa: E402
from debrief.rules import diagnose  # noqa: E402

CANDIDATES = [
    "llama3.1:8b-instruct-q4_K_M",
    "qwen2.5:14b-instruct-q4_K_M",
    "gemma2:9b-instruct-q4_K_M",
]


def main():
    bbl_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "data" / "good_tune.BBL"
    lf = load(bbl_path)
    flight = lf.flights[0]
    m = compute_flight_metrics(flight)
    findings = diagnose(m, flight.config)
    print(f"{len(findings)} findings, {sum(1 for f in findings if f.recommended)} recommended\n")

    client = OllamaClient()
    if not client.is_available():
        print("Ollama server not reachable at 127.0.0.1:11434 -- start it first (`ollama serve`).")
        sys.exit(1)

    for model in CANDIDATES:
        if not client.has_model(model):
            print(f"=== {model}: not pulled locally, skipping (ollama pull {model}) ===\n")
            continue
        print(f"=== {model} ===")
        t0 = time.perf_counter()
        report = build_narrative(findings, m, flight.config, model=model)
        dt = time.perf_counter() - t0
        print(f"wall time: {dt:.1f}s | generated_by: {report.generated_by}")
        print(f"summary: {report.summary}\n")
        for item in report.items:
            print(f"  [{item.finding_id}] {'(question)' if item.is_question else ''}")
            print(f"    whats_wrong: {item.whats_wrong}")
            print(f"    why: {item.why_plain_english}")
            print(f"    test procedure: {item.test_flight_procedure}")
        print()


if __name__ == "__main__":
    main()
