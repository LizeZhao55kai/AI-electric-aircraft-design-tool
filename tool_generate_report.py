"""
工具 6 · 报告生成

输入: 前 5 个工具的 JSON 结果 (从 run_dir 读)
输出:
  - CE-25A_设计报告.md   (markdown 格式, 可直接看)
  - CE-25A_设计报告.docx (Word 格式, 调用 G6 的 md2docx_report.py 生成)

方法:
  1. 读 5 个工具的 JSON 结果
  2. 扁平化成一个 dict (key 对应模板里的占位符)
  3. 用正则替换 {{key}} → 真实数值
  4. 调用 report_gen/md2docx_report.py 生成 docx
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from . import BaseTool, register


# 项目根目录(tools/ 的上层目录)
PROJECT_ROOT = Path(__file__).parent.parent
REPORT_GEN_DIR = PROJECT_ROOT / "report_gen"
TEMPLATE_MD = REPORT_GEN_DIR / "ce25a_design_template.md"
WORD_TEMPLATE = REPORT_GEN_DIR / "word_template" / "模版1.docx"
MD2DOCX_SCRIPT = REPORT_GEN_DIR / "md2docx_report.py"


@register
class GenerateReportTool(BaseTool):
    name = "tool_generate_report"

    description = (
        "【流程最后一步·必须调用】将前 5 个设计工具的结果整合成 CE-25A 设计报告 "
        "(Markdown + Word docx 两种格式)。"
        "★ 重要: 当 tool_requirements、tool_aerodynamics、tool_optimize、"
        "tool_weights、tool_propulsion 五个工具全部完成后, 你必须调用此工具"
        "生成最终设计报告。不调用此工具就直接结束流程, 会导致用户没有报告可看, "
        "属于流程未完成。"
    )

    input_schema = {
        "type": "object",
        "properties": {
            "skip_docx": {
                "type": "boolean",
                "description": "是否跳过 docx 生成 (只输出 md), 默认 false",
                "default": False,
            },
        },
    }

    def run(self, inputs: dict, run_dir: Path) -> dict:
        skip_docx = inputs.get("skip_docx", False)

        # ── 1. 读 5 个工具的结果 ──
        required_tools = [
            "tool_requirements",
            "tool_aerodynamics",
            "tool_optimize",
            "tool_weights",
            "tool_propulsion",
        ]
        results = {}
        missing = []
        for tname in required_tools:
            f = run_dir / f"{tname}.json"
            if not f.exists():
                missing.append(tname)
                continue
            results[tname] = json.loads(f.read_text(encoding="utf-8"))

        if missing:
            raise RuntimeError(
                f"缺少前置工具结果: {missing}。请先运行: {', '.join(missing)}"
            )

        # ── 2. 扁平化数据 ──
        flat = self._flatten(results)

        # ── 3. 读模板 + 替换占位符 ──
        if not TEMPLATE_MD.exists():
            raise RuntimeError(f"找不到报告模板: {TEMPLATE_MD}")

        template_text = TEMPLATE_MD.read_text(encoding="utf-8")
        rendered_md = self._render(template_text, flat)

        # 检查是否有未替换的占位符
        unresolved = re.findall(r"\{\{([^}]+)\}\}", rendered_md)
        if unresolved:
            # 不致命, 只是警告
            print(f"[tool_generate_report] 警告: {len(unresolved)} 个占位符未解析: "
                  f"{list(set(unresolved))[:5]}", file=sys.stderr)

        # ── 4. 写 markdown 文件 ──
        md_path = run_dir / "CE-25A_设计报告.md"
        md_path.write_text(rendered_md, encoding="utf-8")

        result_data = {
            "md_file": str(md_path),
            "md_size_bytes": md_path.stat().st_size,
            "n_placeholders_resolved": 63 - len(set(unresolved)),
            "n_placeholders_total": 63,
        }
        artifacts = [str(md_path)]

        # ── 5. 调 md2docx 生成 docx (可选) ──
        if not skip_docx:
            if not MD2DOCX_SCRIPT.exists():
                result_data["docx_status"] = "skipped"
                result_data["docx_error"] = f"找不到 {MD2DOCX_SCRIPT}"
            elif not WORD_TEMPLATE.exists():
                result_data["docx_status"] = "skipped"
                result_data["docx_error"] = f"找不到 Word 模板 {WORD_TEMPLATE}"
            else:
                docx_path = run_dir / "CE-25A_设计报告.docx"
                cmd = [
                    sys.executable,
                    str(MD2DOCX_SCRIPT),
                    "--template", str(WORD_TEMPLATE),
                    "--input", str(md_path),
                    "--output", str(docx_path),
                    "--profile", "general",
                    "--skip-validation",   # 第一版跳过校验, 避免格式不一致报错
                ]
                try:
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        cwd=str(PROJECT_ROOT),
                    )
                    if proc.returncode == 0 and docx_path.exists():
                        result_data["docx_file"] = str(docx_path)
                        result_data["docx_size_bytes"] = docx_path.stat().st_size
                        result_data["docx_status"] = "success"
                        artifacts.append(str(docx_path))
                    else:
                        result_data["docx_status"] = "error"
                        result_data["docx_error"] = (
                            proc.stderr[-500:] if proc.stderr else "未知错误"
                        )
                except subprocess.TimeoutExpired:
                    result_data["docx_status"] = "timeout"
                    result_data["docx_error"] = "md2docx 转换超时 (>120s)"
                except Exception as e:
                    result_data["docx_status"] = "error"
                    result_data["docx_error"] = str(e)

        # ── 6. 输出 ──
        summary_parts = [
            f"生成 markdown 报告 ({result_data['md_size_bytes']:,} 字节, "
            f"{result_data['n_placeholders_resolved']}/{result_data['n_placeholders_total']} 占位符)"
        ]
        if not skip_docx:
            ds = result_data.get("docx_status", "skipped")
            if ds == "success":
                summary_parts.append(f"+ docx ({result_data['docx_size_bytes']:,} 字节)")
            else:
                summary_parts.append(f"docx 失败 ({ds})")

        return {
            "status": "success",
            "summary": "已" + ", ".join(summary_parts),
            "data": result_data,
            "artifacts": artifacts,
        }

    # ════════════════════════════════════════════════
    # 数据扁平化
    # ════════════════════════════════════════════════
    def _flatten(self, results: dict) -> dict:
        """5 个工具的输出 → 一个扁平 dict 供模板使用"""
        req = results["tool_requirements"]["data"]
        aer = results["tool_aerodynamics"]["data"]
        opt = results["tool_optimize"]["data"]
        wts = results["tool_weights"]["data"]
        prp = results["tool_propulsion"]["data"]

        mtow = req["weights_kg"]["mtow"]

        flat = {
            # ─── 需求 ───
            "aircraft_class": req.get("aircraft_class", "-"),
            "seats":          req["mission"]["seats"],
            "range_km":       req["mission"]["range_km"],
            "cruise_mach":    req["mission"]["cruise_mach"],
            "cruise_alt_m":   req["mission"]["cruise_alt_m"],
            "max_wingspan_m": req["geometry"]["max_wingspan_m"],
            "mtow":           mtow,
            "wing_area":      req["geometry"]["wing_area_m2"],
            "aspect_ratio":   req["geometry"]["aspect_ratio"],
            "wing_loading":   round(mtow / req["geometry"]["wing_area_m2"], 1),
            "battery_kwh":    req.get("propulsion", {}).get("battery_kwh", 0),

            # ─── 气动 ───
            "rho":              aer["atmosphere"]["density_kg_m3"],
            "velocity":         aer["atmosphere"]["velocity_m_s"],
            "dynamic_pressure": aer["atmosphere"]["dynamic_pressure_Pa"],
            "CD0":              aer["drag_breakdown"]["CD0"],
            "K_induced":        aer["drag_breakdown"]["K_induced"],
            "CD_wave":          aer["drag_breakdown"]["CD_wave"],
            "wetted_area":      aer["drag_breakdown"]["wetted_area_m2"],
            "CL_cruise":        aer["cruise_point"]["CL"],
            "CD_cruise":        aer["cruise_point"]["CD"],
            "LD_cruise":        aer["cruise_point"]["L_over_D"],
            "alpha_cruise":     aer["cruise_point"]["alpha_deg"],
            "max_LD":           aer["max_L_D"],

            # ─── 优化 ───
            "n_evaluations":   opt["n_evaluations"],
            "b_baseline":      opt["baseline"]["wingspan_m"],
            "b_optimum":       opt["optimum"]["wingspan_m"],
            "AR_baseline":     opt["baseline"]["aspect_ratio"],
            "AR_optimum":      opt["optimum"]["aspect_ratio"],
            "S_baseline":      opt["baseline"]["wing_area_m2"],
            "S_optimum":       opt["optimum"]["wing_area_m2"],
            "LD_baseline":     opt["baseline"]["L_over_D"],
            "LD_optimum":      opt["optimum"]["L_over_D"],
            "improvement_pct": opt["improvement_pct"],

            # ─── 重量 ───
            "wing_weight":         wts["structure_kg"]["wing"],
            "fuselage_weight":     wts["structure_kg"]["fuselage"],
            "htail_weight":        wts["structure_kg"]["h_tail"],
            "vtail_weight":        wts["structure_kg"]["v_tail"],
            "landing_gear_weight": wts["structure_kg"]["landing_gear"],
            "systems_weight":      wts["systems_kg"]["subtotal"],
            "propulsion_weight":   wts["propulsion_kg"]["subtotal"],
            "empty_weight":        wts["summary_kg"]["empty_weight"],
            "takeoff_calc":        wts["summary_kg"]["takeoff_calc"],
            "delta_pct":           wts["summary_kg"]["delta_pct"],
            "convergence_status":  "收敛" if abs(wts["summary_kg"]["delta_pct"]) <= 15 else "需迭代",

            # ─── 电推进 ───
            "cruise_power_kw":     prp["propulsion"].get("cruise_power_kw", "-"),
            "eta_motor":           prp["propulsion"].get("efficiency_chain", {}).get("motor", "-"),
            "eta_inverter":        prp["propulsion"].get("efficiency_chain", {}).get("inverter", "-"),
            "eta_propeller":       prp["propulsion"].get("efficiency_chain", {}).get("propeller", "-"),
            "eta_total":           prp["propulsion"].get("efficiency_chain", {}).get("total", "-"),
            "usable_kwh":          prp["propulsion"].get("battery_usable_kwh", "-"),
            "reserve_pct":         15,
            "estimated_range_km":  prp["estimated_range_km"],
            "design_range_km":     prp["design_range_km"],
            "range_margin_pct":    prp["range_margin_pct"],
        }

        # 重量占比
        for key in ["wing_weight", "fuselage_weight", "htail_weight", "vtail_weight",
                    "landing_gear_weight", "systems_weight", "propulsion_weight",
                    "empty_weight"]:
            pct_key = key + "_pct"
            try:
                flat[pct_key] = round(flat[key] / mtow * 100, 1)
            except (TypeError, ZeroDivisionError):
                flat[pct_key] = "-"

        # 设计建议
        recommendations = []
        if isinstance(flat["range_margin_pct"], (int, float)) and flat["range_margin_pct"] < -10:
            recommendations.append(
                f"a) 实际续航低于设计航程 {abs(flat['range_margin_pct']):.0f}%, "
                f"建议增加电池容量至约 "
                f"{flat['battery_kwh'] * flat['design_range_km'] / max(flat['estimated_range_km'], 1):.0f} kWh"
            )
        if isinstance(flat["delta_pct"], (int, float)) and abs(flat["delta_pct"]) > 15:
            recommendations.append(
                f"b) 重量收敛偏差 {flat['delta_pct']:+.1f}%, 建议迭代调整 MTOW 输入"
            )
        if isinstance(flat["improvement_pct"], (int, float)) and flat["improvement_pct"] < 5:
            recommendations.append(
                "c) 优化提升幅度有限, 建议扩大设计变量范围或引入更多约束"
            )
        if not recommendations:
            recommendations.append(
                "a) 当前方案各项指标符合设计目标, 可作为下一阶段详细设计的输入。"
            )

        flat["recommendations"] = "\n\n".join(recommendations)

        return flat

    # ════════════════════════════════════════════════
    # 占位符替换
    # ════════════════════════════════════════════════
    def _render(self, template: str, flat: dict) -> str:
        """把模板里的 {{key}} 替换成 flat[key] 的值"""

        def replace(match):
            key = match.group(1).strip()
            if key in flat:
                return str(flat[key])
            return f"<{key}?>"   # 找不到时显示占位符名, 方便调试

        return re.sub(r"\{\{([^}]+)\}\}", replace, template)
