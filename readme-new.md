# agent-memory-loop

**Your AI agent has amnesia. This fixes it.**

https://github.com/mordechaipotash/agent-memory-loop/raw/main/assets/demo.mp4

---

Every AI agent wakes up with zero memory. The decision you made yesterday? Forgotten. The task you started last week? What task?

`agent-memory-loop` is the maintenance layer that makes stateless LLMs feel stateful.

---

## Install

```bash
pip install agent-memory-loop
agent-memory init
```

## What It Does

Five cron jobs that automatically build layered memory:

| Job | Schedule | What it does |
|-----|----------|-------------|
| **context-windows** | Every 15 min | 3h/24h/week context summaries |
| **daily-notes** | 11pm | Write memory/YYYY-MM-DD.md |
| **nightly-consolidation** | 11:30pm | Update STATE.json (tasks, decisions, threads) |
| **weekly-maintenance** | Friday | Review week → update long-term MEMORY.md |
| **brain-sync** | Hourly | Sessions → searchable archive |

---

## The Memory Cascade

```
Real-time context (15 min)
    ↓ consolidates into
Daily notes (nightly)
    ↓ consolidates into
Weekly memory (Friday)
    ↓ curated into
Long-term MEMORY.md (persistent)
```

Most "memory" solutions are just a vector database. That's a library card, not a brain.

Real memory is layered. Short-term fades fast. Medium-term consolidates overnight. Long-term is curated over weeks. This replicates that.

---

## Works With

Any agent framework that reads files:
- Clawdbot
- Claude Code (CLAUDE.md)
- Custom agents
- Anything that can read markdown

---

## File Structure

```
your-agent/
├── MEMORY.md                  # Long-term (curated)
├── STATE.json                 # Tasks, decisions, threads
└── memory/
    ├── context-windows-current.md  # Right now
    ├── 2026-03-01.md              # Yesterday
    └── 2026-03-02.md              # Today
```

Your agent reads these on startup. Instant context.

---

## Part of the ecosystem

[brain-mcp](https://github.com/mordechaipotash/brain-mcp) · [local-voice-ai](https://github.com/mordechaipotash/local-voice-ai) · [x-search](https://github.com/mordechaipotash/x-search) · [mordenews](https://github.com/mordechaipotash/mordenews)

## License

MIT
