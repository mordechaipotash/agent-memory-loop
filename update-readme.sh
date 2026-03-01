#!/bin/bash
# update-readme.sh — Update README.md status table and push to GitHub
#
# Designed to run as a cron job (e.g., hourly):
#   0 * * * * cd /path/to/agent-memory-loop && ./update-readme.sh
#
# What it does:
#   1. Runs `memory-loop update-readme` to refresh the status table
#   2. If README.md changed, commits and pushes to GitHub
#   3. Exits cleanly if nothing changed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M')] update-readme:"

# 1. Update the README
echo "$LOG_PREFIX Running memory-loop update-readme..."
memory-loop update-readme --readme README.md 2>&1 || {
    echo "$LOG_PREFIX ❌ memory-loop update-readme failed"
    exit 1
}

# 2. Check if README changed
if git diff --quiet README.md 2>/dev/null; then
    echo "$LOG_PREFIX ℹ️ No changes to README.md"
    exit 0
fi

# 3. Commit and push
echo "$LOG_PREFIX 📝 README.md changed, committing..."
git add README.md
git commit -m "📊 Update live status table [automated]" --no-verify
git push origin main 2>&1 || {
    echo "$LOG_PREFIX ❌ git push failed"
    exit 1
}

echo "$LOG_PREFIX ✅ README.md updated and pushed"
