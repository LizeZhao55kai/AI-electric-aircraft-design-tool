"""
工具 2 · 气动分析

输入: 上一步 tool_requirements 的 Vehicle 配置
输出: CL/CD/L_D 等气动参数, 阻力极曲线, 多个攻角下的扫描

方法: Raymer "Aircraft Design: A Conceptual Approach" 第 12 章经验公式
- 零升阻力系数 CD0 用湿面积法 (Wing/Body/Tail/Nacelle 分项)
- 诱导阻力 CDi = CL² / (π·AR·e), Oswald 效率因子 e = 0.85
- 跨/超声速波阻 用 Korn 方程
"""

import json
import math
from pathlib import Path

from . import BaseTool, register


@register
class AerodynamicsTool(BaseTool):
    name = "tool_aerodynamics"

    description = (
        "用 Raymer 经验公式估算飞机气动性能 (CL, CD, 升阻比, 阻力极曲线)。"
        "需要先调用 tool_requirements。"
    )

    input_schema = {
        "type": "object",
        "properties": {
            "alpha_sweep_deg": {
                "type": "array",
                "items": {"type": "number"},
                "description": "攻角扫描列表(度), 默认 [-2, 0, 2, 4, 6, 8]",
                "default": [-2, 0, 2, 4, 6, 8],
            },
        },
    }

    def run(self, inputs: dict, run_dir: Path) -> dict:
        # ── 1. 从上一步读 Vehicle 配置 ──
        prev = run_dir / "tool_requirements.json"
        if not prev.exists():
            raise RuntimeError("找不到 tool_requirements.json, 请先调用需求处理工具")

        req_result = json.loads(prev.read_text(encoding="utf-8"))
        vc = req_result["data"]
        geom = vc["geometry"]
        miss = vc["mission"]
        is_electric = vc.get("is_electric", False)

        # ── 2. 输入参数 ──
        S       = geom["wing_area_m2"]
        AR      = geom["aspect_ratio"]
        b       = geom["max_wingspan_m"]
        mach    = miss["cruise_mach"]
        alt     = miss["cruise_alt_m"]
        alphas  = inputs.get("alpha_sweep_deg") or [-2, 0, 2, 4, 6, 8]

        # ── 3. 大气模型 (国际标准大气, 简化版) ──
        # 0-11 km 对流层
        T0, p0, rho0, a0 = 288.15, 101325.0, 1.225, 340.29
        if alt <= 11000:
            T   = T0 - 0.0065 * alt
            p   = p0 * (T / T0) ** 5.2561
            rho = rho0 * (T / T0) ** 4.2561
        else:
            T   = 216.65
            p   = 22632.0 * math.exp(-(alt - 11000) / 6341.6)
            rho = 0.3639 * math.exp(-(alt - 11000) / 6341.6)
        a = math.sqrt(1.4 * 287.05 * T)
        v = mach * a
        q = 0.5 * rho * v * v          # 动压

        # ── 4. CD0 估算 (湿面积法 + 平板摩擦) ──
        # 各部件湿面积估算 (Raymer Eq. 12.39 et seq.)
        S_wet_wing  = 2.0 * S * 1.02      # 机翼湿面积 (双面 + 修正)
        S_wet_fuse  = math.pi * 2.1 * 18.0 * 0.9   # 简化: 圆柱面积 * 0.9
        S_wet_tail  = 0.3 * S_wet_wing    # 尾翼一般占机翼的 30%
        S_wet_total = S_wet_wing + S_wet_fuse + S_wet_tail

        # 摩擦系数 (Schlichting 平板湍流, 取 Re=1e7 附近)
        Re_per_m = rho * v / 1.78e-5
        Re = Re_per_m * 5.0    # 取参考长度 5m
        cf = 0.455 / (math.log10(max(Re, 1e6)) ** 2.58)

        # CD0 = cf * S_wet / S_ref * 形状因子(~1.2) * 干扰因子(~1.05)
        CD0 = cf * (S_wet_total / S) * 1.2 * 1.05

        # ── 5. 跨声速波阻 (Korn 方程, 仅 Mach > 0.7) ──
        CD_wave = 0.0
        if mach > 0.7:
            # 估算临界马赫数 (假设超临界翼型, kA = 0.95)
            t_c = 0.12         # 相对厚度
            CL_design = 0.5    # 设计点 CL
            kA = 0.95
            cos_sweep = math.cos(math.radians(5.0))    # 后掠角 5 度 (CE-25A 类)
            M_cc = (kA / cos_sweep) - (t_c / cos_sweep ** 2) - (CL_design / (10 * cos_sweep ** 3))
            if mach > M_cc:
                CD_wave = 20.0 * (mach - M_cc) ** 4

        # ── 6. 攻角扫描: 计算 CL, CD, L/D ──
        # CL 升力线: dCL/dα = 2π·AR / (2 + sqrt(AR² · (1 + tan²Λ - M²) + 4))
        # 简化为 CL = 0.1 * (alpha + 1.5)  其中 1.5 是零升攻角偏移
        CL_alpha = 0.1                # /deg, 经验值
        alpha_zl = -1.5               # 零升攻角(度)

        e_oswald = 0.85               # Oswald 效率因子
        K_induced = 1.0 / (math.pi * AR * e_oswald)

        polar = []
        for alpha in alphas:
            CL = CL_alpha * (alpha - alpha_zl)
            CDi = K_induced * CL * CL
            CD = CD0 + CDi + CD_wave
            L_over_D = CL / CD if CD > 0 else 0
            polar.append({
                "alpha_deg":  round(alpha, 2),
                "CL":         round(CL, 4),
                "CD":         round(CD, 5),
                "CDi":        round(CDi, 5),
                "L_over_D":   round(L_over_D, 2),
            })

        # ── 7. 巡航点 (设计 CL 平衡重量) ──
        W_cruise_N = vc["weights_kg"]["mtow"] * 9.81 * 0.95  # 巡航中段重量
        CL_cruise = W_cruise_N / (q * S)
        alpha_cruise = CL_cruise / CL_alpha + alpha_zl
        CDi_cruise = K_induced * CL_cruise ** 2
        CD_cruise = CD0 + CDi_cruise + CD_wave
        L_D_cruise = CL_cruise / CD_cruise if CD_cruise > 0 else 0

        # ── 8. 输出 ──
        result_data = {
            "atmosphere": {
                "altitude_m":  alt,
                "density_kg_m3": round(rho, 4),
                "velocity_m_s":  round(v, 2),
                "dynamic_pressure_Pa": round(q, 1),
                "speed_of_sound_m_s":  round(a, 2),
            },
            "drag_breakdown": {
                "CD0":      round(CD0, 5),
                "CD_wave":  round(CD_wave, 5),
                "K_induced": round(K_induced, 5),
                "wetted_area_m2": round(S_wet_total, 1),
            },
            "cruise_point": {
                "CL":       round(CL_cruise, 4),
                "CD":       round(CD_cruise, 5),
                "L_over_D": round(L_D_cruise, 2),
                "alpha_deg": round(alpha_cruise, 2),
            },
            "polar_curve": polar,
            "max_L_D": round(max(p["L_over_D"] for p in polar), 2),
        }

        # 巡航 L/D 合理性检查
        warnings = []
        if L_D_cruise < 5:
            warnings.append(f"巡航 L/D 仅 {L_D_cruise:.1f}, 偏低 (典型 12-20)")
        if L_D_cruise > 25:
            warnings.append(f"巡航 L/D 高达 {L_D_cruise:.1f}, 异常 (典型 12-20)")
        if warnings:
            result_data["warnings"] = warnings

        summary = (
            f"气动分析完成: 巡航 CL={CL_cruise:.3f}, CD={CD_cruise:.4f}, "
            f"L/D={L_D_cruise:.1f}。CD0={CD0:.4f}, 最大升阻比 {max(p['L_over_D'] for p in polar):.1f}。"
        )

        return {
            "status":  "success",
            "summary": summary,
            "data":    result_data,
            "artifacts": [],
        }
