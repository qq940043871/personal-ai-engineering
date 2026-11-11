#!/usr/bin/env bash
# 一键启动脚本（Git Bash / Linux / macOS）
set -uo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo "  郑州发布 - 招聘信息监听流水线"
echo "============================================================"

PY=""
for cand in "./.venv/Scripts/python.exe" "./.venv/bin/python" \
            "/c/Users/qq940/anaconda3/python.exe" \
            "$(command -v python3 2>/dev/null)" "$(command -v python 2>/dev/null)"; do
  if [ -n "$cand" ] && [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "[错误] 没找到 Python，请安装或修改本脚本里的候选路径。"
  exit 1
fi
echo "[1/4] 使用解释器: $PY"

echo "[2/4] 检查依赖..."
if ! "$PY" -c "import feedparser,requests,bs4,yaml" 2>/dev/null; then
  echo "      缺少依赖，正在安装（首次运行会慢一点）..."
  "$PY" -m pip install -r requirements.txt || { echo "[错误] 依赖安装失败"; exit 1; }
else
  echo "      依赖齐全"
fi

echo "[3/4] 读取配置..."
[ -f config.yaml ] || { echo "[错误] 找不到 config.yaml"; exit 1; }

echo "[4/4] 执行流水线..."
echo
"$PY" -m src.pipeline
RC=$?

echo
if [ "$RC" -eq 0 ]; then
  echo "============================================================"
  echo "  完成！日报已生成到 out/ 目录"
  echo "============================================================"
  ls -t out/jobs_*.html 2>/dev/null | head -1
else
  echo "[失败] 流水线返回错误码 $RC"
fi
exit $RC
