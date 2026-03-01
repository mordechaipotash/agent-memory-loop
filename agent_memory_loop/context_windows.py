"""
context_windows.py — Generate time-windowed context summaries from session transcripts.

Extracted from generate-context-window.sh — the short-term memory layer.
Scans recent session files, extracts user messages, detects topics/mode/decisions,
and writes a structured context summary.

Supports three windows:
  - 3h  (🔴 immediate context)
  - 24h (🟡 today's context)
  - week (🔵 this week's context)
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ── Stop words (messages, not prose) ──────────────────────────────────
STOP_WORDS = frozenset(
    "the and for that this with you are was have from can not but what how all "
    "about just now get give its let see did has been will would could should our "
    "out into than them then also here more some your like make want please going "
    "really think know need look take come find help tell show use try one two new "
    "good back over last first next still even much very well only most best way "
    "time day got man right yeah okay from here give says said before were when "
    "where which these those there they been being each other after down same does "
    "done went keep every never always must might since also".split()
)

# ── Mode detection patterns ──────────────────────────────────────────
MODE_PATTERNS = {
    "🎭 conducting": re.compile(
        r"tts|tell them|show them|demo|spotlight|roleplay", re.I
    ),
    "🔧 debugging": re.compile(
        r"error|fix|broken|not working|debug|crash", re.I
    ),
    "🔬 exploring": re.compile(
        r"go deeper|10x|analyze|research|spawn|deploy agent", re.I
    ),
    "🏗️ building": re.compile(
        r"set timer|send message|deploy|create file|open |run ", re.I
    ),
}

# Decision language
DECISION_RE = re.compile(
    r"let.s go with|decided|ship it|send this|pick|chose|going with|the title",
    re.I,
)

# Noise filter — skip system/cron chatter
NOISE_RE = re.compile(
    r"^system:|cron:|exec completed|background task|heartbeat", re.I
)


@dataclass
class WindowConfig:
    """Configuration for a single time window."""

    name: str
    minutes: int
    label: str
    icon: str


WINDOWS = {
    "3h": WindowConfig("3h", 180, "LAST 3 HOURS", "🔴"),
    "24h": WindowConfig("24h", 1440, "LAST 24 HOURS", "🟡"),
    "week": WindowConfig("week", 10080, "LAST WEEK", "🔵"),
}


@dataclass
class ContextSummary:
    """Result of scanning a time window."""

    window: str
    icon: str
    label: str
    session_count: int
    message_count: int
    mode: str
    topics: list[tuple[str, int]]  # (word, count)
    decisions: list[str]
    generated_at: str


@dataclass
class ContextWindowsConfig:
    """Runtime configuration for the context window generator."""

    sessions_dir: str | Path
    output_path: str | Path
    windows: list[str] = field(default_factory=lambda: ["3h", "24h", "week"])
    max_topic_words: int = 10
    max_decisions: int = 5
    tail_lines: int = 500

    def __post_init__(self):
        self.sessions_dir = Path(self.sessions_dir)
        self.output_path = Path(self.output_path)


def find_recent_sessions(sessions_dir: Path, minutes: int) -> list[Path]:
    """Find session JSONL files modified within the given time window."""
    if not sessions_dir.exists():
        return []

    cutoff = datetime.now() - timedelta(minutes=minutes)
    recent = []
    for f in sessions_dir.glob("*.jsonl"):
        if ".deleted." in f.name:
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime >= cutoff:
            recent.append(f)
    return sorted(recent, key=lambda p: p.stat().st_mtime, reverse=True)


def extract_user_messages(
    session_file: Path, tail_lines: int = 500
) -> list[str]:
    """Extract recent user messages from a JSONL session file."""
    messages = []
    try:
        lines = session_file.read_text(errors="replace").splitlines()
        # Take the last N lines (like tail -N)
        for line in lines[-tail_lines:]:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "message":
                continue
            msg = entry.get("message", {})
            if msg.get("role") != "user":
                continue

            content = msg.get("content", [])
            if not content:
                continue
            first = content[0]
            if first.get("type") != "text":
                continue
            text = first.get("text", "")[:200]

            if not NOISE_RE.search(text):
                messages.append(text)
    except (OSError, PermissionError):
        pass
    return messages


def detect_mode(messages: list[str]) -> str:
    """Detect the current working mode from message patterns."""
    counts = {}
    combined = "\n".join(messages)
    for mode_name, pattern in MODE_PATTERNS.items():
        counts[mode_name] = len(pattern.findall(combined))

    # Conducting > debugging > exploring > building > thinking
    for mode_name in [
        "🎭 conducting",
        "🔧 debugging",
        "🔬 exploring",
        "🏗️ building",
    ]:
        if counts.get(mode_name, 0) > 3:
            return mode_name

    # Building vs thinking based on command/question ratio
    commands = counts.get("🏗️ building", 0)
    questions = len(
        re.findall(r"\?|what|how|why|should|think", combined, re.I)
    )
    if commands > questions:
        return "🏗️ building"
    return "💭 thinking"


def extract_topics(
    messages: list[str], max_words: int = 10
) -> list[tuple[str, int]]:
    """Extract top topic words from messages (excluding stop words)."""
    words = Counter()
    for msg in messages:
        for word in re.findall(r"[a-zA-Z]{4,}", msg.lower()):
            if word not in STOP_WORDS:
                words[word] += 1
    return words.most_common(max_words)


def extract_decisions(messages: list[str], max_decisions: int = 5) -> list[str]:
    """Extract messages containing decision language."""
    decisions = []
    for msg in messages:
        if DECISION_RE.search(msg):
            decisions.append(msg.strip())
            if len(decisions) >= max_decisions:
                break
    return decisions


def generate_window(
    config: ContextWindowsConfig, window_name: str
) -> ContextSummary:
    """Generate a context summary for a single time window."""
    wc = WINDOWS[window_name]
    sessions = find_recent_sessions(config.sessions_dir, wc.minutes)
    session_count = len(sessions)

    all_messages: list[str] = []
    for sf in sessions:
        all_messages.extend(
            extract_user_messages(sf, tail_lines=config.tail_lines)
        )

    return ContextSummary(
        window=window_name,
        icon=wc.icon,
        label=wc.label,
        session_count=session_count,
        message_count=len(all_messages),
        mode=detect_mode(all_messages),
        topics=extract_topics(all_messages, config.max_topic_words),
        decisions=extract_decisions(all_messages, config.max_decisions),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M %Z"),
    )


def format_summary(summary: ContextSummary) -> str:
    """Format a ContextSummary into markdown."""
    lines = [
        f"## {summary.icon} {summary.label}",
        f"**Sessions:** {summary.session_count} | "
        f"**Messages:** {summary.message_count} | "
        f"**Mode:** {summary.mode}",
        f"**Generated:** {summary.generated_at}",
        "",
        "### Topics",
    ]
    if summary.topics:
        for word, count in summary.topics:
            lines.append(f"- **{word}** ({count}x)")
    else:
        lines.append("_No activity detected_")

    lines.append("")
    lines.append("### Decisions")
    if summary.decisions:
        for d in summary.decisions:
            lines.append(f"- {d}")
    else:
        lines.append("_None detected_")

    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def generate_all(config: ContextWindowsConfig) -> list[ContextSummary]:
    """Generate context windows and write to the output file."""
    summaries = []
    output_parts = [
        "# Context Windows — Auto-Generated",
        f"**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        "---",
        "",
    ]

    for wname in config.windows:
        summary = generate_window(config, wname)
        summaries.append(summary)
        output_parts.append(format_summary(summary))

    # Write output
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_path.write_text("\n".join(output_parts))

    return summaries
