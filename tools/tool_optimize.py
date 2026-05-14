"""
工具 3 · 气动优化

输入: 上一步的气动结果
输出: 优化后的翼展/展弦比, 以及优化前后对比

方法:
- 设计变量: 翼展 b, 展弦比 AR
- 目标: 最大化巡航 L/D
- 约束:
  - b ≤ max_wingspan (来自需求)
  - 6 ≤ AR ≤ 14 (工程合理范围)
  - 翼面积 S = b² / AR 在合理范围

注意: 这里用最简单的 grid search, 不依赖 SciPy。这样保证一定能跑通。
"""

import json
import math
from pathlib import Path

from . import BaseTool, register


@register
class OptimizeTool(BaseTool):
    name = "tool_optimize"

    description = (
        "用 grid search 优化机翼几何 (翼展 + 展弦比), 目标最大化巡航升阻比。"
        "需要先调用 tool_requirements 和 tool_aerodynamics。"
    )

    input_schema = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "enum":  ["max_L_D", "min_drag", "min_wing_weight"],
                "description": "优化目标, 默认 max_L_D",
                "default": "max_L_D",
            },
        },
    }

    def run(self, inputs: dict, run_dir: Path) -> dict:
        # ── 1. 读上一步数据 ──
        req = json.loads((run_dir / "tool_requirements.json").read_text(encoding="utf-8"))
        aer = json.loads((run_dir / "tool_aerodynamics.json").read_text(encoding="utf-8"))
        vc = req["data"]
        objective = inputs.get("objective") or "max_L_D"

        b_max = vc["geometry"]["max_wingspan_m"]
        mtow_N = vc["weights_kg"]["mtow"] * 9.81
        rho = aer["data"]["atmosphere"]["density_kg_m3"]
        v   = aer["data"]["atmosphere"]["velocity_m_s"]
        q   = 0.5 * rho * v * v
        CD0_base = aer["data"]["drag_breakdown"]["CD0"]
        CD_wave  = aer["data"]["drag_breakdown"]["CD_wave"]

        # 优化前的基线
        baseline = {
            "wingspan_m":   vc["geometry"]["max_wingspan_m"],
            "aspect_ratio": vc["geometry"]["aspect_ratio"],
            "wing_area_m2": vc["geometry"]["wing_area_m2"],
            "L_over_D":     aer["data"]["cruise_point"]["L_over_D"],
            "CD":           aer["data"]["cruise_point"]["CD"],
        }

        # ── 2. Grid search ──
        # b: 80% ~ 100% 最大翼展; AR: 6 ~ 14
        b_grid  = [b_max * x for x in (0.8, 0.85, 0.9, 0.95, 1.0)]
        ar_grid = [6, 8, 9, 10, 11, 12, 13, 14]

        best     = None
        all_runs = []
        for b in b_grid:
            for ar in ar_grid:
                S = b * b / ar
                if S < 10 or S > 200:    # 不合理范围跳过
                    continue
                # 重新算诱导阻力
                CL = mtow_N * 0.95 / (q * S)
                if CL > 1.5:             # 攻角太大, 不合理
                    continue
                K = 1.0 / (math.pi * ar * 0.85)
                # CD0 与翼面积/湿面积有关, 简化为线性放大
                CD0 = CD0_base * (S / vc["geometry"]["wing_area_m2"]) ** 0.5
                CDi = K * CL * CL
                CD = CD0 + CDi + CD_wave
                L_D = CL / CD if CD > 0 else 0

                # 目标函数
                if objective == "max_L_D":
                    score = L_D
                elif objective == "min_drag":
                    score = -CD
                elif objective == "min_wing_weight":
                    # 简化: 翼重 ~ b^1.5 * S^0.5
                    score = -(b ** 1.5 * S ** 0.5) / 100
                else:
                    score = L_D

                run_pt = {
                    "b": round(b, 2), "AR": round(ar, 1), "S": round(S, 1),
                    "CL": round(CL, 3), "CD": round(CD, 5), "L_D": round(L_D, 2),
                    "score": round(score, 4),
                }
                all_runs.append(run_pt)

                if best is None or score > best["score"]:
                    best = run_pt

        # ── 3. 收敛判断 ──
        improvement_pct = ((best["L_D"] - baseline["L_over_D"]) / baseline["L_over_D"]) * 100

        # ── 4. 输出 ──
        result_data = {
            "objective":   objective,
            "n_evaluations": len(all_runs),
            "baseline":    baseline,
            "optimum": {
                "wingspan_m":   best["b"],
                "aspect_ratio": best["AR"],
                "wing_area_m2": best["S"],
                "L_over_D":     best["L_D"],
                "CD":           best["CD"],
            },
            "improvement_pct": round(improvement_pct, 1),
            "top_5_designs":   sorted(all_runs, key=lambda r: -r["score"])[:5],
        }

        if best["b"] > b_max * 0.99:
            result_data.setdefault("warnings", []).append(
                "最优翼展接近最大约束, 实际可行翼展可能受限于机场停机位"
            )

        summary = (
            f"优化完成 ({len(all_runs)} 次评估): "
            f"最优 b={best['b']} m, AR={best['AR']}, S={best['S']} m². "
            f"L/D 从 {baseline['L_over_D']:.1f} 提升到 {best['L_D']:.1f} "
            f"({improvement_pct:+.1f}%)."
        )

        return {
            "status":    "success",
            "summary":   summary,
            "data":      result_data,
            "artifacts": [],
        }
