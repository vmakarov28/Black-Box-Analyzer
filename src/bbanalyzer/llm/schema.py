"""Shared output shape for both the LLM narrative path (narrative.py) and
the --no-llm template fallback (fallback.py) -- Phase 5's report renderer
only ever consumes this, never knows which path produced it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FindingNarrative:
    finding_id: str
    title: str
    whats_wrong: str
    why_plain_english: str
    cli_diff: list[str]
    test_flight_procedure: str
    is_question: bool   # True when the underlying finding was low-confidence


@dataclass
class NarrativeReport:
    summary: str
    items: list[FindingNarrative] = field(default_factory=list)
    other_observations: list[str] = field(default_factory=list)
    generated_by: str = "template-fallback"
