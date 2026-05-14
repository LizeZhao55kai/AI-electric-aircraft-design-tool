"""
Celery 任务定义

一个设计 run 是一个 Celery task (run_design_pipeline)。
task 内部跑 Agent 主循环:
  while not done and step < MAX_STEPS:
      action = agent.plan_next_step(history)
      if action is tool_call:
          result = execute_tool(...)
          history.append(result)
      else:
          break
"""

import json
import time
from pathlib import Path

from celery import Celery

import config
import runs
import agent
from tools import get_tool, TOOL_REGISTRY

# 必须 import 工具模块, 触发 @register 装饰器
import tools.tool_requirements        # noqa: F401
import tools.tool_aerodynamics        # noqa: F401
import tools.tool_optimize            # noqa: F401
import tools.tool_weights             # noqa: F401
import tools.tool_propulsion          # noqa: F401
import tools.tool_generate_report     # noqa: F401


# ═══════════════════════ Celery 应用 ═══════════════════════
app = Celery(
    "aidesign_l3",
    broker  = config.CELERY_BROKER_URL,
    backend = config.CELERY_RESULT_URL,
)
app.conf.update(
    task_time_limit       = config.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit  = config.CELERY_TASK_TIME_LIMIT - 30,
    worker_prefetch_multiplier = 1,
    task_acks_late        = True,
)


MAX_AGENT_STEPS = 12   # Agent 最多决策 12 次, 防止死循环


# ═══════════════════════ 主任务 ═══════════════════════
@app.task(name="run_design_pipeline", bind=True)
def run_design_pipeline(self, run_id: str):
    """完整设计流水线 - Agent 自主调度。"""
    run = runs.get_run(run_id)
    if not run:
        raise ValueError(f"找不到 run {run_id}")

    runs.update_run(run_id, status="running", started_at=time.time())
    runs.log_event(run_id, "pipeline_start", {
        "available_tools": list(TOOL_REGISTRY.keys()),
    })

    form_data = json.loads(run["form_data"])

    # 构造 Agent 对话历史
    history = [
        {"role": "user", "content": agent.build_user_request(form_data)},
    ]

    final_summary = ""
    error_msg = None

    try:
        for step in range(MAX_AGENT_STEPS):
            # ── 1. Agent 决策 ──
            runs.log_event(run_id, "agent_thinking", {"step": step + 1})
            decision = agent.plan_next_step(history)

            runs.log_event(run_id, "agent_decision", {
                "step":     step + 1,
                "action":   decision["action"],
                "thinking": decision.get("thinking", "")[:500],
                "tool":     decision.get("tool_name", ""),
                "args":     decision.get("tool_args", {}),
            })

            # ── 2. 决策结果分发 ──
            if decision["action"] == "finish":
                # ★ 兜底: 检查报告生成是否已跑过, 没跑就强制跑一次
                _run_dir = config.RUNS_DIR / run_id
                report_already_done = (_run_dir / "tool_generate_report.json").exists()
                computation_done = all(
                    (_run_dir / f"{t}.json").exists()
                    for t in ["tool_requirements", "tool_aerodynamics",
                              "tool_optimize", "tool_weights", "tool_propulsion"]
                )
                if computation_done and not report_already_done:
                    # 5 个计算工具齐了但 LLM 漏了报告生成 - 强制兜底
                    # 从 form_data 取 report_type, 不指定时默认 design
                    fb_report_type = form_data.get("report_type", "design")
                    runs.log_event(run_id, "agent_fallback", {
                        "reason": "Agent 选择 finish 但漏了 tool_generate_report, 强制兜底",
                        "report_type": fb_report_type,
                    })
                    fb_name = "tool_generate_report"
                    fb_args = {"report_type": fb_report_type}
                    runs.log_event(run_id, "tool_start", {"tool": fb_name, "args": fb_args})
                    try:
                        fb_tool = get_tool(fb_name)
                        fb_result = fb_tool.execute(fb_args, _run_dir)
                        runs.save_tool_result(run_id, fb_name, fb_result)
                        runs.log_event(run_id, "tool_done", {
                            "tool":    fb_name,
                            "status":  fb_result["status"],
                            "summary": fb_result.get("summary", ""),
                            "elapsed": fb_result.get("elapsed_s", 0),
                        })
                    except Exception as fb_err:
                        runs.log_event(run_id, "tool_error", {
                            "tool": fb_name, "error": str(fb_err),
                        })

                final_summary = decision.get("final_summary", "")
                runs.log_event(run_id, "pipeline_finish", {"summary": final_summary})
                break

            # 工具调用
            tool_name = decision["tool_name"]
            tool_args = decision["tool_args"]
            tool_call_id = decision["tool_call_id"]

            # 把 assistant 的 tool_call 写回 history (LLM 协议要求)
            history.append({
                "role":    "assistant",
                "content": decision.get("thinking", ""),
                "tool_calls": [{
                    "id":   tool_call_id,
                    "type": "function",
                    "function": {
                        "name":      tool_name,
                        "arguments": json.dumps(tool_args, ensure_ascii=False),
                    },
                }],
            })

            # ── 3. 执行工具 ──
            runs.log_event(run_id, "tool_start", {
                "tool": tool_name, "args": tool_args,
            })
            try:
                tool = get_tool(tool_name)
                result = tool.execute(tool_args, config.RUNS_DIR / run_id)
                runs.save_tool_result(run_id, tool_name, result)
                runs.log_event(run_id, "tool_done", {
                    "tool":    tool_name,
                    "status":  result["status"],
                    "summary": result["summary"],
                    "elapsed": result.get("elapsed_s", 0),
                })
            except Exception as e:
                result = {"status": "error", "summary": str(e),
                          "data": {}, "error": str(e)}
                runs.log_event(run_id, "tool_error", {
                    "tool": tool_name, "error": str(e),
                })

            # 把工具观察结果写回 history
            history.append(agent.make_tool_observation(tool_name, tool_call_id, result))

        else:
            # for 循环跑满 MAX_AGENT_STEPS 没 break
            error_msg = f"Agent 跑了 {MAX_AGENT_STEPS} 步还没结束, 强制终止"
            runs.log_event(run_id, "agent_timeout", {"max_steps": MAX_AGENT_STEPS})

    except Exception as e:
        error_msg = f"Pipeline 异常: {e}"
        runs.log_event(run_id, "pipeline_error", {"error": str(e)})

    # ── 收尾 ──
    final_status = "failed" if error_msg else "done"
    runs.update_run(run_id,
                    status        = final_status,
                    finished_at   = time.time(),
                    final_summary = final_summary,
                    error         = error_msg)

    return {
        "run_id":  run_id,
        "status":  final_status,
        "summary": final_summary,
        "error":   error_msg,
    }
