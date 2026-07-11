"""Renders a TuneGeneratorResult to paste-ready files: stage1.txt,
stage2.txt, ... (each a complete, standalone `set`...`save` block), a
consolidated rollback.txt, and a changelog.md table. No single
"apply everything" file is ever produced -- that's not an oversight to
add later, it's the point: one stage, one test flight, every time.
"""
from __future__ import annotations

from pathlib import Path

from debrief.tune.generator import TuneGeneratorResult


def stage_text(stage_num: int, changes: list) -> str:
    lines = [f"# Stage {stage_num} -- {len(changes)} change(s). Save, then fly one test flight before staging the next."]
    for c in changes:
        lines.append(f"# {c.reason} (confidence: {c.confidence})")
        if c.old_value is not None:
            # comment goes on its own line, never trailing on the `set` line --
            # not every firmware CLI parser is guaranteed to accept an inline
            # comment after a command, and this file must be safely paste-ready.
            lines.append(f"# was {c.old_value}")
        lines.append(f"set {c.key} = {c.new_value}")
    lines.append("save")
    return "\n".join(lines) + "\n"


def rollback_text(rollback: list) -> str:
    if not rollback:
        return "# Nothing was changed -- no rollback needed.\n"
    lines = ["# Restores every key touched by the staged changes to its pre-change value."]
    for c in rollback:
        lines.append(f"set {c.key} = {c.new_value}")
    lines.append("save")
    return "\n".join(lines) + "\n"


def changelog_text(result: TuneGeneratorResult) -> str:
    lines = ["| Stage | Key | Old | New | Reason | Confidence |", "|---|---|---|---|---|---|"]
    for i, stage in enumerate(result.stages, start=1):
        for c in stage:
            old = c.old_value if c.old_value is not None else "-"
            lines.append(f"| {i} | `{c.key}` | {old} | {c.new_value} | {c.reason} | {c.confidence} |")
    if result.rejected:
        lines.append("")
        lines.append("### Flagged for human review (not emitted)")
        lines.append("| Key | Reason |")
        lines.append("|---|---|")
        for r in result.rejected:
            lines.append(f"| `{r.key}` | {r.reason} |")
    return "\n".join(lines) + "\n"


def write_tune_files(result: TuneGeneratorResult, output_dir: str | Path) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    for i, stage in enumerate(result.stages, start=1):
        p = out / f"stage{i}.txt"
        p.write_text(stage_text(i, stage), encoding="utf-8")
        written[f"stage{i}"] = p

    rollback_path = out / "rollback.txt"
    rollback_path.write_text(rollback_text(result.rollback), encoding="utf-8")
    written["rollback"] = rollback_path

    changelog_path = out / "changelog.md"
    changelog_path.write_text(changelog_text(result), encoding="utf-8")
    written["changelog"] = changelog_path

    return written
