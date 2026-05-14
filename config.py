"""
飞机智能设计平台 L3 · 全局配置
所有路径、端口、模型 API 信息集中在此, 改动只需要这一个文件。
"""

import os
from pathlib import Path

# ═══════════════════════ 路径配置 ═══════════════════════
PROJECT_DIR = Path(__file__).resolve().parent
RUNS_DIR    = PROJECT_DIR / "runs"          # 每个设计 run 的输出目录
LOGS_DIR    = PROJECT_DIR / "logs"
DB_PATH     = PROJECT_DIR / "runs.db"       # SQLite 进度库

RUNS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ═══════════════════════ 知识源 ═══════════════════════
# 启动时一次性加载, 注入 LLM system prompt
SKILL_MD_PATH = PROJECT_DIR / "skill.md"     # 把已有的 skill.md 放在项目根

# ═══════════════════════ Redis (Celery broker) ═══════════════════════
REDIS_HOST = "127.0.0.1"

# Redis 端口从 redis_port.txt 自动读, fallback 8011
def _read_redis_port() -> int:
    port_file = PROJECT_DIR / "redis_port.txt"
    if port_file.exists():
        try:
            return int(port_file.read_text().strip())
        except Exception:
            pass
    return 8011    # 兜底: 当时 fix_redis.sh 找到的端口

REDIS_PORT = _read_redis_port()
REDIS_DB   = 0
REDIS_URL  = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# Celery
CELERY_BROKER_URL  = REDIS_URL
CELERY_RESULT_URL  = REDIS_URL
CELERY_TASK_TIME_LIMIT = 1800                # 单个 task 硬超时 30 分钟

# ═══════════════════════ Web 后端 ═══════════════════════
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8881                           # 管理员给你的对外端口

# ═══════════════════════ LLM API ═══════════════════════
LLM_API_URL = "http://10.90.111.114:8509/v1/chat/completions"
LLM_API_KEY = "sk-team-b2d6c8e1a5f9d3b7"
LLM_MODEL   = "deepseek-v4-flash"            # minimax 已停用, 换成 deepseek
LLM_TIMEOUT = 180                            # 秒

# ═══════════════════════ SUAVE ═══════════════════════
# 跑 SUAVE 需要的 conda 环境名(诊断时确认是 suave-py310)
SUAVE_CONDA_ENV = "suave-py310"
SUAVE_PYTHON    = f"/root/miniconda3/envs/{SUAVE_CONDA_ENV}/bin/python"

# ═══════════════════════ 设计流程定义 ═══════════════════════
# 5 个工具按顺序执行, 每个工具的元信息让 Agent 知道何时调用
DESIGN_PIPELINE = [
    {
        "stage":    "requirements",
        "tool":     "tool_requirements",
        "name":     "需求处理",
        "desc":     "校验输入参数, 创建 SUAVE Vehicle 对象",
        "timeout":  60,
    },
    {
        "stage":    "aerodynamics",
        "tool":     "tool_aerodynamics",
        "name":     "气动分析",
        "desc":     "用 SUAVE 经验公式算升阻比、阻力极曲线",
        "timeout":  300,
    },
    {
        "stage":    "optimize",
        "tool":     "tool_optimize",
        "name":     "气动优化",
        "desc":     "调翼展/扭转角, 找最小阻力配置",
        "timeout":  900,
    },
    {
        "stage":    "weights",
        "tool":     "tool_weights",
        "name":     "结构重量估算",
        "desc":     "用 Roskam/Raymer 经验公式算各部件重量",
        "timeout":  60,
    },
    {
        "stage":    "propulsion",
        "tool":     "tool_propulsion",
        "name":     "电推进任务分析",
        "desc":     "电池-电机匹配, 跑任务剖面算续航",
        "timeout":  300,
    },
]
