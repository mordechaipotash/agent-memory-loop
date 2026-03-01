#!/bin/bash
# generate-context-window.sh — Auto-generate time-windowed context summaries
# Usage: ./generate-context-window.sh [3h|24h|week]
# Output: $WORKSPACE/memory/context-windows-current.md
#
# This is the original shell implementation of context-windows.
# The Python version (memory-loop run context-windows) does the same thing.
# Use this if you want zero dependencies — just bash + jq.
#
# Setup:
#   crontab -e
#   */15 * * * * /path/to/generate-context-window.sh 3h
#   */15 * * * * /path/to/generate-context-window.sh 24h
#   */15 * * * * /path/to/generate-context-window.sh week

# --- Configuration (override via environment) ---
WORKSPACE="${AGENT_WORKSPACE:-$HOME/agent-workspace}"
SESSIONS_DIR="${AGENT_SESSIONS_DIR:-$HOME/.clawdbot/agents/main/sessions}"
OUTPUT="${CONTEXT_WINDOWS_OUTPUT:-$WORKSPACE/memory/context-windows-current.md}"

WINDOW="${1:-3h}"
NOW=$(date -u +%Y-%m-%dT%H:%M:%S)
NOW_LOCAL=$(date +"%Y-%m-%d %H:%M %Z")

# Calculate time threshold
case "$WINDOW" in
  3h)  MINS=180;  LABEL="LAST 3 HOURS";  ICON="🔴" ;;
  24h) MINS=1440; LABEL="LAST 24 HOURS"; ICON="🟡" ;;
  week) MINS=10080; LABEL="LAST WEEK";   ICON="🔵" ;;
  *) echo "Usage: $0 [3h|24h|week]"; exit 1 ;;
esac

# Find recent session files
RECENT_FILES=$(find "$SESSIONS_DIR" -name "*.jsonl" -mmin -${MINS} ! -name "*.deleted.*" 2>/dev/null)
SESSION_COUNT=$(echo "$RECENT_FILES" | grep -c "jsonl" 2>/dev/null || echo "0")

# Extract user messages from recent sessions
TEMP_MSGS=$(mktemp)
for f in $RECENT_FILES; do
  tail -500 "$f" | jq -r "
    select(.type==\"message\") |
    select(.message.role==\"user\") |
    select(.message.content[0].type==\"text\") |
    .message.content[0].text | .[0:200]
  " 2>/dev/null | grep -iv "^system:\|cron:\|exec completed\|background task\|heartbeat"
done > "$TEMP_MSGS" 2>/dev/null

MSG_COUNT=$(wc -l < "$TEMP_MSGS" | tr -d ' ')

# Detect mode from message patterns
COMMANDS=$(grep -cEi "set timer|send message|deploy|create file|open |run " "$TEMP_MSGS" 2>/dev/null || echo "0")
QUESTIONS=$(grep -cEi "\?|what|how|why|should|think" "$TEMP_MSGS" 2>/dev/null || echo "0")
DEEP_CMDS=$(grep -cEi "go deeper|10x|analyze|research|spawn|deploy agent" "$TEMP_MSGS" 2>/dev/null || echo "0")
DEBUG_CMDS=$(grep -cEi "error|fix|broken|not working|debug|crash" "$TEMP_MSGS" 2>/dev/null || echo "0")
CONDUCT_CMDS=$(grep -cEi "tts|tell them|show them|demo|spotlight|roleplay" "$TEMP_MSGS" 2>/dev/null || echo "0")

# Determine mode (handle empty values)
COMMANDS=$(echo "${COMMANDS}" | tr -d '[:space:]'); COMMANDS=${COMMANDS:-0}
QUESTIONS=$(echo "${QUESTIONS}" | tr -d '[:space:]'); QUESTIONS=${QUESTIONS:-0}
DEEP_CMDS=$(echo "${DEEP_CMDS}" | tr -d '[:space:]'); DEEP_CMDS=${DEEP_CMDS:-0}
DEBUG_CMDS=$(echo "${DEBUG_CMDS}" | tr -d '[:space:]'); DEBUG_CMDS=${DEBUG_CMDS:-0}
CONDUCT_CMDS=$(echo "${CONDUCT_CMDS}" | tr -d '[:space:]'); CONDUCT_CMDS=${CONDUCT_CMDS:-0}

if [ "$CONDUCT_CMDS" -gt 3 ] 2>/dev/null; then MODE="🎭 conducting"
elif [ "$DEBUG_CMDS" -gt 3 ] 2>/dev/null; then MODE="🔧 debugging"
elif [ "$DEEP_CMDS" -gt 3 ] 2>/dev/null; then MODE="🔬 exploring"
elif [ "$COMMANDS" -gt "$QUESTIONS" ] 2>/dev/null; then MODE="🏗️ building"
else MODE="💭 thinking"
fi

# Extract key topics (top words, excluding common)
TOPICS=$(cat "$TEMP_MSGS" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alpha:]' '\n' | \
  grep -vE "^.{0,3}$" | \
  grep -vE "^(the|and|for|that|this|with|you|are|was|have|from|can|not|but|what|how|all|about|just|now|get|give|its|let|see|did|has|been|will|would|could|should|our|out|into|than|them|then|also|here|more|some|your|like|make|want|please|going|really|think|know|need|look|take|come|find|help|tell|show|use|try|one|two|new|good|back|over|last|first|next|still|even|much|very|well|just|only|most|best|way|time|day|got|man|right|yeah|okay|discord|guild|general|channel|message|from|here|give|says|said|before|were|when|where|which|these|those|there|they|been|being|each|other|after|down|same|does|done|went|keep|every|never|always|also|must|might|chat|messages|since|reply|context|current|respond|attached|media|inbound|image|send|prefer|tool|file|path|caption|text|body|quote|inline|spaces)$" | \
  sort | uniq -c | sort -rn | head -10 | awk '{print "- **" $2 "** (" $1 "x)"}')

# Extract decisions (messages containing decision language)
DECISIONS=$(grep -iE "let.s go with|decided|ship it|send this|pick|chose|going with|the title" "$TEMP_MSGS" | head -5 | sed 's/^/- /')

# Ensure output directory exists
mkdir -p "$(dirname "$OUTPUT")"

# Write output
if [ "$WINDOW" = "3h" ]; then
  # For 3h window, overwrite the whole file starting with 3h section
  cat > "$OUTPUT" << EOF
# Context Windows — Auto-Generated
**Last updated:** $NOW_LOCAL

---

## $ICON $LABEL
**Sessions:** $SESSION_COUNT | **Messages:** $MSG_COUNT | **Mode:** $MODE
**Generated:** $NOW_LOCAL

### Topics
$TOPICS

### Decisions
${DECISIONS:-_None detected_}

---

EOF
else
  # For 24h and week, append
  cat >> "$OUTPUT" << EOF
## $ICON $LABEL
**Sessions:** $SESSION_COUNT | **Messages:** $MSG_COUNT | **Mode:** $MODE
**Generated:** $NOW_LOCAL

### Topics
$TOPICS

### Decisions
${DECISIONS:-_None detected_}

---

EOF
fi

rm -f "$TEMP_MSGS"
echo "[$WINDOW] Generated: $SESSION_COUNT sessions, $MSG_COUNT messages, mode=$MODE"
