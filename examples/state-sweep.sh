#!/bin/bash
# state-sweep.sh — Mark stale items in STATE.json
# Run weekly via cron (e.g., Sunday 10am)
#
# This is the original shell implementation of the staleness sweep.
# The Python version (memory-loop sweep) does the same thing.
# Use this if you want zero dependencies — just bash + jq.
#
# Setup (with Clawdbot):
#   clawdbot cron add \
#     --name "state-sweep" \
#     --cron "0 10 * * 0" \
#     --tz "America/New_York" \
#     --session isolated \
#     --message "Run state sweep and post summary"
#
# Setup (plain cron):
#   0 10 * * 0  /path/to/state-sweep.sh

# --- Configuration (override via environment) ---
WORKSPACE="${AGENT_WORKSPACE:-$HOME/agent-workspace}"
STATE_FILE="${STATE_JSON_PATH:-$WORKSPACE/STATE.json}"

if [ ! -f "$STATE_FILE" ]; then
  echo "❌ STATE.json not found at $STATE_FILE"
  exit 1
fi

NOW_EPOCH=$(date +%s)
STALE_COUNT=0
ACTIVE_COUNT=0
WAITING_COUNT=0
DONE_COUNT=0
TOTAL=0

echo "🧹 STATE.json Sweep — $(date '+%Y-%m-%d %H:%M %Z')"
echo "================================================"
echo ""

# Use jq to find stale items
# An item is stale if: status is "active", and lastTouched is more than staleAfterDays ago
STALE_ITEMS=$(jq -r --argjson now "$NOW_EPOCH" '
  .tasks[] |
  select(.status == "active") |
  .lastTouched as $lt |
  .staleAfterDays as $sad |
  # Parse ISO8601 date (basic — strips timezone for epoch calc)
  ($lt | sub("\\+.*";"") | sub("T";" ") | strptime("%Y-%m-%d %H:%M:%S") | mktime) as $ltEpoch |
  ($sad * 86400) as $staleSeconds |
  select(($now - $ltEpoch) > $staleSeconds) |
  "\(.id)|\(.title)|\(.lastTouched)|\(.staleAfterDays)"
' "$STATE_FILE" 2>/dev/null)

echo "📊 Summary:"
echo ""

# Count by status
jq -r '.tasks[] | .status' "$STATE_FILE" | sort | uniq -c | while read count status; do
  echo "  $status: $count"
done

TOTAL=$(jq '.tasks | length' "$STATE_FILE")
echo "  TOTAL: $TOTAL"
echo ""

if [ -z "$STALE_ITEMS" ]; then
  echo "✅ No newly stale items found."
else
  echo "⚠️  Items that should be marked STALE:"
  echo ""
  echo "$STALE_ITEMS" | while IFS='|' read id title lastTouched staleAfterDays; do
    DAYS_AGO=$(( (NOW_EPOCH - $(date -j -f "%Y-%m-%dT%H:%M:%S" "$(echo $lastTouched | sed 's/+.*//')" +%s 2>/dev/null || echo $NOW_EPOCH)) / 86400 ))
    echo "  🔴 $id: $title"
    echo "     Last touched: $lastTouched ($DAYS_AGO days ago, threshold: ${staleAfterDays}d)"
    echo ""
  done

  echo ""
  echo "To mark these as stale, update STATE.json:"
  echo '  jq ".tasks |= map(if .id == \"ID\" then .status = \"stale\" | .lastTouched = \"NOW\" else . end)" STATE.json'
fi

echo ""
echo "📋 Active high-priority items:"
jq -r '.tasks[] | select(.status == "active" and .priority == "high") | "  🔥 \(.id): \(.title)"' "$STATE_FILE"

echo ""
echo "⏳ Waiting items:"
jq -r '.tasks[] | select(.status == "waiting") | "  ⏳ \(.id): \(.title)"' "$STATE_FILE"

echo ""
echo "💤 Dormant threads:"
jq -r '.threads[] | select(.status == "dormant") | "  💤 \(.id): \(.topic) — \(.notes)"' "$STATE_FILE"
