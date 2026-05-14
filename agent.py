"""
LLM Agent · 设计流程编排器

核心职责:
  - 加载 skill.md 作为 system prompt
  - 读取 5 个工具的 schema, 注册成 OpenAI tools
  - 接收用户需求, 让 LLM 决定调哪个工具、用什么参数
  - 收到工具结果后, 决定下一步(继续调下一个工具 / 总结结束)
  - 返回完整的"思考-行动-观察"轨迹

设计哲学:
  Agent 不直接执行工具, 而是返回"应该调什么工具"。
  真正的执行由 Celery worker 完成, 这样 Agent 的决策可以独立测试。
"""

import json
import requests
from pathlib import Path
from typing import Iterator

import config
from tools import get_all_schemas, TOOL_REGISTRY


# ═══════════════════════ 加载 skill.md ═══════════════════════
def _load_skill() -> str:
    if not config.SKILL_MD_PATH.exists():
        return "(skill.md 未加载, Agent 只能用通用知识)"
    return config.SKILL_MD_PATH.read_text(encoding="utf-8")


SKILL_KNOWLEDGE = _load_skill()


# ═══════════════════════ System Prompt ═══════════════════════
def make_system_prompt() -> str:
    return f"""你是飞机智能设计平台的 Agent, 任务是把用户的设计需求自动跑完一个完整设计流程。

平台知识 (skill.md):
============================================================
{SKILL_KNOWLEDGE}
============================================================

你有 {len(TOOL_REGISTRY)} 个工具可用, 它们应当按以下顺序调用:
1. tool_requirements   - 处理需求, 输出 Vehicle 配置 (必须第一个调用)
2. tool_aerodynamics   - 用 SUAVE 算升阻比 (依赖 1 的输出)
3. tool_optimize       - 调翼展/扭转角找最优配置 (依赖 1, 2)
4. tool_weights        - 估算各部件重量 (依赖 1)
5. tool_propulsion     - 电池/电机匹配, 任务剖面 (依赖 1, 4)

工作流程:
  - 每一步只调用一个工具
  - 工具返回结果后, 你查看 summary 判断成败
  - 失败就分析原因, 决定是重试、跳过、还是终止
  - 全部 5 步走完, 输出最终设计总结

CE-25A 是电动支线机, 应选 aircraft_class='electric-regional'。
"""


# ═══════════════════════ LLM 调用 ═══════════════════════
def call_llm(messages: list, tools: list = None, max_tokens: int = 3000) -> dict:
    """调一次 LLM, 返回完整 message 对象 (含 tool_calls)。"""
    payload = {
        "model":       config.LLM_MODEL,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": 0.4,
        "top_p":       0.95,
    }
    if tools:
        payload["tools"]       = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {config.LLM_API_KEY}",
    }
    resp = requests.post(config.LLM_API_URL, headers=headers, json=payload,
                         timeout=config.LLM_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


# ═══════════════════════ Agent 主循环 ═══════════════════════
def plan_next_step(history: list, max_iterations: int = 10) -> dict:
    """根据当前历史, 决定下一步动作。

    返回:
      {
        "action": "tool_call" | "finish",
        "tool_name": "tool_xxx",          (action=tool_call 时)
        "tool_args": {...},               (action=tool_call 时)
        "thinking": "...",                LLM 的解释
        "final_summary": "..."            (action=finish 时)
      }
    """
    messages = [{"role": "system", "content": make_system_prompt()}] + history
    tools = get_all_schemas()

    msg = call_llm(messages, tools=tools)

    # 处理 tool_calls (LLM 决定调用工具)
    tool_calls = msg.get("tool_calls") or []
    if tool_calls:
        tc = tool_calls[0]   # 一次只取第一个工具调用
        fn = tc.get("function", {})
        name = fn.get("name", "")
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except Exception:
            args = {}
        return {
            "action":     "tool_call",
            "tool_name":  name,
            "tool_args":  args,
            "thinking":   msg.get("content", "") or "",
            "tool_call_id": tc.get("id", ""),
        }

    # 没有工具调用 → LLM 认为流程结束
    return {
        "action":        "finish",
        "thinking":      msg.get("content", "") or "",
        "final_summary": msg.get("content", "") or "",
    }


def make_tool_observation(tool_name: str, tool_call_id: str, result: dict) -> dict:
    """把工具执行结果包装成 LLM 能理解的 message。"""
    # 截短大数据, 避免占满上下文
    obs_data = {
        "status":  result.get("status"),
        "summary": result.get("summary"),
        "data":    result.get("data"),
    }
    if result.get("error"):
        obs_data["error"] = result["error"]

    content = json.dumps(obs_data, ensure_ascii=False, indent=2)
    if len(content) > 8000:
        content = content[:8000] + "\n... (truncated)"

    return {
        "role":         "tool",
        "tool_call_id": tool_call_id,
        "name":         tool_name,
        "content":      content,
    }


def build_user_request(form_data: dict) -> str:
    """把前端表单数据转成 LLM 第一条 user message。"""
    parts = ["请帮我跑完整套设计流程。需求如下:\n"]
    for k, v in form_data.items():
        if v not in (None, "", 0):
            parts.append(f"- {k}: {v}")
    parts.append("\n请按顺序调用 5 个工具完成设计, 每步告诉我进展。")
    return "\n".join(parts)
