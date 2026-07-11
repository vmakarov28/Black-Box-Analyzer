"""The Finding data model. This is the sole interface between the rules
layer (which carries all diagnostic logic and judgment) and everything
downstream (LLM narrative, report, tune generator) -- neither of those
layers is allowed to re-derive a diagnosis from raw metrics; they only
render/act on Findings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    INFO = "info"           # neutral observation, no action implied
    ADVISORY = "advisory"   # worth considering, low urgency
    WARNING = "warning"     # measurable problem, should be addressed
    CRITICAL = "critical"   # actively unsafe or badly broken tune

    def rank(self) -> int:
        return {"info": 0, "advisory": 1, "warning": 2, "critical": 3}[self.value]


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2}[self.value]


@dataclass
class ParamHint:
    """A candidate CLI key + direction for Phase 6 to independently
    validate (whitelist, version-guard, bounds-clamp) and turn into an
    actual `set` command -- this layer never emits a CLI diff itself.
    """

    key_guess: str
    direction: str  # "increase" | "decrease" | "enable" | "disable" | "investigate"
    magnitude_pct: float | None = None  # suggested relative move, if applicable
    axis: str | None = None


@dataclass
class Finding:
    id: str                      # stable rule id, e.g. "propwash_bounce_back"
    title: str
    category: str                # "filtering" | "pid" | "rates" | "hardware" | "config" | "rpm_filter" | ...
    severity: Severity
    confidence: Confidence
    axis: str | None
    trigger_summary: str         # the actual values that fired this rule, for transparency
    rationale: str                # why this matters, in plain terms; may cite the heuristic's source
    suggestion: str               # human-readable recommendation (question, if confidence is low)
    param_hints: list[ParamHint] = field(default_factory=list)
    source: str = "community-heuristic"   # "betaflight-wiki" | "config-check" | "community-heuristic" | "measurement"
    recommended: bool = False    # set by the engine's top-N selection, not by the rule itself
    tunable_note: str | None = None  # present when a threshold in this rule is a TUNABLE guess, not a spec value
