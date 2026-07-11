"""debrief: local-only Betaflight blackbox log analyzer.

Layers (kept strictly separated so each is testable alone):
  parse  -- decode .bbl/.bfl into dataframes + header config (Phase 1)
  dsp    -- pure-function metric extraction from dataframes (Phase 2)
  rules  -- metrics -> diagnostic flags (Phase 3)
  llm    -- local LLM narrative over flags+metrics only, never raw samples (Phase 4)
  report -- self-contained HTML rendering (Phase 5)
  tune   -- CLI diff parsing + staged tuning change generator (Phase 6)
"""

__version__ = "0.1.0"
