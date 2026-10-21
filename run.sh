#!/usr/bin/env bash
# The academy on http://127.0.0.1:8768 (local only).
#   ./run.sh            build the frontend if needed, start the server in the background (log: data/server.log)
#   ./run.sh --fg       same, in the foreground
#   ACADEMY_CLUSTER=off ./run.sh   practice mode: no cluster access at all, recorded outputs only
#   ./stop.sh           stop it
set -euo pipefail
cd "$(dirname "$0")"
PORT="${ACADEMY_PORT:-8768}"
mkdir -p data
if [ ! -x .venv/bin/python ]; then
  echo "• creating .venv"; uv venv .venv --python 3.12 -q && uv pip install -q --python .venv/bin/python -r requirements.txt
fi
if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html frontend/product.json -newer frontend/dist/index.html -print -quit 2>/dev/null)" ]; then
  echo "• building the frontend"
  (cd frontend && { [ -d node_modules ] || npm ci --silent --prefer-offline; } && nice npm run -s build >/dev/null)
fi
if ss -ltn 2>/dev/null | grep -q "127.0.0.1:${PORT} "; then echo "! port ${PORT} busy (already running? ./stop.sh)"; exit 1; fi
echo
NAME="$(.venv/bin/python -c 'import json; print(json.load(open("frontend/product.json"))["name"])' 2>/dev/null || echo "The academy")"
echo "  ${NAME} → http://127.0.0.1:${PORT}"
echo
CMD=(.venv/bin/python -m uvicorn academy.main:app --app-dir backend --host 127.0.0.1 --no-proxy-headers --port "$PORT" --log-level warning)
if [ "${1:-}" = "--fg" ]; then exec "${CMD[@]}"; fi
nohup "${CMD[@]}" >>data/server.log 2>&1 &
echo $! > data/server.pid
for _ in $(seq 30); do curl -fsS "http://127.0.0.1:${PORT}/api/status" -o /dev/null 2>/dev/null && { echo "  running (pid $(cat data/server.pid))"; exit 0; }; sleep 0.5; done
echo "! did not start; see data/server.log"; exit 1
