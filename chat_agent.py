"""
对话式需求收集 Agent
让 LLM 通过自然对话方式收集飞机设计的 7 个必填字段, 同时
持续输出结构化的 extracted_params 供前端实时显示。

无状态: 每次调用传入完整 history, 不在服务端存 session。
"""

import json
import re
from typing import Dict, List

import requests

import config


# ────────────────────────────────────────────────
# 字段定义
# ────────────────────────────────────────────────
REQUIRED_FIELDS = {
    "aircraft_class":  "飞机类型 (electric-regional 电动支线 / hybrid 混合动力 / conventional 常规)",
    "seats":           "座位数 (整数, 比如 9 / 19 / 30)",
    "range_km":        "设计航程 (公里, 比如 500)",
    "cruise_mach":     "巡航马赫数 (0.2-0.85, 比如 0.35 表示亚音速)",
    "cruise_alt_m":    "巡航高度 (米, 比如 3000)",
    "max_wingspan_m":  "最大翼展 (米, 受机场跑道宽度限制)",
    "battery_kwh":     "电池容量 (kWh, electric-regional 必填; 其他类型可填 0)",
}

OPTIONAL_FIELDS = {
    "extra":        "其他特殊要求 (文字描述, 比如'重视续航'/'兼顾货运'等)",
    "report_type":  "报告类型 (design 总体设计 / propulsion 电推进专题, 默认 design)",
}


# ────────────────────────────────────────────────
# 系统提示词
# ────────────────────────────────────────────────
SYSTEM_PROMPT = """你是「CE-25A 飞机智能设计平台」的需求收集助手, 任务是通过亲切自然的对话, 收集用户对飞机概念设计的需求参数。

【必须收集的字段】
- aircraft_class: 飞机类型, 取值之一: "electric-regional" / "hybrid" / "conventional"
- seats: 座位数 (整数)
- range_km: 设计航程, 单位 km
- cruise_mach: 巡航马赫数 (0.2-0.85)
- cruise_alt_m: 巡航高度, 单位 m
- max_wingspan_m: 最大翼展, 单位 m
- battery_kwh: 电池容量, 单位 kWh (electric-regional 必填; 其他类型用 0)

【对话风格 · 必须遵守】
1. 友好简洁, 像同事聊天那样, 不要像填表
2. 每次只问 1-2 个字段, 别一次问 7 个吓退用户
3. 不要把字段名 (例如 "cruise_mach") 直接告诉用户, 用人话:
   • cruise_mach → "巡航速度" (说"大概 0.35 马赫, 也就是低速亚音速")
   • max_wingspan_m → "翼展上限" (说"机场跑道一般能容纳多大的翼展")
   • battery_kwh → "电池容量"
4. 用户回答含糊时, 主动给典型推荐值, 让用户确认或修改:
   • "19 座支线飞机" → "建议航程 500 km, 巡航 0.35 马赫, 高度 3000 m, 翼展上限 17 m, 你看可以吗?"
5. 用户用模糊语言时主动澄清:
   • "中等大小" → "大概是多少座?" 或给几个选项让用户挑
6. 全部字段收齐后, 用 2-3 句简短总结所有参数, 询问"信息齐了, 可以开始 AI 设计吗?"
7. 用户说"开始/可以/好的/没问题/启动"等确认词时, 把 is_ready 设为 true

【输出格式 · 极其重要, 必须严格遵守】

★★★ 你的每一次回复, 整个内容必须是一个纯 JSON 对象, 不能包含任何其他东西:
  ✗ 不要 markdown 代码块 (不要 ```json 或 ```)
  ✗ 不要在 JSON 前后加任何说明文字
  ✗ 不要把 JSON 包在引号里
  ✓ 直接以 { 开头, 以 } 结尾

JSON 结构必须是这样:
{
  "reply": "给用户看的对话内容 (中文, 友好, 1-3 句; 不要堆砌内容)",
  "extracted_params": {
    "字段名": 值
  },
  "is_ready": false,
  "missing_fields": ["字段名 1", "字段名 2"]
}

注意:
- extracted_params 只包含到目前为止从对话中"明确确认"的字段
- 用户没说的字段不要瞎填默认值, 等用户回答了再加进去
- missing_fields 是必填字段里还缺的, 按重要性排序
- is_ready=true 当且仅当所有必填字段都有值 + 用户明确说了"开始"

【首次对话】
打个招呼, 说一下你能干啥 (用 1-2 句, 别长), 然后问"你想做个什么样的飞机?"——这是个开放问题, 让用户先发散描述, 你再针对性追问。
"""


