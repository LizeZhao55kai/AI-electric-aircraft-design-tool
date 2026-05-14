"""
工具 5 · 电推进任务分析

输入: Vehicle 配置 + 气动 + 重量
输出: 任务剖面 (爬升/巡航/下降), 续航能力, 能耗

电动飞机的 Breguet 续航公式:
  Range = (E_battery * η_total / (W * g)) * (L/D)

其中:
  E_battery = battery_kwh * 3.6e6  (J)
  η_total = η_motor * η_inverter * η_propeller ≈ 0.85 * 0.95 * 0.85 = 0.69
  W = MTOW * g (N)
"""

import json
import math
from pathlib import Path

from . import BaseTool, register


@register
class PropulsionTool(BaseTool):
    name = "tool_propulsion"

    description = (
        "分析推进系统任务剖面: 爬升/巡航/下降, 计算续航和能耗。"
        "需要先调用 tool_requirements 和 tool_aerodynamics。"
    )

    input_schema = {
        "type": "object",
        "properties": {
            "reserve_fraction": {
                "type": "number",
                "description": "电池/燃油备用比例, 默认 0.15 (15%)",
                "default": 0.15,
            },
        },
    }

    def run(self, inputs: dict, run_dir: Path) -> dict:
        # ── 1. 读上一步数据 ──
        req = json.loads((run_dir / "tool_requirements.json").read_text(encoding="utf-8"))
        aer = json.loads((run_dir / "tool_aerodynamics.json").read_text(encoding="utf-8"))
        vc = req["data"]
        is_electric = vc.get("is_electric", False)
        reserve = inputs.get("reserve_fraction", 0.15)

        MTOW_kg = vc["weights_kg"]["mtow"]
        v_cruise = aer["data"]["atmosphere"]["velocity_m_s"]
        L_D_cruise = aer["data"]["cruise_point"]["L_over_D"]
        cruise_alt = vc["mission"]["cruise_alt_m"]

        # ── 2. 巡航功率需求 ──
        # P_cruise = T * V = (W / (L/D)) * V
        W_N = MTOW_kg * 9.81 * 0.95   # 巡航中段
        T_cruise_N = W_N / L_D_cruise
        P_cruise_W = T_cruise_N * v_cruise

        if is_electric:
            # ── 3a. 电动飞机 ──
            battery_kwh = vc.get("propulsion", {}).get("battery_kwh", 0)
            if battery_kwh <= 0:
                raise ValueError("电动飞机但 battery_kwh = 0, 检查需求工具输出")

            # 效率链
            eta_motor      = 0.92
            eta_inverter   = 0.95
            eta_propeller  = 0.85
            eta_total      = eta_motor * eta_inverter * eta_propeller   # ~0.74

            # 巡航段电池放电功率
            P_battery_W = P_cruise_W / eta_total
            P_battery_kW = P_battery_W / 1000

            # 可用电池能量 (扣掉备用 + DOD 90%)
            E_usable_kwh = battery_kwh * (1 - reserve) * 0.9

            # 巡航续航 (Breguet for electric)
            t_cruise_h = E_usable_kwh / P_battery_kW
            range_cruise_km = v_cruise * 3.6 * t_cruise_h * 0.85  # 爬升+下降占 15% 距离

            # 任务剖面分段
            mission_profile = self._electric_mission_profile(
                MTOW_kg, v_cruise, cruise_alt, L_D_cruise, eta_total,
                battery_kwh, reserve,
            )

            propulsion_data = {
                "type": "electric",
                "battery_kwh":         battery_kwh,
                "battery_usable_kwh":  round(E_usable_kwh, 1),
                "cruise_power_kw":     round(P_battery_kW, 1),
                "efficiency_chain": {
                    "motor":     eta_motor,
                    "inverter":  eta_inverter,
                    "propeller": eta_propeller,
                    "total":     round(eta_total, 3),
                },
                "estimated_range_km":  round(range_cruise_km, 1),
                "endurance_h":         round(t_cruise_h, 2),
                "energy_consumption_wh_per_km": round(
                    battery_kwh * 1000 / max(range_cruise_km, 1), 1),
            }

        else:
            # ── 3b. 燃油飞机 (用 Breguet for jet) ──
            fuel_kg = vc["weights_kg"]["fuel_or_battery"]
            sfc = 0.55 / 3600   # kg/(N·s), 典型涡扇 0.5-0.7 lb/(lbf·hr)
            # Range = (V/g·SFC) * (L/D) * ln(W_initial/W_final)
            W_init = MTOW_kg
            W_final = MTOW_kg - fuel_kg * (1 - reserve)
            range_m = (v_cruise / (9.81 * sfc)) * L_D_cruise * math.log(W_init / W_final)
            range_km = range_m / 1000
            propulsion_data = {
                "type": "turbofan",
                "fuel_kg":       fuel_kg,
                "fuel_usable_kg": round(fuel_kg * (1 - reserve), 1),
                "sfc_kg_N_s":    sfc,
                "estimated_range_km": round(range_km, 1),
                "fuel_per_km_kg": round(fuel_kg / range_km, 3),
            }
            mission_profile = []   # 燃油机简化, 不画详细剖面

        # ── 4. 与设计航程对比 ──
        design_range_km = vc["mission"]["range_km"]
        actual_range = propulsion_data["estimated_range_km"]
        margin_pct = ((actual_range - design_range_km) / design_range_km) * 100

        result_data = {
            "design_range_km":   design_range_km,
            "estimated_range_km": actual_range,
            "range_margin_pct":  round(margin_pct, 1),
            "cruise_velocity_m_s": round(v_cruise, 2),
            "L_over_D_used":     L_D_cruise,
            "propulsion":        propulsion_data,
            "mission_profile":   mission_profile,
        }

        warnings = []
        if margin_pct < -5:
            warnings.append(
                f"实际续航 {actual_range:.0f} km < 设计航程 {design_range_km:.0f} km "
                f"({margin_pct:+.1f}%)。建议增加电池/燃油 或 优化气动效率"
            )
        elif margin_pct > 50:
            warnings.append(
                f"实际续航是设计航程的 {1 + margin_pct/100:.1f} 倍, 电池/燃油可能富余, "
                f"可减重以提升经济性"
            )
        if warnings:
            result_data["warnings"] = warnings

        summary = (
            f"任务分析完成: {'电动' if is_electric else '燃油'} 推进, "
            f"巡航功率 {propulsion_data.get('cruise_power_kw', '-')} kW, "
            f"估算续航 {actual_range:.0f} km vs 设计 {design_range_km:.0f} km "
            f"({margin_pct:+.1f}%)。"
        )

        return {
            "status":    "success",
            "summary":   summary,
            "data":      result_data,
            "artifacts": [],
        }

    def _electric_mission_profile(self, mtow, v_cruise, alt_cruise,
                                   L_D, eta, battery_kwh, reserve):
        """生成电动飞机任务剖面 (爬升 / 巡航 / 下降)"""
        segments = []

        # 爬升段 - 假设爬升率 5 m/s, 平均功率 = 1.5 * 巡航功率
        climb_rate = 5.0
        t_climb_s = alt_cruise / climb_rate
        P_climb_kW = (mtow * 9.81 * 0.95 / L_D * v_cruise) / eta * 1.5 / 1000
        E_climb_kwh = P_climb_kW * t_climb_s / 3600
        segments.append({
            "stage":         "climb",
            "duration_min":  round(t_climb_s / 60, 1),
            "altitude_m":    f"0 → {alt_cruise:.0f}",
            "power_kw":      round(P_climb_kW, 1),
            "energy_kwh":    round(E_climb_kwh, 1),
        })

        # 下降段 - 假设下降率 3 m/s, 平均功率 = 0.3 * 巡航功率
        descent_rate = 3.0
        t_descent_s = alt_cruise / descent_rate
        P_descent_kW = (mtow * 9.81 * 0.95 / L_D * v_cruise) / eta * 0.3 / 1000
        E_descent_kwh = P_descent_kW * t_descent_s / 3600

        # 巡航段 - 用剩余电量
        E_usable = battery_kwh * (1 - reserve) * 0.9
        E_cruise = E_usable - E_climb_kwh - E_descent_kwh
        if E_cruise <= 0:
            E_cruise = 0
        P_cruise_kW = (mtow * 9.81 * 0.95 / L_D * v_cruise) / eta / 1000
        t_cruise_s = E_cruise / P_cruise_kW * 3600 if P_cruise_kW > 0 else 0
        d_cruise_km = v_cruise * 3.6 * t_cruise_s / 3600
        segments.append({
            "stage":         "cruise",
            "duration_min":  round(t_cruise_s / 60, 1),
            "altitude_m":    f"{alt_cruise:.0f} (level)",
            "distance_km":   round(d_cruise_km, 1),
            "power_kw":      round(P_cruise_kW, 1),
            "energy_kwh":    round(E_cruise, 1),
        })

        segments.append({
            "stage":         "descent",
            "duration_min":  round(t_descent_s / 60, 1),
            "altitude_m":    f"{alt_cruise:.0f} → 0",
            "power_kw":      round(P_descent_kW, 1),
            "energy_kwh":    round(E_descent_kwh, 1),
        })

        return segments
