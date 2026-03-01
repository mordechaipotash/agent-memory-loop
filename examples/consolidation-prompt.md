# Nightly Consolidation Prompt

**Purpose:** Cron agent reads today's activity and updates STATE.json accordingly.

**Schedule:** Nightly at 23:30 local time.

**Setup (with Clawdbot):**
```bash
clawdbot cron add \
  --name "state-consolidation" \
  --cron "30 23 * * *" \
  --tz "America/New_York" \
  --session isolated \
  --message "$(cat /path/to/consolidation-prompt.md)" \
  --deliver --channel discord
```

**Setup (plain cron — sends prompt to any LLM CLI):**
```bash
30 23 * * *  cat /path/to/consolidation-prompt.md | your-llm-cli --system "You are a maintenance agent"
```

---

## Prompt for the Cron Agent

You are the nightly consolidation agent. Your ONLY job is to update STATE.json based on today's activity.

### Steps:

1. **Read today's memory file:**
   ```
   memory/YYYY-MM-DD.md
   ```
   (Use today's actual date. Path is relative to your agent workspace.)

2. **Read current STATE.json:**
   ```
   STATE.json
   ```

3. **For each task in STATE.json:**
   - Was it mentioned today? → Update `lastTouched` to today's date
   - Was it completed? → Set `status: "done"`, update `lastTouched`
   - Was it discussed but not finished? → Keep `status: "active"`, update `lastTouched`
   - Was it explicitly abandoned? → Set `status: "archived"`, update `lastTouched`
   - Not mentioned and past `staleAfterDays`? → Set `status: "stale"`

4. **For new work today not in STATE.json:**
   - Add as a new task with the next available `tXXX` id
   - Set `created` and `lastTouched` to today
   - Set `source` to today's memory file
   - Determine `priority` based on context (high = deadline/blocking, medium = important, low = nice-to-have)
   - Set reasonable `staleAfterDays` (5 for urgent, 7 for normal, 14 for background)

5. **For decisions made today:**
   - Add to the `decisions` array with next available `dXXX` id
   - If it supersedes a previous decision, set `supersedes` to that id

6. **For threads:**
   - Update `lastActivity` if the thread was active today
   - Change `status` to "dormant" if no activity in 7+ days
   - Change `status` to "resolved" if explicitly closed
   - Add new threads if a new multi-session topic emerged

7. **Update `lastAudit` to now.**

### Rules:
- **NEVER just append** — always update existing entries
- **NEVER delete entries** — change status to "done" or "archived"
- **Keep context brief** — 1-2 sentences max
- **Be honest about status** — if something wasn't touched, don't pretend it was
- **Bump version** if you change the schema (you shouldn't need to)

### Output:
After updating STATE.json, post a brief summary:

```
📋 Nightly STATE.json consolidation:
- Updated: X items
- New: Y items
- Completed: Z items
- Newly stale: W items
- Active high-priority: [list titles]
```

If today's memory file doesn't exist, post:
```
📋 No memory file for today. STATE.json unchanged.
```
