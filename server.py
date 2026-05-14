"""
飞机智能设计平台 L3 · FastAPI 后端

核心 API:
  POST /api/design/start          创建 run, 提交 Celery task, 返回 run_id
  GET  /api/design/{id}/status    查 run 状态
  GET  /api/design/{id}/stream    SSE 实时推事件流 (前端进度看板订阅)
  GET  /api/design/{id}/result    查最终结果 + 各工具产物列表
  GET  /api/design/{id}/file      下载 run 目录里的具体文件
  GET  /api/design/list           列出最近的 runs
  GET  /api/health                健康检查
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import runs
import auth
import chat_agent
from tasks import run_design_pipeline


# ═══════════════════════ App ═══════════════════════
app = FastAPI(title="Aircraft Design L3", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

INDEX_HTML   = config.PROJECT_DIR / "index.html"
LOGIN_HTML   = config.PROJECT_DIR / "login.html"
HISTORY_HTML = config.PROJECT_DIR / "history.html"
ADMIN_HTML   = config.PROJECT_DIR / "admin.html"

# 服务启动时间, 给后台显示用
SERVER_START_TS = time.time()


# ═══════════════════════ 认证 middleware ═══════════════════════
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """每个请求检查 cookie。白名单(/login, 健康检查, 静态文件)跳过"""
    path = request.url.path

    # 白名单
    if auth.is_whitelisted(path):
        return await call_next(request)

    # 检查 cookie
    token = request.cookies.get(auth.COOKIE_NAME)
    if not auth.check_session(token):
        # API 请求 → 401
        if path.startswith("/api/"):
            return JSONResponse({"error": "未登录", "redirect": "/login"}, status_code=401)
        # 页面请求 → 重定向到登录
        return RedirectResponse("/login", status_code=302)

    return await call_next(request)


# ═══════════════════════ 数据模型 ═══════════════════════
class StartRequest(BaseModel):
    aircraft_class: str = "electric-regional"
    seats:          int = 19
    range_km:       float = 500
    cruise_mach:    float = 0.35
    cruise_alt_m:   float = 3000
    max_wingspan_m: float = 17
    battery_kwh:    float = 0
    report_type:    str = "design"     # 报告类型: design / propulsion
    extra:          str = ""


# ═══════════════════════ 路由 ═══════════════════════
@app.get("/", response_class=HTMLResponse)
async def root():
    if INDEX_HTML.exists():
        return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>index.html 未找到</h1>")


# ═══════════════════════ 登录/登出 ═══════════════════════
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    if LOGIN_HTML.exists():
        return HTMLResponse(LOGIN_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>login.html 未找到</h1>")


@app.post("/login")
async def login_submit(password: str = Form(...)):
    if auth.verify_password(password):
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(
            auth.COOKIE_NAME,
            auth.make_session_token(),
            httponly=True,
            max_age=auth.COOKIE_MAXAGE,
            samesite="lax",
        )
        return resp
    return RedirectResponse("/login?error=1", status_code=302)


@app.post("/logout")
async def logout_submit():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


# ═══════════════════════ 历史记录页 ═══════════════════════
@app.get("/history", response_class=HTMLResponse)
async def history_page():
    if HISTORY_HTML.exists():
        return HTMLResponse(HISTORY_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>history.html 未找到</h1>")


# ═══════════════════════ 管理后台页 ═══════════════════════
@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    if ADMIN_HTML.exists():
        return HTMLResponse(ADMIN_HTML.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>admin.html 未找到</h1>")


@app.get("/api/admin/status")
async def admin_status():
    """系统状态: Redis/Celery worker/磁盘/任务计数"""
    out = {}

    # Redis
    try:
        import redis
        r = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT,
                        db=config.REDIS_DB, socket_timeout=2)
        r.ping()
        out["redis_ok"] = True
        out["redis_port"] = config.REDIS_PORT
        try:
            out["queue_length"] = r.llen("celery")
        except Exception:
            out["queue_length"] = None
    except Exception:
        out["redis_ok"] = False
        out["redis_port"] = config.REDIS_PORT
        out["queue_length"] = None

    # Celery worker 进程数 (ps + grep)
    try:
        proc = subprocess.run(
            ["pgrep", "-f", "celery -A tasks worker"],
            capture_output=True, text=True, timeout=5,
        )
        pids = [p for p in proc.stdout.strip().split("\n") if p]
        out["celery_workers"] = len(pids)
    except Exception:
        out["celery_workers"] = -1

    # 运行中任务数 + 历史 run 数
    try:
        all_runs = runs.list_runs(limit=1000)
        out["total_runs"] = len(all_runs)
        out["running_count"] = sum(1 for r in all_runs if r["status"] == "running")
    except Exception:
        out["total_runs"] = 0
        out["running_count"] = 0

    # 磁盘
    try:
        total, used, free = shutil.disk_usage(str(config.RUNS_DIR))
        out["disk_usage"] = f"{used // (1024**3)} GB / {total // (1024**3)} GB"
    except Exception:
        out["disk_usage"] = "-"

    # runs/ 目录大小
    try:
        proc = subprocess.run(
            ["du", "-sh", str(config.RUNS_DIR)],
            capture_output=True, text=True, timeout=10,
        )
        out["runs_dir_size"] = proc.stdout.split("\t")[0] if proc.stdout else "-"
    except Exception:
        out["runs_dir_size"] = "-"

    # db 大小
    try:
        if config.DB_PATH.exists():
            sz = config.DB_PATH.stat().st_size
            out["db_size"] = f"{sz // 1024} KB" if sz < 1024**2 else f"{sz // (1024**2)} MB"
        else:
            out["db_size"] = "-"
    except Exception:
        out["db_size"] = "-"

    # LLM model + 启动时间
    out["llm_model"] = getattr(config, "LLM_MODEL", "-")
    uptime_s = int(time.time() - SERVER_START_TS)
    if uptime_s < 3600:
        out["server_uptime"] = f"{uptime_s // 60} 分钟"
    else:
        out["server_uptime"] = f"{uptime_s // 3600} 小时 {(uptime_s % 3600) // 60} 分钟"

    return out


@app.delete("/api/admin/runs/{run_id}")
async def admin_delete_run(run_id: str):
    """删除 run: db 记录 + runs/<run_id> 目录"""
    # 防止路径注入
    if "/" in run_id or ".." in run_id:
        raise HTTPException(400, "非法 run_id")

    run = runs.get_run(run_id)
    if not run:
        raise HTTPException(404, "run 不存在")

    # 删 runs/ 目录
    run_dir = config.RUNS_DIR / run_id
    if run_dir.exists():
        shutil.rmtree(str(run_dir), ignore_errors=True)

    # 删 db 记录
    try:
        with runs.db() as conn:
            conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM tool_results WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            conn.commit()
    except Exception as e:
        raise HTTPException(500, f"DB 删除失败: {e}")

    return {"ok": True, "run_id": run_id}


@app.get("/flow_chart.jpg")
async def flow_chart_image():
    """返回设计架构流程图 (CE-25A drawio 导出版)"""
    f = config.PROJECT_DIR / "flow_chart.jpg"
    if not f.exists():
        raise HTTPException(404, "flow_chart.jpg 不存在")
    return FileResponse(str(f), media_type="image/jpeg")


@app.get("/api/health")
async def health():
    skill_loaded = config.SKILL_MD_PATH.exists()
    skill_chars  = len(config.SKILL_MD_PATH.read_text(encoding="utf-8")) if skill_loaded else 0

    # 测 Redis
    redis_ok = False
    try:
        import redis
        r = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, socket_timeout=2)
        redis_ok = r.ping()
    except Exception:
        pass

    return {
        "status":          "ok",
        "skill_md_loaded": skill_loaded,
        "skill_md_chars":  skill_chars,
        "model":           config.LLM_MODEL,
        "redis_url":       config.REDIS_URL,
        "redis_ok":        redis_ok,
        "runs_count":      len(runs.list_runs(limit=1000)),
    }


@app.post("/api/chat/turn")
async def chat_turn(request: Request):
    """
    对话式需求收集 - 单轮对话
    输入: { history: [{role, content}, ...] }
    输出: { reply, extracted_params, is_ready, missing_fields }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Body 不是合法 JSON")

    history = body.get("history", [])
    if not isinstance(history, list):
        raise HTTPException(400, "history 必须是数组")

    # 安全限制: 历史最长 50 条
    if len(history) > 50:
        history = history[-50:]

    # 字段格式校验
    for i, msg in enumerate(history):
        if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
            raise HTTPException(400, f"history[{i}] 格式错误")
        if msg["role"] not in ("user", "assistant"):
            raise HTTPException(400, f"history[{i}].role 必须是 user 或 assistant")

    result = chat_agent.chat_turn(history)
    return result


