"""Tests for STATE.json management."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_memory_loop.state import StateManager, DEFAULT_STATE


@pytest.fixture
def state_file(tmp_path):
    """Create a temporary STATE.json."""
    path = tmp_path / "STATE.json"
    path.write_text(json.dumps(DEFAULT_STATE, indent=2))
    return path


@pytest.fixture
def state(state_file):
    """Create a StateManager with empty state."""
    return StateManager(state_file)


class TestStateManager:
    def test_load_empty(self, state):
        data = state.load()
        assert data["version"] == 1
        assert data["tasks"] == []
        assert data["decisions"] == []
        assert data["threads"] == []

    def test_load_creates_default_if_missing(self, tmp_path):
        path = tmp_path / "nonexistent" / "STATE.json"
        sm = StateManager(path)
        data = sm.load()
        assert data["version"] == 1

    def test_save_and_reload(self, state, state_file):
        state.load()
        state.add_task("Test task")
        state.save()

        # Reload
        sm2 = StateManager(state_file)
        sm2.load()
        assert len(sm2.data["tasks"]) == 1
        assert sm2.data["tasks"][0]["title"] == "Test task"

    def test_add_task(self, state):
        state.load()
        task = state.add_task(
            title="Build memory system",
            priority="high",
            context="First task",
            stale_after_days=5,
        )
        assert task["id"] == "t001"
        assert task["title"] == "Build memory system"
        assert task["status"] == "active"
        assert task["priority"] == "high"
        assert task["staleAfterDays"] == 5

    def test_add_task_auto_increment(self, state):
        state.load()
        t1 = state.add_task("First")
        t2 = state.add_task("Second")
        t3 = state.add_task("Third")
        assert t1["id"] == "t001"
        assert t2["id"] == "t002"
        assert t3["id"] == "t003"

    def test_get_task(self, state):
        state.load()
        state.add_task("Find me")
        result = state.get_task("t001")
        assert result is not None
        assert result["title"] == "Find me"

    def test_get_task_not_found(self, state):
        state.load()
        assert state.get_task("t999") is None

    def test_update_task(self, state):
        state.load()
        state.add_task("Update me")
        updated = state.update_task("t001", status="done", context="All done")
        assert updated["status"] == "done"
        assert updated["context"] == "All done"

    def test_update_task_touches_timestamp(self, state):
        state.load()
        state.add_task("Touch me")
        original_time = state.get_task("t001")["lastTouched"]
        import time
        time.sleep(0.01)
        state.update_task("t001", status="active")
        assert state.get_task("t001")["lastTouched"] != original_time

    def test_update_nonexistent_task(self, state):
        state.load()
        result = state.update_task("t999", status="done")
        assert result is None

    def test_add_decision(self, state):
        state.load()
        d = state.add_decision(
            description="Ship it",
            context="Ready to go",
        )
        assert d["id"] == "d001"
        assert d["description"] == "Ship it"
        assert d["supersedes"] is None

    def test_add_decision_with_supersedes(self, state):
        state.load()
        d1 = state.add_decision("Old decision")
        d2 = state.add_decision("New decision", supersedes="d001")
        assert d2["supersedes"] == "d001"

    def test_add_thread(self, state):
        state.load()
        th = state.add_thread(
            topic="Brain MCP launch",
            notes="Getting close",
        )
        assert th["id"] == "th001"
        assert th["topic"] == "Brain MCP launch"
        assert th["status"] == "active"

    def test_update_thread(self, state):
        state.load()
        state.add_thread("Test thread")
        updated = state.update_thread("th001", status="dormant", notes="Gone quiet")
        assert updated["status"] == "dormant"
        assert updated["notes"] == "Gone quiet"


class TestStalenessDetection:
    def test_sweep_empty(self, state):
        state.load()
        result = state.sweep()
        assert result.newly_stale == []
        assert result.total_tasks == 0

    def test_sweep_finds_stale(self, state):
        state.load()
        # Add a task with lastTouched 10 days ago, staleAfterDays=7
        task = state.add_task("Old task", stale_after_days=7)
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        task["lastTouched"] = old_date

        result = state.sweep()
        assert len(result.newly_stale) == 1
        assert result.newly_stale[0]["title"] == "Old task"

    def test_sweep_ignores_fresh(self, state):
        state.load()
        state.add_task("Fresh task", stale_after_days=7)
        result = state.sweep()
        assert len(result.newly_stale) == 0

    def test_sweep_ignores_done(self, state):
        state.load()
        task = state.add_task("Done task", stale_after_days=1)
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        task["lastTouched"] = old_date
        task["status"] = "done"

        result = state.sweep()
        assert len(result.newly_stale) == 0

    def test_mark_stale_auto(self, state):
        state.load()
        task = state.add_task("Going stale", stale_after_days=3)
        old_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        task["lastTouched"] = old_date

        count = state.mark_stale()
        assert count == 1
        assert state.get_task("t001")["status"] == "stale"

    def test_mark_stale_specific_ids(self, state):
        state.load()
        state.add_task("Task A")
        state.add_task("Task B")
        count = state.mark_stale(["t002"])
        assert count == 1
        assert state.get_task("t001")["status"] == "active"
        assert state.get_task("t002")["status"] == "stale"

    def test_status_counts(self, state):
        state.load()
        state.add_task("Active 1")
        state.add_task("Active 2")
        t3 = state.add_task("Done 1")
        state.update_task("t003", status="done")

        result = state.sweep()
        assert result.status_counts["active"] == 2
        assert result.status_counts["done"] == 1

    def test_summary(self, state):
        state.load()
        state.add_task("High priority", priority="high")
        state.add_task("Low priority", priority="low")
        state.add_thread("Active thread")

        summary = state.summary()
        assert summary["total_tasks"] == 2
        assert "High priority" in summary["active_high_priority"]
        assert summary["newly_stale"] == 0


class TestDateParsing:
    def test_parse_iso_with_offset(self):
        dt = StateManager._parse_date("2026-02-28T23:30:00+02:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 2

    def test_parse_iso_utc(self):
        dt = StateManager._parse_date("2026-02-28T21:30:00Z")
        assert dt is not None

    def test_parse_iso_plain(self):
        dt = StateManager._parse_date("2026-02-28T21:30:00")
        assert dt is not None

    def test_parse_empty(self):
        assert StateManager._parse_date("") is None

    def test_parse_invalid(self):
        assert StateManager._parse_date("not-a-date") is None
