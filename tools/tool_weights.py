"""
工具 4 · 结构重量估算

输入: Vehicle 配置 + 优化后的几何
输出: 各部件重量分解 (机翼、机身、尾翼、起落架、动力装置、系统)

方法: Raymer "Aircraft Design" Chapter 15 经验公式
- 机翼重量: W_wing = K * S^0.65 * AR^0.36 * (MTOW/Sref)^0.65 * Mach^0.5
- 机身重量: W_fuse = K * L^0.42 * Diameter * V_dive^0.5
- 尾翼: ~ 25% 机翼
- 起落架: ~ 4.5% MTOW
- 系统: ~ 8% MTOW
"""

import json
import math
from pathlib import Path

from . import BaseTool, register


@register
class WeightsTool(BaseTool):
    name = "tool_weights"

    description = (
        "用 Raymer 经验公式估算飞机各部件重量 (机翼/机身/尾翼/起落架/系统/动力)。"
        "需要先调用 tool_requirements。"
    )

    input_schema = {
        "type": "object",
        "properties": {
            "use_optimized_geometry": {
                "type": "boolean",
                "description": "是否使用优化后的几何 (true) 或原始几何 (false), 默认 true",
                "default": True,
            },
        },
    }

    def run(self, inputs: dict, run_dir: Path) -> dict:
        # ── 1. 读上一步数据 ──
        req = json.loads((run_dir / "tool_requirements.json").read_text(encoding="utf-8"))
        vc = req["data"]
        is_electric = vc.get("is_electric", False)

        # 用优化结果如果有
        use_opt = inputs.get("use_optimized_geometry", True)
        opt_path = run_dir / "tool_optimize.json"
        if use_opt and opt_path.exists():
            opt = json.loads(opt_path.read_text(encoding="utf-8"))
            S  = opt["data"]["optimum"]["wing_area_m2"]
            b  = opt["data"]["optimum"]["wingspan_m"]
            AR = opt["data"]["optimum"]["aspect_ratio"]
            geom_source = "optimized"
        else:
            S  = vc["geometry"]["wing_area_m2"]
            b  = vc["geometry"]["max_wingspan_m"]
            AR = vc["geometry"]["aspect_ratio"]
            geom_source = "baseline"

        MTOW = vc["weights_kg"]["mtow"]               # kg
        mach = vc["mission"]["cruise_mach"]
        seats = vc["mission"]["seats"]

        # ── 2. 机身参数估算 ──
        # 经验: L_fuse = 0.65 * (seats^0.5) * 椅距 + 鼻段 + 尾段
        seat_pitch_m = 0.81    # 32 inch
        L_fuse = 3.0 + (seats / 4) * seat_pitch_m + 4.0   # 鼻段 + 客舱 + 尾段
        D_fuse = 2.0 + (seats / 100) * 1.0   # 简化估算

        # ── 3. 各部件重量 (Raymer 简化公式, 单位 kg) ──
        # 机翼 - 简化的 Raymer Eq 15.46 (民航机)
        # W_wing = 0.0051 * (MTOW * n_z)^0.557 * S^0.649 * AR^0.5 * (t/c)^-0.4
        n_z = 3.75    # 极限载荷因子
        t_c = 0.12
        W_wing_lb = 0.0051 * ((MTOW * 2.205 * n_z) ** 0.557) * \
                    ((S * 10.764) ** 0.649) * (AR ** 0.5) * (t_c ** -0.4)
        W_wing = W_wing_lb / 2.205   # → kg

        # 机身 - Raymer Eq 15.49
        L_ft = L_fuse * 3.281
        D_ft = D_fuse * 3.281
        W_fuse_lb = 0.328 * ((MTOW * 2.205) ** 0.5) * (L_ft ** 0.61) * \
                    ((D_ft) ** 0.5) * (1.0)   # 简化: 增压系数 = 1
        W_fuse = W_fuse_lb / 2.205

        # 水平尾翼 (~ 25% 机翼)
        W_htail = 0.25 * W_wing
        # 垂直尾翼 (~ 12% 机翼)
        W_vtail = 0.12 * W_wing
        # 起落架 (~ 4.5% MTOW)
        W_landing = 0.045 * MTOW
        # 操纵系统 (~ 1% MTOW)
        W_controls = 0.01 * MTOW
        # 液压气动 (~ 0.5% MTOW)
        W_hydraulic = 0.005 * MTOW
        # 电气 (~ 1.5% MTOW)
        W_electric = 0.015 * MTOW
        # 航电 (~ 1.0% MTOW)
        W_avionics = 0.01 * MTOW
        # 客舱设备 (~ 50 kg/seat)
        W_furnishings = 50 * seats

        # 动力装置
        if is_electric:
            # 电动飞机推进系统重量
            # 巡航功率: 大约 100 W/kg MTOW (典型电动机参考值)
            # 例: 19座电动机 MTOW 19t → ~ 700-1000 kW
            cruise_power_kw = MTOW * 0.05   # 50 W/kg, 偏保守
            # 现代电机功率密度 5 kW/kg (如 magniX MagniDrive350)
            W_motor = cruise_power_kw / 5.0
            W_propeller = 100.0    # 双螺旋桨, 每个 50 kg
            W_battery = vc.get("propulsion", {}).get("battery_mass_kg", 0)
            W_propulsion = W_motor + W_propeller + W_battery
            propulsion_breakdown = {
                "motor_controller_kg": round(W_motor, 1),
                "propeller_kg":        round(W_propeller, 1),
                "battery_kg":          round(W_battery, 1),
                "cruise_power_kw":     round(cruise_power_kw, 0),
            }
        else:
            # 涡扇发动机, ~ 3 kg/kN 推力
            thrust_per_engine_kN = MTOW * 9.81 * 0.3 / 1000 / 2   # 推重比 0.3, 双发
            W_engines = thrust_per_engine_kN * 2 * 3.0 * 1000     # kg
            W_fuel_system = 0.04 * MTOW
            W_propulsion = W_engines + W_fuel_system
            propulsion_breakdown = {
                "engines_kg":      round(W_engines, 1),
                "fuel_system_kg":  round(W_fuel_system, 1),
            }

        # ── 4. 汇总 ──
        W_structure = W_wing + W_fuse + W_htail + W_vtail + W_landing
        W_systems = W_controls + W_hydraulic + W_electric + W_avionics + W_furnishings
        W_empty_calc = W_structure + W_systems + W_propulsion
        W_payload = vc["weights_kg"]["payload"]
        W_fuel_battery = vc["weights_kg"]["fuel_or_battery"]
        W_takeoff_calc = W_empty_calc + W_payload + W_fuel_battery

        # ── 5. 与初始 MTOW 对比 ──
        delta_pct = ((W_takeoff_calc - MTOW) / MTOW) * 100

        result_data = {
            "geometry_source": geom_source,
            "structure_kg": {
                "wing":     round(W_wing, 1),
                "fuselage": round(W_fuse, 1),
                "h_tail":   round(W_htail, 1),
                "v_tail":   round(W_vtail, 1),
                "landing_gear": round(W_landing, 1),
                "subtotal": round(W_structure, 1),
            },
            "systems_kg": {
                "controls":    round(W_controls, 1),
                "hydraulic":   round(W_hydraulic, 1),
                "electric":    round(W_electric, 1),
                "avionics":    round(W_avionics, 1),
                "furnishings": round(W_furnishings, 1),
                "subtotal":    round(W_systems, 1),
            },
            "propulsion_kg": {
                "subtotal": round(W_propulsion, 1),
                **propulsion_breakdown,
            },
            "summary_kg": {
                "empty_weight":   round(W_empty_calc, 1),
                "payload":        round(W_payload, 1),
                "fuel_or_battery": round(W_fuel_battery, 1),
                "takeoff_calc":   round(W_takeoff_calc, 1),
                "MTOW_input":     round(MTOW, 1),
                "delta_pct":      round(delta_pct, 1),
            },
        }

        warnings = []
        if abs(delta_pct) > 15:
            warnings.append(
                f"重量收敛偏差 {delta_pct:+.1f}%, 超过 ±15%。"
                f"输入 MTOW={MTOW} kg, 估算 {W_takeoff_calc:.0f} kg, "
                f"建议迭代调整 MTOW 或飞机配置"
            )
        if warnings:
            result_data["warnings"] = warnings

        summary = (
            f"重量估算完成: 空重 {W_empty_calc:.0f} kg ({W_empty_calc/MTOW*100:.0f}%), "
            f"机翼 {W_wing:.0f} kg, 机身 {W_fuse:.0f} kg, 推进 {W_propulsion:.0f} kg。"
            f"估算起飞 {W_takeoff_calc:.0f} kg vs 输入 {MTOW:.0f} kg ({delta_pct:+.1f}%)。"
        )

        return {
            "status":    "success",
            "summary":   summary,
            "data":      result_data,
            "artifacts": [],
        }