@app.post("/api/design/start")
async def start_design(req: StartRequest):
    """创建 run + 提交 Celery 任务"""
    form = req.dict()
    run_id = runs.create_run(form)

    # 提交到 Celery
    try:
        run_design_pipeline.delay(run_id)
    except Exception as e:
        runs.update_run(run_id, status="failed", error=f"提交任务失败: {e}")
        raise HTTPException(500, f"提交任务失败: {e}")

    return {"run_id": run_id, "status": "pending"}


@app.get("/api/design/{run_id}/status")
async def get_status(run_id: str):
    run = runs.get_run(run_id)
    if not run:
        raise HTTPException(404, "run 不存在")
    return run


@app.get("/api/design/{run_id}/stream")
async def stream_events(run_id: str):
    """SSE 推事件流 - 前端订阅这个看实时进度。"""
    run = runs.get_run(run_id)
    if not run:
        raise HTTPException(404, "run 不存在")

    async def event_generator():
        last_id = 0
        idle_count = 0
        while True:
            evs = runs.get_events(run_id, after_id=last_id)
            if evs:
                for e in evs:
                    last_id = e["id"]
                    yield f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
                idle_count = 0
            else:
                idle_count += 1

            # 检查 run 是否已结束
            r = runs.get_run(run_id)
            if r and r["status"] in ("done", "failed", "cancelled"):
                # 再发最后一波事件确保不漏
                final_evs = runs.get_events(run_id, after_id=last_id)
                for e in final_evs:
                    yield f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
                yield f"data: {json.dumps({'kind':'__end__','status':r['status']})}\n\n"
                return

            # 太久没事件就发心跳
            if idle_count > 30:
                yield f": heartbeat\n\n"
                idle_count = 0

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/design/{run_id}/result")
async def get_result(run_id: str):
    run = runs.get_run(run_id)
    if not run:
        raise HTTPException(404, "run 不存在")

    # 列出 runs/<id>/ 里所有产物文件
    rd = config.RUNS_DIR / run_id
    artifacts = []
    if rd.exists():
        for f in sorted(rd.iterdir()):
            artifacts.append({
                "name": f.name,
                "size": f.stat().st_size,
                "url":  f"/api/design/{run_id}/file?name={f.name}",
            })

    # 把每个工具的 JSON 结果嵌入返回 (前端可以直接显示)
    tool_results = {}
    for f in (rd.glob("tool_*.json") if rd.exists() else []):
        try:
            tool_results[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "run":          run,
        "artifacts":    artifacts,
        "tool_results": tool_results,
    }


@app.get("/api/design/{run_id}/file")
async def get_file(run_id: str, name: str = Query(...)):
    """下载 run 目录里的某个文件。"""
    rd = config.RUNS_DIR / run_id
    f = rd / name
    if not f.exists() or not f.is_file():
        raise HTTPException(404, "文件不存在")
    # 防止路径穿越
    if not str(f.resolve()).startswith(str(rd.resolve())):
        raise HTTPException(403, "非法路径")
    return FileResponse(str(f))


@app.get("/api/design/list")
async def list_runs(limit: int = 20):
    return runs.list_runs(limit=limit)


# ═══════════════════════ 启动 ═══════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=config.SERVER_HOST)
    parser.add_argument("--port", type=int, default=config.SERVER_PORT)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"\n🚀 飞机智能设计平台 L3")
    print(f"   监听: http://{args.host}:{args.port}")
    print(f"   Redis: {config.REDIS_URL}")
    print(f"   skill.md: {'已加载' if config.SKILL_MD_PATH.exists() else '未加载'}")
    print(f"   模型: {config.LLM_MODEL}")
    print()

    import uvicorn
    if args.reload:
        uvicorn.run("server:app", host=args.host, port=args.port, reload=True)
    else:
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
