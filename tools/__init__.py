"""
SUAVE 工具基类与通用功能

每个工具(需求/气动/优化/重量/电推进)都继承 BaseTool, 实现:
  - run(inputs, run_dir) -> outputs
  - tool_schema() -> dict (给 LLM 看的 OpenAI tool 格式)

工具的执行方式:
  Agent 决定调用哪个工具 → 通过 Celery 提交 task → worker 拉起子进程跑 SUAVE → 把结果以 JSON 写回 run_dir
"""

import json
import time
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ToolError(Exception):
    """工具执行失败"""
    pass


class BaseTool(ABC):
    """所有 SUAVE 工具的基类。

    子类必须实现:
      - name: str          工具的唯一标识符
      - description: str   给 LLM 的描述
      - input_schema: dict JSON Schema 描述输入
      - run(...)          实际执行逻辑
    """

    name: str = ""
    description: str = ""
    input_schema: dict = {}

    def tool_schema(self) -> dict:
        """返回 OpenAI 风格的 tool schema, 供 LLM tool calling 使用。"""
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters":  self.input_schema,
            },
        }

    @abstractmethod
    def run(self, inputs: dict, run_dir: Path) -> dict:
        """执行工具。

        参数:
          inputs:  dict, LLM 给的工具调用参数
          run_dir: Path, 该次运行的输出目录, 工具产物全部写到这里

        返回:
          dict, 标准化的结果, 必须包含:
            - status: 'success' | 'error'
            - summary: str    人类可读的简短总结
            - data: dict      详细数据, 给下一个工具或前端展示
            - artifacts: list 产物文件路径(JSON/PNG/STEP 等)
        """
        ...

    def execute(self, inputs: dict, run_dir: Path) -> dict:
        """带异常捕获的执行入口, 不让异常中断整条流水线。"""
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / f"{self.name}.log"
        result_path = run_dir / f"{self.name}.json"

        t0 = time.time()
        try:
            result = self.run(inputs, run_dir)
            assert isinstance(result, dict), "工具返回值必须是 dict"
            result.setdefault("status",    "success")
            result.setdefault("summary",   "")
            result.setdefault("data",      {})
            result.setdefault("artifacts", [])
            result["elapsed_s"] = round(time.time() - t0, 2)
        except Exception as e:
            tb = traceback.format_exc()
            log_path.write_text(tb, encoding="utf-8")
            result = {
                "status":    "error",
                "summary":   f"工具 {self.name} 失败: {e}",
                "data":      {},
                "artifacts": [str(log_path)],
                "elapsed_s": round(time.time() - t0, 2),
                "error":     str(e),
                "traceback": tb,
            }

        # 落盘 JSON
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

        return result


# ═══════════════════════ 工具注册表 ═══════════════════════
# 子类注册到这里, agent.py 通过这个字典查工具

TOOL_REGISTRY: dict[str, BaseTool] = {}


def register(tool_class):
    """装饰器: 把工具类注册到 TOOL_REGISTRY"""
    instance = tool_class()
    TOOL_REGISTRY[instance.name] = instance
    return tool_class


def get_all_schemas() -> list[dict]:
    """返回所有工具的 schema, 给 LLM tool calling 用。"""
    return [t.tool_schema() for t in TOOL_REGISTRY.values()]


def get_tool(name: str) -> BaseTool:
    if name not in TOOL_REGISTRY:
        raise ToolError(f"未知工具: {name}, 已注册: {list(TOOL_REGISTRY.keys())}")
    return TOOL_REGISTRY[name]
