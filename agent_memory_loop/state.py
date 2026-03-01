"""
state.py — STATE.json management: read, update, staleness detection.

Extracted from STATE.json schema + state-sweep.sh logic.

STATE.json is the source of truth for what's open, done, stale, and decided.
This module provides CRUD operations and automated staleness detection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

StatusType = Literal["active", "waiting", "blocked", "done", "stale", "archived"]
PriorityType = Literal["high", "medium", "low"]


# ── Default schema ────────────────────────────────────────────────────

DEFAULT_STATE = {
    "version": 1,
    "lastAudit": None,
    "tasks": [],
    "decisions": [],
    "threads": [],
}


@dataclass
class SweepResult:
    """Result of a staleness sweep."""

    newly_stale: list[dict]
    active_high_priority: list[dict]
    waiting_items: list[dict]
    dormant_threads: list[dict]
    total_tasks: int
    status_counts: dict[str, int]


class StateManager:
    """Manage a STATE.json file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data: dict | None = None

    @property
    def data(self) -> dict:
        if self._data is None:
            self.load()
        return self._data  # type: ignore

    def load(self) -> dict:
        """Load STATE.json from disk."""
        if self.path.exists():
            self._data = json.loads(self.path.read_text())
        else:
            self._data = json.loads(json.dumps(DEFAULT_STATE))
        return self._data

    def save(self) -> None:
        """Write STATE.json to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n")

    # ── Task CRUD ─────────────────────────────────────────────────

    def get_task(self, task_id: str) -> dict | None:
        """Get a task by ID."""
        for t in self.data.get("tasks", []):
            if t["id"] == task_id:
                return t
        return None

    def add_task(
        self,
        title: str,
        priority: PriorityType = "medium",
        context: str = "",
        source: str = "",
        stale_after_days: int = 7,
    ) -> dict:
        """Add a new task with auto-incremented ID."""
        tasks = self.data.setdefault("tasks", [])
        # Find next ID
        max_id = 0
        for t in tasks:
            try:
                num = int(t["id"].lstrip("t"))
                max_id = max(max_id, num)
            except (ValueError, KeyError):
                pass

        now = datetime.now(timezone.utc).isoformat()
        task = {
            "id": f"t{max_id + 1:03d}",
            "title": title,
            "status": "active",
            "priority": priority,
            "created": now,
            "lastTouched": now,
            "staleAfterDays": stale_after_days,
            "context": context,
            "source": source,
            "signals": [],
        }
        tasks.append(task)
        return task

    def update_task(
        self,
        task_id: str,
        status: StatusType | None = None,
        context: str | None = None,
        priority: PriorityType | None = None,
        touch: bool = True,
    ) -> dict | None:
        """Update an existing task. Always updates lastTouched unless touch=False."""
        task = self.get_task(task_id)
        if task is None:
            return None
        if status is not None:
            task["status"] = status
        if context is not None:
            task["context"] = context
        if priority is not None:
            task["priority"] = priority
        if touch:
            task["lastTouched"] = datetime.now(timezone.utc).isoformat()
        return task

    # ── Decision CRUD ─────────────────────────────────────────────

    def add_decision(
        self,
        description: str,
        context: str = "",
        supersedes: str | None = None,
    ) -> dict:
        """Add a new decision with auto-incremented ID."""
        decisions = self.data.setdefault("decisions", [])
        max_id = 0
        for d in decisions:
            try:
                num = int(d["id"].lstrip("d"))
                max_id = max(max_id, num)
            except (ValueError, KeyError):
                pass

        decision = {
            "id": f"d{max_id + 1:03d}",
            "description": description,
            "date": datetime.now(timezone.utc).isoformat(),
            "context": context,
            "supersedes": supersedes,
        }
        decisions.append(decision)
        return decision

    # ── Thread CRUD ───────────────────────────────────────────────

    def get_thread(self, thread_id: str) -> dict | None:
        """Get a thread by ID."""
        for th in self.data.get("threads", []):
            if th["id"] == thread_id:
                return th
        return None

    def add_thread(
        self,
        topic: str,
        notes: str = "",
        status: str = "active",
    ) -> dict:
        """Add a new thread with auto-incremented ID."""
        threads = self.data.setdefault("threads", [])
        max_id = 0
        for th in threads:
            try:
                num = int(th["id"].lstrip("th"))
                max_id = max(max_id, num)
            except (ValueError, KeyError):
                pass

        thread = {
            "id": f"th{max_id + 1:03d}",
            "topic": topic,
            "status": status,
            "lastActivity": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }
        threads.append(thread)
        return thread

    def update_thread(
        self,
        thread_id: str,
        status: str | None = None,
        notes: str | None = None,
        touch: bool = True,
    ) -> dict | None:
        """Update a thread."""
        th = self.get_thread(thread_id)
        if th is None:
            return None
        if status is not None:
            th["status"] = status
        if notes is not None:
            th["notes"] = notes
        if touch:
            th["lastActivity"] = datetime.now(timezone.utc).isoformat()
        return th

    # ── Staleness detection ───────────────────────────────────────

    def sweep(self, now: datetime | None = None) -> SweepResult:
        """Find stale items, similar to state-sweep.sh logic."""
        if now is None:
            now = datetime.now(timezone.utc)

        newly_stale = []
        active_high = []
        waiting = []
        dormant_threads = []
        status_counts: dict[str, int] = {}

        for task in self.data.get("tasks", []):
            status = task.get("status", "active")
            status_counts[status] = status_counts.get(status, 0) + 1

            if status == "active":
                last_touched = self._parse_date(task.get("lastTouched", ""))
                stale_days = task.get("staleAfterDays", 7)
                if last_touched and (now - last_touched).days > stale_days:
                    newly_stale.append(task)

                if task.get("priority") == "high":
                    active_high.append(task)

            elif status == "waiting":
                waiting.append(task)

        for th in self.data.get("threads", []):
            if th.get("status") == "dormant":
                dormant_threads.append(th)

        return SweepResult(
            newly_stale=newly_stale,
            active_high_priority=active_high,
            waiting_items=waiting,
            dormant_threads=dormant_threads,
            total_tasks=len(self.data.get("tasks", [])),
            status_counts=status_counts,
        )

    def mark_stale(self, task_ids: list[str] | None = None) -> int:
        """Mark stale items. If no IDs given, auto-detect from sweep."""
        if task_ids is None:
            result = self.sweep()
            task_ids = [t["id"] for t in result.newly_stale]

        count = 0
        for tid in task_ids:
            updated = self.update_task(tid, status="stale")
            if updated:
                count += 1
        return count

    def set_audit_timestamp(self) -> None:
        """Update the lastAudit timestamp."""
        self.data["lastAudit"] = datetime.now(timezone.utc).isoformat()

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parse an ISO8601 date string, handling timezone offsets."""
        if not date_str:
            return None
        try:
            # Python 3.11+ fromisoformat handles offsets
            return datetime.fromisoformat(date_str)
        except ValueError:
            pass
        # Fallback: strip offset and parse as UTC
        try:
            clean = date_str.split("+")[0].split("Z")[0]
            return datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def summary(self) -> dict[str, Any]:
        """Return a quick summary of the state."""
        result = self.sweep()
        return {
            "total_tasks": result.total_tasks,
            "status_counts": result.status_counts,
            "newly_stale": len(result.newly_stale),
            "active_high_priority": [t["title"] for t in result.active_high_priority],
            "waiting": [t["title"] for t in result.waiting_items],
            "dormant_threads": [t["topic"] for t in result.dormant_threads],
            "last_audit": self.data.get("lastAudit"),
        }
