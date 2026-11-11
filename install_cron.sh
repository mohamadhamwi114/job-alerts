#!/usr/bin/env bash
# Linux/macOS equivalent of register_task.ps1: adds (or replaces) a crontab entry running every 30 minutes.
# Remove with: ./install_cron.sh --remove
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
MARK="# linkedin-job-alerts"
chmod +x "$DIR/run_local.sh"

current="$(crontab -l 2>/dev/null | grep -v "$MARK" || true)"
if [[ "${1:-}" == "--remove" ]]; then
    printf '%s\n' "$current" | crontab -
    echo "Removed job-alerts cron entry."
    exit 0
fi

printf '%s\n%s\n' "$current" "*/30 * * * * \"$DIR/run_local.sh\" $MARK" | sed '/^$/d' | crontab -
echo "Installed: every 30 min -> $DIR/run_local.sh"
crontab -l | grep "$MARK"
