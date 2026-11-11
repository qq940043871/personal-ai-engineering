#!/usr/bin/env bash
# ================================================================
#  OpenCode Go -> WorkBuddy 代理启动器（Git Bash 版）
#
#  如果双击 start_proxy.bat 有问题，用这个。
#  用法：在 Git Bash 里执行  bash start_proxy.sh
# ================================================================

set -e

KEY="oc_sk_de841b233e97_L3wBR5Jm582tRbUmJFRGLhn5AO7LboN3"
PORT="${LUNA_PROXY_PORT:-8787}"
PY="C:/Users/qq940/.workbuddy/binaries/python/versions/3.13.12/python.exe"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export OPENCODE_API_KEY="$KEY"
export LUNA_PROXY_PORT="$PORT"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "=============================================================="
echo "  Starting OpenCode Go proxy (Git Bash launcher)"
echo "  Dir  : $DIR"
echo "  Port : $PORT"
echo "  Keep this window OPEN. Press Ctrl+C to stop."
echo "=============================================================="

cd "$DIR"
exec "$PY" -u oc_session_proxy.py
