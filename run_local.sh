#!/usr/bin/env bash
# Linux/macOS equivalent of run_local.ps1: one local run, output appended to logs/run_YYYY-MM-DD.log
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs
exec .venv/bin/python job_alerts.py --runner local >> "logs/run_$(date +%F).log" 2>&1
