"""
cli.py — Click-based CLI for agent-memory-loop.

Commands:
  memory-loop status            Show current system status
  memory-loop run <job>         Run a specific job
  memory-loop update-readme     Update README.md status table
  memory-loop sweep             Run staleness detection
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import click

from .context_windows import ContextWindowsConfig, generate_all, generate_window, WINDOWS
from .daily_notes import generate_daily_note
from .consolidation import Consolidator
from .state import StateManager
from .readme_updater import update_readme, DEFAULT_JOBS


def _find_config() -> dict:
    """Find and load configuration."""
    # Look for brain.yaml or .memory-loop.yaml
    for name in ["brain.yaml", ".memory-loop.yaml", ".memory-loop.json"]:
        p = Path.cwd() / name
        if p.exists():
            if name.endswith(".json"):
                return json.loads(p.read_text())
            try:
                import yaml

                return yaml.safe_load(p.read_text()) or {}
            except ImportError:
                click.echo(f"Found {name} but PyYAML not installed. Using defaults.", err=True)
                return {}
    return {}


def _get_sessions_dir(config: dict) -> str:
    """Get sessions directory from config or default."""
    return config.get(
        "sessions_dir",
        str(Path.home() / ".clawdbot" / "agents" / "main" / "sessions"),
    )


def _get_memory_dir(config: dict) -> str:
    """Get memory directory from config or default."""
    return config.get("memory_dir", str(Path.cwd() / "memory"))


def _get_state_path(config: dict) -> str:
    """Get STATE.json path from config or default."""
    return config.get("state_path", str(Path.cwd() / "STATE.json"))


def _get_output_path(config: dict) -> str:
    """Get context windows output path from config or default."""
    return config.get(
        "context_output", str(Path.cwd() / "memory" / "context-windows-current.md")
    )


@click.group()
@click.version_option(package_name="agent-memory-loop")
def cli():
    """🔄 agent-memory-loop — Your AI agent has amnesia. This fixes it."""
    pass


@cli.command()
@click.option("--state", "state_path", default=None, help="Path to STATE.json")
@click.option("--json-output", "as_json", is_flag=True, help="Output as JSON")
def status(state_path: str | None, as_json: bool):
    """Show current memory system status."""
    config = _find_config()
    if state_path is None:
        state_path = _get_state_path(config)

    state = StateManager(state_path)
    try:
        state.load()
    except FileNotFoundError:
        click.echo(f"❌ STATE.json not found at {state_path}", err=True)
        sys.exit(1)

    summary = state.summary()

    if as_json:
        click.echo(json.dumps(summary, indent=2))
        return

    click.echo("🔄 agent-memory-loop status")
    click.echo("=" * 40)
    click.echo(f"📋 Total tasks: {summary['total_tasks']}")
    click.echo(f"📊 Status breakdown:")
    for status_name, count in sorted(summary["status_counts"].items()):
        emoji = {"active": "🟢", "done": "✅", "stale": "⚠️", "waiting": "⏳", "blocked": "🔴", "archived": "📦"}.get(
            status_name, "❓"
        )
        click.echo(f"   {emoji} {status_name}: {count}")
    click.echo(f"⚠️  Newly stale: {summary['newly_stale']}")
    if summary["active_high_priority"]:
        click.echo(f"🔥 High priority:")
        for title in summary["active_high_priority"]:
            click.echo(f"   → {title}")
    if summary["dormant_threads"]:
        click.echo(f"💤 Dormant threads:")
        for topic in summary["dormant_threads"]:
            click.echo(f"   → {topic}")
    click.echo(f"🕐 Last audit: {summary['last_audit'] or 'never'}")


@cli.group()
def run():
    """Run a specific memory loop job."""
    pass


@run.command("context-windows")
@click.option("--window", "-w", multiple=True, default=["3h", "24h", "week"], help="Windows to generate")
@click.option("--sessions-dir", default=None, help="Path to session JSONL files")
@click.option("--output", "-o", default=None, help="Output file path")
def run_context_windows(window: tuple[str, ...], sessions_dir: str | None, output: str | None):
    """Generate time-windowed context summaries."""
    config = _find_config()

    cw_config = ContextWindowsConfig(
        sessions_dir=sessions_dir or _get_sessions_dir(config),
        output_path=output or _get_output_path(config),
        windows=list(window),
    )

    click.echo(f"📡 Scanning sessions in {cw_config.sessions_dir}")
    summaries = generate_all(cw_config)

    for s in summaries:
        click.echo(f"  {s.icon} [{s.window}] {s.session_count} sessions, {s.message_count} messages, mode={s.mode}")

    click.echo(f"✅ Written to {cw_config.output_path}")


@run.command("daily-notes")
@click.option("--sessions-dir", default=None, help="Path to session files")
@click.option("--memory-dir", default=None, help="Path to memory directory")
@click.option("--date", default=None, help="Date (YYYY-MM-DD), default today")
def run_daily_notes(sessions_dir: str | None, memory_dir: str | None, date: str | None):
    """Generate today's daily memory note."""
    config = _find_config()

    dt = datetime.strptime(date, "%Y-%m-%d") if date else None
    result = generate_daily_note(
        sessions_dir=sessions_dir or _get_sessions_dir(config),
        output_dir=memory_dir or _get_memory_dir(config),
        date=dt,
    )

    if result:
        click.echo(f"✅ Daily note written to {result}")
    else:
        click.echo("⚠️ No session activity found for today.")


