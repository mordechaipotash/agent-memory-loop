"""
consolidation.py — Nightly STATE.json update from daily activity.

Extracted from consolidation-prompt.md — the medium-term memory layer.

This runs nightly (e.g., 23:30) and:
  1. Reads today's daily note (memory/YYYY-MM-DD.md)
  2. Reads current STATE.json
  3. Updates task statuses based on activity
  4. Detects newly stale items
  5. Updates the lastAudit timestamp

The actual "intelligence" (deciding what's done, what's new, what to update)
is meant to be handled by an LLM agent. This module provides the scaffolding:
data loading, staleness detection, and structured output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .state import StateManager, SweepResult


@dataclass
class ConsolidationResult:
    """Summary of what the nightly consolidation found/changed."""

    date: str
    daily_note_exists: bool
    daily_note_content: str | None
    sweep: SweepResult | None
    updated_count: int = 0
    new_count: int = 0
    completed_count: int = 0
    newly_stale_count: int = 0
    active_high_priority: list[str] = field(default_factory=list)


class Consolidator:
    """Nightly consolidation engine."""

    def __init__(
        self,
        state_path: str | Path,
        memory_dir: str | Path,
    ):
        self.state = StateManager(state_path)
        self.memory_dir = Path(memory_dir)

    def run(self, date: datetime | None = None) -> ConsolidationResult:
        """
        Run the nightly consolidation.

        This handles the mechanical parts:
        - Load today's memory file
        - Run staleness sweep
        - Mark stale items
        - Update audit timestamp

        The semantic parts (deciding what's done, adding new tasks from notes)
        should be handled by an LLM agent using the ConsolidationResult
        as input context.

        Args:
            date: Date to consolidate (default: today)

        Returns:
            ConsolidationResult with everything needed for an LLM to act on.
        """
        if date is None:
            date = datetime.now()

        date_str = date.strftime("%Y-%m-%d")
        self.state.load()

        # 1. Read today's daily note
        note_path = self.memory_dir / f"{date_str}.md"
        daily_note_exists = note_path.exists()
        daily_note_content = note_path.read_text() if daily_note_exists else None

        # 2. Run staleness sweep
        sweep = self.state.sweep()

        # 3. Auto-mark stale items
        stale_count = self.state.mark_stale()

        # 4. Update audit timestamp
        self.state.set_audit_timestamp()

        # 5. Save
        self.state.save()

        return ConsolidationResult(
            date=date_str,
            daily_note_exists=daily_note_exists,
            daily_note_content=daily_note_content,
            sweep=sweep,
            newly_stale_count=stale_count,
            active_high_priority=[
                t["title"] for t in (sweep.active_high_priority if sweep else [])
            ],
        )

    def generate_prompt(self, result: ConsolidationResult) -> str:
        """
        Generate a consolidation prompt for an LLM agent.

        This is the equivalent of consolidation-prompt.md — structured instructions
        for an agent to update STATE.json intelligently based on today's activity.
        """
        prompt_parts = [
            "# Nightly Consolidation Task",
            "",
            f"**Date:** {result.date}",
            "",
        ]

        if not result.daily_note_exists:
            prompt_parts.append(
                f"📋 No memory file for {result.date}. "
                "Only run staleness sweep."
            )
        else:
            prompt_parts.extend(
                [
                    "## Today's Memory File",
                    "",
                    "```markdown",
                    result.daily_note_content or "",
                    "```",
                    "",
                ]
            )

        # Add current state summary
        summary = self.state.summary()
        prompt_parts.extend(
            [
                "## Current STATE.json Summary",
                "",
                f"- Total tasks: {summary['total_tasks']}",
                f"- Status breakdown: {json.dumps(summary['status_counts'])}",
                f"- Newly stale: {result.newly_stale_count}",
                f"- Active high-priority: {', '.join(result.active_high_priority) or 'none'}",
                f"- Last audit: {summary['last_audit']}",
                "",
                "## Instructions",
                "",
                "For each task in STATE.json:",
                "1. If mentioned in today's note → update `lastTouched`",
                "2. If completed → set `status: \"done\"`",
                "3. If discussed but not finished → keep `status: \"active\"`, update `lastTouched`",
                "4. If explicitly abandoned → set `status: \"archived\"`",
                "",
                "For new work not in STATE.json:",
                "- Add as new task with next available ID",
                "- Set reasonable `staleAfterDays` (5 urgent, 7 normal, 14 background)",
                "",
                "For decisions made today:",
                "- Add to `decisions` array",
                "",
                "For threads:",
                "- Update `lastActivity` if active today",
                "- Mark `dormant` if no activity in 7+ days",
                "- Mark `resolved` if explicitly closed",
            ]
        )

        return "\n".join(prompt_parts)

    def format_summary(self, result: ConsolidationResult) -> str:
        """Format the consolidation result as a human-readable summary."""
        lines = [
            f"📋 Nightly STATE.json consolidation ({result.date}):",
            f"- Newly stale: {result.newly_stale_count} items",
            f"- Active high-priority: {', '.join(result.active_high_priority) or 'none'}",
        ]
        if not result.daily_note_exists:
            lines.append(f"- ⚠️ No memory file for {result.date}")
        return "\n".join(lines)
