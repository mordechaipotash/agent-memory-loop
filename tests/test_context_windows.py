"""Tests for context window generation."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from agent_memory_loop.context_windows import (
    ContextWindowsConfig,
    detect_mode,
    extract_decisions,
    extract_topics,
    extract_user_messages,
    find_recent_sessions,
    format_summary,
    generate_all,
    generate_window,
)


def _make_session_line(text: str, role: str = "user") -> str:
    """Create a JSONL session line."""
    return json.dumps({
        "type": "message",
        "message": {
            "role": role,
            "content": [{"type": "text", "text": text}],
        },
    })


@pytest.fixture
def sessions_dir(tmp_path):
    """Create a temp directory with a mock session file."""
    d = tmp_path / "sessions"
    d.mkdir()

    session = d / "test-session.jsonl"
    lines = [
        _make_session_line("How do I deploy this to production?"),
        _make_session_line("I think we should go with Next.js for the frontend"),
        _make_session_line("let's go with the blue design"),
        _make_session_line("Fix the broken API endpoint"),
        _make_session_line("What about using Redis for caching?"),
        _make_session_line("decided to ship the MVP first"),
        _make_session_line("Research monotropism and ADHD patterns"),
        _make_session_line("deploy the agent to Railway"),
        _make_session_line("This is a response from assistant", role="assistant"),
        _make_session_line("system: cron job running", role="user"),  # noise
    ]
    session.write_text("\n".join(lines))
    return d


class TestFindRecentSessions:
    def test_finds_recent(self, sessions_dir):
        sessions = find_recent_sessions(sessions_dir, minutes=60)
        assert len(sessions) == 1

    def test_nonexistent_dir(self, tmp_path):
        sessions = find_recent_sessions(tmp_path / "nope", minutes=60)
        assert sessions == []

    def test_ignores_deleted(self, sessions_dir):
        deleted = sessions_dir / "old.deleted.jsonl"
        deleted.write_text("{}")
        sessions = find_recent_sessions(sessions_dir, minutes=60)
        assert len(sessions) == 1  # only the original


class TestExtractUserMessages:
    def test_extracts_user_only(self, sessions_dir):
        session_file = list(sessions_dir.glob("*.jsonl"))[0]
        messages = extract_user_messages(session_file)
        # Should get user messages minus noise (system: cron job)
        assert len(messages) >= 6
        assert all("assistant" not in m.lower() for m in messages[:6])

    def test_filters_noise(self, sessions_dir):
        session_file = list(sessions_dir.glob("*.jsonl"))[0]
        messages = extract_user_messages(session_file)
        assert not any("cron job" in m for m in messages)


class TestDetectMode:
    def test_thinking_mode(self):
        messages = [
            "What do you think about this?",
            "How should we approach this problem?",
            "Why does this happen?",
        ]
        assert detect_mode(messages) == "💭 thinking"

    def test_building_mode(self):
        messages = [
            "create file test.py",
            "deploy this to production",
            "run the tests",
            "open the browser",
            "send message to the team",
        ]
        assert detect_mode(messages) == "🏗️ building"

    def test_debugging_mode(self):
        messages = [
            "this is broken",
            "fix the error in the API",
            "not working again",
            "debug the crash",
            "error in the logs",
        ]
        assert "debugging" in detect_mode(messages)


class TestExtractTopics:
    def test_extracts_frequent_words(self):
        messages = [
            "deploy deploy deploy the agent",
            "agent memory agent system",
            "deploy the memory loop",
        ]
        topics = extract_topics(messages, max_words=3)
        words = [w for w, _ in topics]
        assert "deploy" in words
        assert "agent" in words

    def test_excludes_stop_words(self):
        messages = ["the and for this with that about just"]
        topics = extract_topics(messages)
        assert len(topics) == 0

    def test_respects_max_words(self):
        messages = ["alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo"]
        topics = extract_topics(messages, max_words=3)
        assert len(topics) == 3


class TestExtractDecisions:
    def test_finds_decisions(self):
        messages = [
            "just talking here",
            "let's go with the blue design",
            "decided to ship MVP first",
            "more chatting",
        ]
        decisions = extract_decisions(messages)
        assert len(decisions) == 2

    def test_respects_max(self):
        messages = [
            "decided A",
            "decided B",
            "decided C",
        ]
        decisions = extract_decisions(messages, max_decisions=2)
        assert len(decisions) == 2


class TestFormatSummary:
    def test_format_basic(self):
        from agent_memory_loop.context_windows import ContextSummary

        summary = ContextSummary(
            window="3h",
            icon="🔴",
            label="LAST 3 HOURS",
            session_count=5,
            message_count=42,
            mode="💭 thinking",
            topics=[("deploy", 10), ("agent", 8)],
            decisions=["let's go with blue"],
            generated_at="2026-03-01 10:00 IST",
        )
        text = format_summary(summary)
        assert "🔴 LAST 3 HOURS" in text
        assert "Sessions:** 5" in text
        assert "**deploy** (10x)" in text
        assert "let's go with blue" in text

    def test_format_empty(self):
        from agent_memory_loop.context_windows import ContextSummary

        summary = ContextSummary(
            window="3h",
            icon="🔴",
            label="LAST 3 HOURS",
            session_count=0,
            message_count=0,
            mode="💭 thinking",
            topics=[],
            decisions=[],
            generated_at="2026-03-01 10:00 IST",
        )
        text = format_summary(summary)
        assert "No activity detected" in text
        assert "None detected" in text


class TestGenerateAll:
    def test_generates_output_file(self, sessions_dir, tmp_path):
        output = tmp_path / "context-windows-current.md"
        config = ContextWindowsConfig(
            sessions_dir=str(sessions_dir),
            output_path=str(output),
            windows=["3h"],
        )
        summaries = generate_all(config)
        assert len(summaries) == 1
        assert output.exists()
        content = output.read_text()
        assert "Context Windows — Auto-Generated" in content
        assert "LAST 3 HOURS" in content
