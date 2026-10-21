#!/usr/bin/env bash
# Practice-mode server for UX testing (never touches a cluster): http://127.0.0.1:${1:-8791}
cd "$(dirname "$0")/.." || exit
# its own data directory: the practice server never reads the kubeconfigs under ./data
mkdir -p data/practice
ACADEMY_CLUSTER=off ACADEMY_DATA_DIR="$PWD/data/practice" nohup .venv/bin/python -m uvicorn academy.main:app --app-dir backend --host 127.0.0.1 --port "${1:-8791}" --log-level warning >>data/practice-server.log 2>&1 &
echo $! > data/practice-server.pid
for _ in $(seq 40); do curl -fsS "http://127.0.0.1:${1:-8791}/healthz" -o /dev/null 2>/dev/null && { echo "practice server on ${1:-8791} (pid $(cat data/practice-server.pid))"; exit 0; }; sleep 0.25; done
echo "did not start; see data/practice-server.log"; exit 1
