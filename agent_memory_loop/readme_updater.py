"""
readme_updater.py — THE SHOWSTOPPER.

Reads cron job statuses and writes a live status table into the repo's own README.md.
The table lives between <!-- STATUS:START --> and <!-- STATUS:END --> markers.

Shows: job name, last run time, status emoji, next scheduled run.

This is designed to run as a cron job itself — updating the README hourly
so the repo always shows a live dashboard of your memory system's health.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


STATUS_START = "<!-- STATUS:START -->"
STATUS_END = "<!-- STATUS:END -->"


@dataclass
class CronJob:
    """Definition of a cron job to monitor."""

    name: str
    schedule: str
    purpose: str
    log_file: str | None = None
    check_command: str | None = None


@dataclass
class JobStatus:
    """Runtime status of a cron job."""

    job: CronJob
    last_run: datetime | None = None
    status: str = "unknown"  # ok, stale, error, unknown
    next_run: str = ""
    detail: str = ""


# ── Default cron schedule (the full memory loop) ─────────────────────

DEFAULT_JOBS: list[CronJob] = [
    CronJob(
        "context-windows",
        "*/15 * * * *",
        "3h/24h/week context summaries",
    ),
    CronJob(
        "brain-sync-hourly",
        "5 * * * *",
        "Sessions → parquet",
    ),
    CronJob(
        "daily-notes",
        "0 23 * * 0-4,6",
        "Write memory/YYYY-MM-DD.md",
    ),
    CronJob(
        "nightly-consolidation",
        "30 23 * * 0-4,6",
        "Update STATE.json",
    ),
    CronJob(
        "weekly-memory-maintenance",
        "0 22 * * 5",
        "Review week → update MEMORY.md",
    ),
    CronJob(
        "brain-sync-unified",
        "0 3 * * *",
        "All sources + embeddings",
    ),
    CronJob(
        "brain-summary-pipeline",
        "15 3 * * *",
        "New convos → structured summaries",
    ),
    CronJob(
        "github-sync",
        "30 2 * * *",
        "GitHub repos + commits",
    ),
]


def detect_job_status(
    job: CronJob,
    log_dir: str | Path | None = None,
    now: datetime | None = None,
) -> JobStatus:
    """
    Detect the status of a cron job.

    Checks:
    1. Log file modification time (if log_file specified)
    2. Custom check command (if check_command specified)
    3. Falls back to "unknown" if no signals available

    Status:
    - ✅ ok: ran within expected interval
    - ⚠️ stale: overdue based on schedule
    - ❌ error: check command failed
    - ❓ unknown: no data available
    """
    if now is None:
        now = datetime.now(timezone.utc)

    status = JobStatus(job=job)

    # Try log file
    if job.log_file:
        log_path = Path(job.log_file).expanduser()
        if log_path.exists():
            mtime = datetime.fromtimestamp(
                log_path.stat().st_mtime, tz=timezone.utc
            )
            status.last_run = mtime
            expected_interval = _parse_cron_interval(job.schedule)
            if (now - mtime) < expected_interval * 2:
                status.status = "ok"
            else:
                status.status = "stale"

    # Try check command
    if job.check_command:
        try:
            result = subprocess.run(
                job.check_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                status.status = "ok"
                status.detail = result.stdout.strip()[:100]
            else:
                status.status = "error"
                status.detail = result.stderr.strip()[:100]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            status.status = "error"

    # Calculate next run (approximate)
    status.next_run = _estimate_next_run(job.schedule, now)

    return status


def _parse_cron_interval(schedule: str) -> timedelta:
    """Estimate the interval between cron runs (rough approximation)."""
    parts = schedule.split()
    if not parts:
        return timedelta(hours=24)

    minute = parts[0] if len(parts) > 0 else "*"

    if minute.startswith("*/"):
        try:
            return timedelta(minutes=int(minute[2:]))
        except ValueError:
            pass

    hour = parts[1] if len(parts) > 1 else "*"
    if hour == "*" and minute != "*":
        return timedelta(hours=1)

    return timedelta(hours=24)


def _estimate_next_run(schedule: str, now: datetime) -> str:
    """Rough estimate of next run time."""
    interval = _parse_cron_interval(schedule)
    next_time = now + interval
    return next_time.strftime("%H:%M UTC")


STATUS_EMOJI = {
    "ok": "✅",
    "stale": "⚠️",
    "error": "❌",
    "unknown": "❓",
}


def generate_status_table(
    jobs: list[CronJob] | None = None,
    log_dir: str | Path | None = None,
) -> str:
    """Generate a markdown status table for all monitored jobs."""
    if jobs is None:
        jobs = DEFAULT_JOBS

    now = datetime.now(timezone.utc)
    statuses = [detect_job_status(job, log_dir, now) for job in jobs]

    lines = [
        f"> Last checked: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "| Status | Job | Schedule | Purpose | Last Run | Next Run |",
        "|--------|-----|----------|---------|----------|----------|",
    ]

    for s in statuses:
        emoji = STATUS_EMOJI.get(s.status, "❓")
        last_run = (
            s.last_run.strftime("%Y-%m-%d %H:%M")
            if s.last_run
            else "—"
        )
        lines.append(
            f"| {emoji} | **{s.job.name}** | `{s.job.schedule}` | "
            f"{s.job.purpose} | {last_run} | {s.next_run} |"
        )

    return "\n".join(lines)


def update_readme(
    readme_path: str | Path,
    jobs: list[CronJob] | None = None,
    log_dir: str | Path | None = None,
) -> bool:
    """
    Update the README.md status table between markers.

    Returns True if the file was changed, False otherwise.
    """
    readme_path = Path(readme_path)
    if not readme_path.exists():
        return False

    content = readme_path.read_text()

    # Find markers
    start_idx = content.find(STATUS_START)
    end_idx = content.find(STATUS_END)
    if start_idx == -1 or end_idx == -1:
        return False

    # Generate new status
    table = generate_status_table(jobs, log_dir)
    new_section = f"{STATUS_START}\n{table}\n{STATUS_END}"

    # Replace
    old_section = content[start_idx : end_idx + len(STATUS_END)]
    new_content = content.replace(old_section, new_section)

    if new_content == content:
        return False

    readme_path.write_text(new_content)
    return True
