"""
设计运行(run) 状态管理

每个用户提交的设计任务对应一个 run, 用 SQLite 记录:
  - 元信息(id, 状态, 开始/结束时间)
  - 事件流 (Agent 每次决策、每个工具的开始/结束)
  - 工具结果 (落到 runs/<id>/<tool_name>.json)

状态机:
  pending → running → done | failed | cancelled
"""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import config


# ═══════════════════════ DB 初始化 ═══════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,              -- pending/running/done/failed/cancelled
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL,
    form_data   TEXT NOT NULL,              -- 用户提交的原始表单(JSON)
    final_summary TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT NOT NULL,
    ts        REAL NOT NULL,
    kind      TEXT NOT NULL,                -- agent_think/tool_start/tool_done/tool_error/finish
    payload   TEXT NOT NULL,                -- JSON
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, ts);
"""


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(config.DB_PATH), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        # 一次写多语句
        for stmt in SCHEMA.strip().split(";"):
            if stmt.strip():
                conn.execute(stmt)
        yield conn
    finally:
        conn.close()


# ═══════════════════════ Run 操作 ═══════════════════════
def create_run(form_data: dict) -> str:
    """创建新 run, 返回 run_id。"""
    rid = uuid.uuid4().hex[:12]
    with db() as c:
        c.execute("INSERT INTO runs (id, status, created_at, form_data) VALUES (?, ?, ?, ?)",
                  (rid, "pending", time.time(), json.dumps(form_data, ensure_ascii=False)))
    # 建对应的输出目录
    (config.RUNS_DIR / rid).mkdir(exist_ok=True)
    return rid


def update_run(run_id: str, **fields):
    if not fields:
        return
    keys = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [run_id]
    with db() as c:
        c.execute(f"UPDATE runs SET {keys} WHERE id=?", vals)


def get_run(run_id: str) -> Optional[dict]:
    with db() as c:
        row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(limit: int = 50) -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT id, status, created_at, finished_at FROM runs "
                         "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════ 事件操作 ═══════════════════════
def log_event(run_id: str, kind: str, payload: dict):
    """记录一个事件 (会被前端 SSE 流读取)。"""
    with db() as c:
        c.execute("INSERT INTO events (run_id, ts, kind, payload) VALUES (?, ?, ?, ?)",
                  (run_id, time.time(), kind,
                   json.dumps(payload, ensure_ascii=False, default=str)))


def get_events(run_id: str, after_id: int = 0) -> list[dict]:
    """读取 run 的所有事件 (after_id 后的, 用于 SSE 增量推送)。"""
    with db() as c:
        rows = c.execute("SELECT id, ts, kind, payload FROM events "
                         "WHERE run_id=? AND id>? ORDER BY id",
                         (run_id, after_id)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"])
        except Exception:
            pass
        out.append(d)
    return out


# ═══════════════════════ 工具结果存取 ═══════════════════════
def save_tool_result(run_id: str, tool_name: str, result: dict):
    """工具结果落到 runs/<id>/<tool>.json"""
    rd = config.RUNS_DIR / run_id
    rd.mkdir(exist_ok=True)
    (rd / f"{tool_name}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8"
    )


def load_tool_result(run_id: str, tool_name: str) -> Optional[dict]:
    f = config.RUNS_DIR / run_id / f"{tool_name}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
