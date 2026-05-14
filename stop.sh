#!/bin/bash
# 停掉 L3 平台的所有进程

cd "$(dirname "$0")"

echo "▶ 停掉 Celery worker..."
pkill -f "celery -A tasks" 2>/dev/null && echo "  ✓ 已停" || echo "  (没在跑)"

echo "▶ 停掉 FastAPI server..."
pkill -f "python.*server.py" 2>/dev/null && echo "  ✓ 已停" || echo "  (没在跑)"

rm -f .worker.pid .server.pid

echo ""
echo "L3 平台已全部停止 (Redis 不会停)"