@run.command("consolidation")
@click.option("--state", "state_path", default=None, help="Path to STATE.json")
@click.option("--memory-dir", default=None, help="Path to memory directory")
@click.option("--date", default=None, help="Date (YYYY-MM-DD)")
@click.option("--generate-prompt", "gen_prompt", is_flag=True, help="Output LLM prompt instead of running")
def run_consolidation(state_path: str | None, memory_dir: str | None, date: str | None, gen_prompt: bool):
    """Run nightly STATE.json consolidation."""
    config = _find_config()

    consolidator = Consolidator(
        state_path=state_path or _get_state_path(config),
        memory_dir=memory_dir or _get_memory_dir(config),
    )

    dt = datetime.strptime(date, "%Y-%m-%d") if date else None
    result = consolidator.run(dt)

    if gen_prompt:
        click.echo(consolidator.generate_prompt(result))
    else:
        click.echo(consolidator.format_summary(result))


@cli.command()
@click.option("--state", "state_path", default=None, help="Path to STATE.json")
def sweep(state_path: str | None):
    """Run staleness detection on STATE.json."""
    config = _find_config()
    state_path = state_path or _get_state_path(config)

    state = StateManager(state_path)
    state.load()
    result = state.sweep()

    click.echo(f"🧹 STATE.json Sweep — {datetime.now().strftime('%Y-%m-%d %H:%M %Z')}")
    click.echo("=" * 50)
    click.echo(f"\n📊 Summary:")
    for status_name, count in sorted(result.status_counts.items()):
        click.echo(f"  {status_name}: {count}")
    click.echo(f"  TOTAL: {result.total_tasks}")

    if result.newly_stale:
        click.echo(f"\n⚠️ Newly stale items ({len(result.newly_stale)}):")
        for t in result.newly_stale:
            click.echo(f"  🔴 {t['id']}: {t['title']}")
    else:
        click.echo("\n✅ No newly stale items.")

    if result.active_high_priority:
        click.echo(f"\n🔥 Active high-priority:")
        for t in result.active_high_priority:
            click.echo(f"  → {t['id']}: {t['title']}")

    if result.waiting_items:
        click.echo(f"\n⏳ Waiting:")
        for t in result.waiting_items:
            click.echo(f"  → {t['id']}: {t['title']}")

    if result.dormant_threads:
        click.echo(f"\n💤 Dormant threads:")
        for t in result.dormant_threads:
            click.echo(f"  → {t['id']}: {t['topic']}")


@cli.command("update-readme")
@click.option("--readme", default=None, help="Path to README.md")
def update_readme_cmd(readme: str | None):
    """Update README.md with live status table."""
    if readme is None:
        readme = str(Path.cwd() / "README.md")

    changed = update_readme(readme)
    if changed:
        click.echo(f"✅ README.md updated with live status")
    else:
        click.echo("ℹ️ README.md unchanged (no markers found or no changes)")


def main():
    cli()


if __name__ == "__main__":
    main()
