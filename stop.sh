#!/usr/bin/env bash
cd "$(dirname "$0")"

if [ ! -f bot.pid ]; then
  echo "No bot.pid — bot is not running (or was started without start.sh)"
  exit 0
fi

PID="$(cat bot.pid)"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  for _ in 1 2 3 4 5; do
    kill -0 "$PID" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null || true
  fi
  echo "Bot stopped (pid $PID)"
else
  echo "Bot was not running (stale pid file removed)"
fi
rm -f bot.pid
