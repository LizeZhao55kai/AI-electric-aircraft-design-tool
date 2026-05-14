# 1 范围

本报告记录 CE-25A 电动支线飞机的概念设计方案及计算结果。报告内容由 AI 智能设计平台基于工程经验公式 (Raymer / Roskam) 自动生成。

本报告适用于 CE-25A 飞机方案设计阶段的内部评审、参数对比与下一阶段输入参考。

# 2 引用文件

下列文件对于本文件的应用是必不可少的：

| 编号 | 文件名称 |
|---|---|
| AIAA-2017-3922 | Aircraft Design: A Conceptual Approach, 6th ed. (D. P. Raymer) |
| AIAA Education Series | Airplane Aerodynamics and Performance (J. Roskam) |
| ICAO Doc 7488 | Manual of the ICAO Standard Atmosphere |
| SUAVE 2.5.2 | Stanford University Aerospace Vehicle Environment |

# 3 术语和缩略语

| 缩略语 | 英文全称 | 中文释义 |
|---|---|---|
| MTOW | Maximum Take-Off Weight | 最大起飞重量 |
| L/D | Lift-to-Drag Ratio | 升阻比 |
| AR | Aspect Ratio | 展弦比 |
| CL | Lift Coefficient | 升力系数 |
| CD | Drag Coefficient | 阻力系数 |
| CD0 | Zero-Lift Drag Coefficient | 零升阻力系数 |
| CDi | Induced Drag Coefficient | 诱导阻力系数 |
| ISA | International Standard Atmosphere | 国际标准大气 |
| DOD | Depth Of Discharge | 电池放电深度 |

# 4 设计需求与目标

## 4.1 任务剖面与设计指标

本机为 {{aircraft_class}} 类电动支线飞机，主要设计指标如下：

a) 座位数：{{seats}} 座；

b) 设计航程：{{range_km}} km；

c) 巡航马赫数：{{cruise_mach}}；

d) 巡航高度：{{cruise_alt_m}} m；

e) 最大允许翼展：{{max_wingspan_m}} m；

f) 推进类型：电动，电池容量 {{battery_kwh}} kWh。

## 4.2 总体参数初值

依据 Raymer 经验公式以及典型电动支线飞机统计数据 [推理：基于历史飞机数据回归]，估算总体参数：

表 1 总体参数初值

| 项目 | 数值 | 单位 |
|---|---|---|
| 最大起飞重量 MTOW | {{mtow}} | kg |
| 翼面积 | {{wing_area}} | m² |
| 展弦比 AR | {{aspect_ratio}} | - |
| 翼载荷 W/S | {{wing_loading}} | kg/m² |

# 5 气动设计与分析

## 5.1 大气模型

巡航段采用国际标准大气 (ISA)，{{cruise_alt_m}} m 高度处：

a) 空气密度：{{rho}} kg/m³；

b) 巡航速度：{{velocity}} m/s；

c) 动压：{{dynamic_pressure}} Pa。

## 5.2 阻力分解

依据 Raymer Eq.12.39 et seq. 进行阻力分项估算，方法为湿面积法 + 平板摩擦修正：

表 2 阻力系数分解

| 项目 | 数值 | 备注 |
|---|---|---|
| 零升阻力系数 CD0 | {{CD0}} | 摩擦 + 形状 + 干扰 |
| 诱导阻力因子 K | {{K_induced}} | K = 1/(π·AR·e), e=0.85 |
| 跨声速波阻 | {{CD_wave}} | Korn 方程 |
| 总湿面积 | {{wetted_area}} | m² |

## 5.3 巡航点性能

表 3 巡航点气动性能

| 项目 | 数值 | 单位 |
|---|---|---|
| 巡航升力系数 CL | {{CL_cruise}} | - |
| 巡航阻力系数 CD | {{CD_cruise}} | - |
| 巡航升阻比 L/D | {{LD_cruise}} | - |
| 巡航攻角 α | {{alpha_cruise}} | ° |

## 5.4 阻力极曲线

通过对设计攻角范围进行扫描，得到完整的阻力极曲线，最大升阻比 {{max_LD}}。

# 6 气动优化

## 6.1 优化设置

a) 设计变量：翼展 b、展弦比 AR；

b) 约束条件：b ≤ {{max_wingspan_m}} m，6 ≤ AR ≤ 14；

c) 优化目标：最大化巡航 L/D；

d) 优化方法：Grid Search，共评估 {{n_evaluations}} 个设计点。

