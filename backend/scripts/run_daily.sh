#!/bin/bash
# HomeScout daily run (called by launchd at 8:00 AM local time; Mac is on America/New_York).
set -euo pipefail
BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/HomeScout"
mkdir -p "$LOG_DIR"
cd "$BACKEND_DIR"
PY="$(/Users/bryampiedra/.local/bin/poetry env info -p)/bin/python"
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  "$PY" -m app.jobs.daily_search "$@"
  echo "exit: $?"
} >> "$LOG_DIR/daily.log" 2>&1