# ────────────────────────────────────────────────
# 主函数
# ────────────────────────────────────────────────
def chat_turn(history: List[Dict[str, str]]) -> Dict:
    """
    一轮对话.

    Args:
        history: 完整对话历史. 格式 [{"role": "user"/"assistant", "content": "..."}, ...]
                 注意: 不要把 system prompt 包进来, 这里会自动加。
                 首次对话时 history 可以是空 [], 或只有一条 user message。

    Returns:
        {
            "reply":            str,        # AI 回复内容
            "extracted_params": dict,       # 已提取的字段
            "is_ready":         bool,       # 是否可以开始设计
            "missing_fields":   list[str],  # 还缺的字段
        }
    """
    # 加 system prompt + 在末尾再追加一个提醒, 防止多轮对话后 LLM 忘了 JSON 格式
    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history
        + [{
            "role": "system",
            "content": "提醒: 你的下一条回复必须是纯 JSON 对象, 以 { 开头 } 结尾。不要 markdown 代码块。",
        }]
    )

    try:
        resp = requests.post(
            config.LLM_API_URL,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {config.LLM_API_KEY}",
            },
            json={
                "model":       config.LLM_MODEL,
                "messages":    messages,
                "temperature": 0.3,
                "top_p":       0.95,
                "max_tokens":  600,
            },
            timeout=getattr(config, "LLM_TIMEOUT", 30),
        )
        if resp.status_code != 200:
            # 把上游 LLM 的错误细节回传给前端, 帮调试
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text[:300]
            return {
                "reply":            f"(LLM 返回 {resp.status_code}: {err_body})",
                "extracted_params": {},
                "is_ready":         False,
                "missing_fields":   list(REQUIRED_FIELDS.keys()),
                "error":            f"HTTP {resp.status_code}",
            }
        data    = resp.json()
        content = data["choices"][0]["message"]["content"]
        print(f"[chat_agent] LLM raw: {content[:200]}", flush=True)
    except Exception as e:
        return {
            "reply":            f"(网络/解析错误: {e})",
            "extracted_params": {},
            "is_ready":         False,
            "missing_fields":   list(REQUIRED_FIELDS.keys()),
            "error":            str(e),
        }

    return _parse_response(content)


def _parse_response(content: str) -> Dict:
    """从 LLM 的回复里提取 JSON, 多种兜底"""
    # 1. 试直接解析
    parsed = _try_json(content)
    if parsed:
        return _normalize(parsed)

    # 2. 试去掉 markdown 代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        parsed = _try_json(m.group(1))
        if parsed:
            return _normalize(parsed)

    # 3. 试找第一个 { 到最后一个 }
    s = content.find("{")
    e = content.rfind("}")
    if s != -1 and e > s:
        parsed = _try_json(content[s:e + 1])
        if parsed:
            return _normalize(parsed)

    # 4. 全失败: 把原文当 reply
    return {
        "reply":            content,
        "extracted_params": {},
        "is_ready":         False,
        "missing_fields":   list(REQUIRED_FIELDS.keys()),
        "parse_error":      True,
    }


def _try_json(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None


def _normalize(parsed: dict) -> Dict:
    """标准化输出 (容忍字段名小写/拼写差异)"""
    out = {
        "reply":            str(parsed.get("reply", "")),
        "extracted_params": dict(parsed.get("extracted_params", {})),
        "is_ready":         bool(parsed.get("is_ready", False)),
        "missing_fields":   list(parsed.get("missing_fields", [])),
    }

    # 重算 missing_fields 防 LLM 给错
    extracted = out["extracted_params"]
    real_missing = [f for f in REQUIRED_FIELDS if f not in extracted]
    if real_missing:
        out["missing_fields"] = real_missing
        # 如果 LLM 自报 is_ready=True 但实际有缺, 修正
        if out["is_ready"]:
            out["is_ready"] = False

    return out