## 6.2 优化结果

表 4 优化前后对比

| 项目 | 优化前 | 优化后 |
|---|---|---|
| 翼展 b (m) | {{b_baseline}} | {{b_optimum}} |
| 展弦比 AR | {{AR_baseline}} | {{AR_optimum}} |
| 翼面积 S (m²) | {{S_baseline}} | {{S_optimum}} |
| 升阻比 L/D | {{LD_baseline}} | {{LD_optimum}} |

经优化后升阻比提升 {{improvement_pct}}%。

# 7 结构与重量估算

## 7.1 各部件重量

依据 Raymer Eq.15.46~15.49 经验公式估算各主要部件重量：

表 5 部件重量分解

| 部件 | 重量 (kg) | 占 MTOW |
|---|---|---|
| 主翼 | {{wing_weight}} | {{wing_weight_pct}}% |
| 机身 | {{fuselage_weight}} | {{fuselage_weight_pct}}% |
| 水平尾翼 | {{htail_weight}} | {{htail_weight_pct}}% |
| 垂直尾翼 | {{vtail_weight}} | {{vtail_weight_pct}}% |
| 起落架 | {{landing_gear_weight}} | {{landing_gear_weight_pct}}% |
| 系统 (含航电) | {{systems_weight}} | {{systems_weight_pct}}% |
| 推进系统 | {{propulsion_weight}} | {{propulsion_weight_pct}}% |
| 空机重量 OEW | {{empty_weight}} | {{empty_weight_pct}}% |

## 7.2 重量收敛检查

a) 估算起飞重量：{{takeoff_calc}} kg；

b) 输入 MTOW：{{mtow}} kg；

c) 收敛偏差：{{delta_pct}}%；

d) 收敛状态：{{convergence_status}}。

# 8 电推进系统

## 8.1 推进配置

a) 推进类型：电动 (双发，机翼上方布置)；

b) 巡航功率需求：{{cruise_power_kw}} kW；

c) 电池容量：{{battery_kwh}} kWh。

## 8.2 效率链

表 6 电推进系统效率分解

| 部件 | 效率 |
|---|---|
| 电机 (motor) | {{eta_motor}} |
| 控制器/逆变器 | {{eta_inverter}} |
| 螺旋桨 | {{eta_propeller}} |
| 总效率 η_total | {{eta_total}} |

## 8.3 续航分析

依据电动飞机 Breguet 续航公式：

```
Range = (E_battery × η_total) / (W × g) × L/D
```

a) 可用电池能量：{{usable_kwh}} kWh (扣 {{reserve_pct}}% 备用 + DOD)；

b) 估算最大巡航续航：{{estimated_range_km}} km；

c) 设计航程：{{design_range_km}} km；

d) 续航裕度：{{range_margin_pct}}%。

# 9 性能总结

表 7 关键性能指标汇总

| 项目 | 数值 | 单位 |
|---|---|---|
| 最大起飞重量 MTOW | {{mtow}} | kg |
| 空机重量 OEW | {{empty_weight}} | kg |
| 翼展 (优化后) | {{b_optimum}} | m |
| 翼面积 (优化后) | {{S_optimum}} | m² |
| 巡航升阻比 L/D | {{LD_optimum}} | - |
| 巡航功率 | {{cruise_power_kw}} | kW |
| 估算续航 | {{estimated_range_km}} | km |
| 重量收敛偏差 | {{delta_pct}} | % |

# 10 设计评估与结论

本次设计通过 5 步智能设计流程 (需求处理 → 气动分析 → 气动优化 → 重量估算 → 电推进任务分析) 完成，主要结论如下：

a) 总体重量{{convergence_status}}，偏差 {{delta_pct}}%；

b) 气动效率经优化后提升 {{improvement_pct}}%；

c) 电池容量与设计航程匹配度：{{range_margin_pct}}%。

设计建议：

{{recommendations}}

---

**报告生成说明：**

本报告由 CE-25A 智能设计平台 (L3 端到端 Agent) 自动生成，数据基于工程经验公式。报告内容采用三类信息来源标注：

a) 直接来自设计工具计算的数据，按数值直接呈现；

b) [推理：依据] 表示基于工程经验公式或理论模型的推导；

c) [常识推理：依据] 表示行业惯例或对缺失数据的合理估计。

如需更高精度计算 (高保真 CFD / FEM)，请将本方案输入下一阶段详细设计流程。
