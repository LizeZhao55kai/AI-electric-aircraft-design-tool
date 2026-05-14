"""
工具 1 · 需求处理

输入: 用户填的设计需求 (机型类别、座位、航程、电池容量等)
输出: 标准化的 SUAVE Vehicle 配置 JSON, 供后续工具消费

不调用 SUAVE, 只做参数校验和派生计算 — 这是最快的一步, 适合做"系统跑通"的烟雾测试。
"""

from pathlib import Path
import math

from . import BaseTool, register


@register
class RequirementsTool(BaseTool):
    name = "tool_requirements"

    description = (
        "处理飞机设计需求, 校验输入参数, 计算派生量(如最大起飞重量初值、巡航高度建议), "
        "输出供后续气动/结构/电推进工具使用的标准化配置。"
    )

    input_schema = {
        "type": "object",
        "properties": {
            "aircraft_class": {
                "type":        "string",
                "enum":        ["subsonic-narrow", "subsonic-wide",
                                "supersonic", "regional", "electric-regional"],
                "description": "机型类别。CE-25A 应选 electric-regional",
            },
            "seats":          {"type": "integer", "description": "座位数, 例 19"},
            "range_km":       {"type": "number",  "description": "设计航程 (km), 例 500"},
            "cruise_mach":    {"type": "number",  "description": "巡航马赫数, 例 0.35"},
            "cruise_alt_m":   {"type": "number",  "description": "巡航高度 (m), 例 3000"},
            "max_wingspan_m": {"type": "number",  "description": "最大允许翼展 (m)"},
            "battery_kwh":    {"type": "number",  "description": "电池容量 kWh, 仅电动飞机"},
            "extra":          {"type": "string",  "description": "其他自由文本要求"},
        },
        "required": ["aircraft_class"],
    }

    def run(self, inputs: dict, run_dir: Path) -> dict:
        """处理设计需求, 输出标准化 Vehicle 配置。"""

        # ── 1. 校验输入 ──
        cls = inputs.get("aircraft_class")
        if not cls:
            raise ValueError("aircraft_class 必填")

        seats   = int(inputs.get("seats", 0)) or self._default_seats(cls)
        range_  = float(inputs.get("range_km", 0)) or self._default_range(cls)
        mach    = float(inputs.get("cruise_mach", 0)) or self._default_mach(cls)
        alt     = float(inputs.get("cruise_alt_m", 0)) or self._default_alt(cls)
        wspan   = float(inputs.get("max_wingspan_m", 0)) or self._default_wingspan(cls, seats)

        # ── 2. 派生计算 ──
        # MTOW 估算 (kg) - 不同机型用不同系数
        # 参考: Raymer Table 3.1 + 真实飞机数据
        mtow_per_seat = {
            "subsonic-narrow":   400,    # B737-800: 79t / 189 seats ≈ 418
            "subsonic-wide":     500,    # A330-300: 233t / 440 ≈ 530
            "supersonic":        1850,   # Concorde: 185t / 100 ≈ 1850
            "regional":          280,    # ATR-72: 23t / 78 ≈ 295
            "electric-regional": 350,    # Cessna SkyCourier (柴油): 8.6t / 19 ≈ 450, 电动稍重些
        }.get(cls, 350)
        range_factor = {
            "subsonic-narrow":   8,
            "subsonic-wide":     12,
            "supersonic":        15,
            "regional":          5,
            "electric-regional": 1,    # 电动机航程短不显著影响
        }.get(cls, 5)
        mtow_kg = mtow_per_seat * seats + range_factor * range_
        empty_w = mtow_kg * 0.55                # 空重 ~55%
        fuel_w  = mtow_kg * 0.30                # 燃油 / 电池 ~30%
        payload = seats * 100                   # 单乘客+行李 100kg

        # 翼面积 (m²) - 优先用典型翼载荷, 再算展弦比
        wing_loading_kg_m2 = {
            "subsonic-narrow":   600,
            "subsonic-wide":     650,
            "supersonic":        400,
            "regional":          400,
            "electric-regional": 300,    # 电动机翼载荷低, 续航需要
        }.get(cls, 450)
        wing_area = mtow_kg / wing_loading_kg_m2

        # 展弦比 - 检查翼展约束, 必要时降低 AR
        ar_target = {"subsonic-narrow": 9.5, "subsonic-wide": 9.0,
                     "supersonic": 1.7, "regional": 11.0,
                     "electric-regional": 10.0}.get(cls, 9.0)
        # 实际翼展 = sqrt(AR * S), 不能超过 max_wingspan
        ideal_span = math.sqrt(ar_target * wing_area)
        if ideal_span > wspan:
            # 翼展受限, 降低 AR
            ar_default = (wspan ** 2) / wing_area
        else:
            ar_default = ar_target
            wspan = ideal_span    # 用理想翼展

        # ── 3. 电动飞机特殊处理 ──
        is_electric = cls.startswith("electric")
        battery_kwh = float(inputs.get("battery_kwh", 0))
        if is_electric and not battery_kwh:
            # 经验公式: 1 kWh ≈ 5 kg 电池, 续航 1km 需要 ~0.5 kWh (小型电动机)
            battery_kwh = 0.5 * range_
        if is_electric:
            empty_w  += battery_kwh * 5         # 电池重量并入空重
            fuel_w    = 0                        # 电动机没有燃油

        # ── 4. 构造标准输出 ──
        vehicle_config = {
            "aircraft_class": cls,
            "is_electric":    is_electric,
            "geometry": {
                "max_wingspan_m": wspan,
                "wing_area_m2":   round(wing_area, 2),
                "aspect_ratio":   round(wspan ** 2 / wing_area, 2),
            },
            "mission": {
                "range_km":     range_,
                "cruise_mach":  mach,
                "cruise_alt_m": alt,
                "seats":        seats,
            },
            "weights_kg": {
                "mtow":     round(mtow_kg, 1),
                "empty":    round(empty_w, 1),
                "fuel_or_battery": round(fuel_w if not is_electric else battery_kwh * 5, 1),
                "payload":  payload,
            },
        }
        if is_electric:
            vehicle_config["propulsion"] = {
                "type":         "electric",
                "battery_kwh":  battery_kwh,
                "battery_mass_kg": round(battery_kwh * 5, 1),
            }

        # ── 5. 人类可读总结 ──
        summary = (
            f"已确认 {cls} 机型: {seats} 座, 航程 {range_:.0f} km, "
            f"巡航 Mach {mach:.2f} @ {alt:.0f} m。"
            f"估算 MTOW={mtow_kg:.0f} kg, 翼面积={wing_area:.1f} m²。"
        )
        if is_electric:
            summary += f" 电池 {battery_kwh:.0f} kWh ({battery_kwh*5:.0f} kg)。"

        return {
            "status":  "success",
            "summary": summary,
            "data":    vehicle_config,
            "artifacts": [],  # 这一步纯计算, 没有大文件产物
        }

    # ─────── 辅助: 各机型默认值 ───────
    def _default_seats(self, cls):
        return {"subsonic-narrow": 180, "subsonic-wide": 300,
                "supersonic": 100, "regional": 70,
                "electric-regional": 19}.get(cls, 100)

    def _default_range(self, cls):
        return {"subsonic-narrow": 5500, "subsonic-wide": 11000,
                "supersonic": 6000, "regional": 2000,
                "electric-regional": 500}.get(cls, 3000)

    def _default_mach(self, cls):
        return {"subsonic-narrow": 0.78, "subsonic-wide": 0.82,
                "supersonic": 2.0, "regional": 0.72,
                "electric-regional": 0.35}.get(cls, 0.7)

    def _default_alt(self, cls):
        return {"subsonic-narrow": 11000, "subsonic-wide": 11500,
                "supersonic": 18000, "regional": 9000,
                "electric-regional": 3000}.get(cls, 10000)

    def _default_wingspan(self, cls, seats):
        # 简单估算: 翼展 ≈ 2 * sqrt(seats), 但有不同机型上限
        import math
        base = 2 * math.sqrt(max(seats, 10))
        cap = {"subsonic-narrow": 36, "subsonic-wide": 60,
               "supersonic": 25, "regional": 28, "electric-regional": 20}.get(cls, 30)
        return min(base * 1.5, cap)
