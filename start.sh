#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PY=python3
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  command -v python3 >/dev/null 2>&1 || { echo "python3 not found"; exit 1; }
  python3 -m venv .venv
  PY=.venv/bin/python
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — set BOT_TOKEN in it, then run ./start.sh again."
  exit 1
fi

if [ -f bot.pid ] && kill -0 "$(cat bot.pid)" 2>/dev/null; then
  echo "Bot already running (pid $(cat bot.pid))"
  exit 0
fi

nohup "$PY" bot.py >/dev/null 2>&1 &
PID=$!
echo "$PID" > bot.pid
sleep 2
if kill -0 "$PID" 2>/dev/null; then
  echo "Bot started (pid $PID). No logs are saved. Safe to close this window."
else
  rm -f bot.pid
  echo "Bot failed to start. Run in foreground to see why: $PY bot.py"
  exit 1
fi
