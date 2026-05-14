#!/bin/bash
# L3 飞机智能设计平台 · 一键启动
# 
# 启动两个进程:
#   1. Celery worker (跑设计任务)
#   2. FastAPI server (Web 前端 + API)
# 
# 都用 nohup 后台跑, 日志写到 logs/

set -e

cd "$(dirname "$0")"

mkdir -p logs

# ─────── 检查 Redis ───────
if [ -f redis_port.txt ]; then
    PORT=$(cat redis_port.txt)
    if ! redis-cli -p "$PORT" ping 2>&1 | grep -q PONG; then
        echo "❌ Redis 在 $PORT 端口上没响应, 请先跑: bash fix_redis.sh"
        exit 1
    fi
    echo "✓ Redis OK (端口 $PORT)"
else
    echo "❌ 找不到 redis_port.txt, 请先跑: bash fix_redis.sh"
    exit 1
fi

# ─────── 检查 skill.md ───────
if [ ! -f skill.md ]; then
    echo "⚠ skill.md 不存在, AI 将只能用通用知识"
    echo "  把 skill.md 放到当前目录可以让 AI 用平台专属知识"
fi

# ─────── 停掉之前的 worker / server ───────
echo "▶ 停掉之前的 worker / server..."
pkill -f "celery -A tasks" 2>/dev/null || true
pkill -f "python.*server.py" 2>/dev/null || true
sleep 1

# ─────── 启动 Celery worker ───────
echo "▶ 启动 Celery worker..."
nohup celery -A tasks worker \
    --loglevel=INFO \
    --concurrency=2 \
    --pool=prefork \
    > logs/celery.log 2>&1 &
WORKER_PID=$!
echo "  worker PID: $WORKER_PID"
sleep 2

# 验证 worker 起来了
if ! ps -p $WORKER_PID > /dev/null; then
    echo "  ❌ Celery worker 启动失败, 看 logs/celery.log:"
    tail -20 logs/celery.log
    exit 1
fi

# ─────── 启动 FastAPI server ───────
echo "▶ 启动 FastAPI server..."
nohup python -u server.py > logs/server.log 2>&1 &
SERVER_PID=$!
echo "  server PID: $SERVER_PID"
sleep 2

if ! ps -p $SERVER_PID > /dev/null; then
    echo "  ❌ Server 启动失败, 看 logs/server.log:"
    tail -20 logs/server.log
    exit 1
fi

# 测试健康检查
sleep 1
HEALTH=$(curl -sf http://127.0.0.1:8881/api/health 2>&1 || echo "FAIL")
if [[ "$HEALTH" == *"\"status\":\"ok\""* ]]; then
    echo "  ✓ /api/health → ok"
else
    echo "  ⚠ /api/health 异常: $HEALTH"
fi
echo ""

# ─────── 写 PID 文件方便停止 ───────
echo "$WORKER_PID" > .worker.pid
echo "$SERVER_PID" > .server.pid

echo "════════════════════════════════════════════════════════════"
echo "  ✅ L3 平台已启动"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  访问: http://10.90.111.114:8881"
echo ""
echo "  日志:"
echo "    tail -f logs/server.log    # FastAPI 后端"
echo "    tail -f logs/celery.log    # Celery worker"
echo ""
echo "  停止: bash stop.sh"
echo ""
