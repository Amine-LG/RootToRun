#!/usr/bin/env bash
# Stop the academy server (only this app) and wait until its port is free.
cd "$(dirname "$0")" || exit
[ -f data/server.pid ] || { echo "not running"; exit 0; }
pid="$(cat data/server.pid)"
# the PID file may be stale and its number reused by another program: only stop this checkout's own server (the
# academy's command line, started from this directory; where /proc is missing, as on macOS, the command line only)
cmd=""; cwd="$(pwd -P)"
if [[ "$pid" =~ ^[0-9]+$ ]]; then
  if [ -r "/proc/$pid/cmdline" ]; then
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)"; cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)"
  else
    cmd="$(ps -p "$pid" -o command= 2>/dev/null)"
  fi
fi
if [[ "$cmd" != *"uvicorn academy.main:app"* ]] || [ "$cwd" != "$(pwd -P)" ]; then
  rm -f data/server.pid; echo "not running (stale PID file removed)"; exit 0
fi
kill "$pid" 2>/dev/null || { rm -f data/server.pid; echo "not running"; exit 0; }
for _ in $(seq 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
rm -f data/server.pid
echo stopped
