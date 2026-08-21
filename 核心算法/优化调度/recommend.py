# -*- coding: utf-8 -*-
"""
容量推荐器总入口（模块二通用化核心）。

输入：厂名 + 可装光伏占地（公顷）→ 输出：推荐光伏装机 + 储能容量 + 经济指标。

任何厂（A/B/C/D）只要有负荷数据 + 占地，就能算最优配置：
光伏出力由 pv_output_model（辐射×装机×PR）生成，不依赖该厂历史光伏数据。

口径（关键）：
  - 刚性基准 = 无光伏无储能无柔性（负荷全额按电价购电）
  - 柔性基准 = 无光伏无储能，但启用柔性负荷（下调曝气 ~5%，零投资节能）
  - 光伏储能的「增量收益」= 相对柔性基准的节省（纯增量，不含柔性零投资节能）

用法：
    from recommend import recommend_capacity
    result = recommend_capacity("B", land_hectare=15)
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from factory_loader import load_factory
from pv_output_model import pv_output_from_radiation
from capacity_planning import annual_operation, baseline_cost, baseline_carbon


# 占地系数（kW/㎡）：实测 0.027（A 厂 8.12MW÷30公顷）/ 理论 0.035
PV_PER_SQM_ACTUAL = 0.027
PV_PER_SQM_THEORY = 0.035

# 默认储能枚举 [(E_kWh, P_kW), ...]：0/4/8/16/32 MWh，功率=容量/2h
DEFAULT_BATTERIES = [(0, 0), (4000, 2000), (8000, 4000), (16000, 8000), (32000, 16000)]


def recommend_capacity(factory, land_hectare, pv_per_sqm=PV_PER_SQM_ACTUAL,
                       batteries=None, pv_steps=8, verbose=True):
    """容量推荐器总入口。

    参数
    ----
    factory:        "A"/"B"/"C"（未来可加 D）
    land_hectare:   可装光伏占地（公顷）
    pv_per_sqm:     占地系数 kW/㎡（默认 0.027 实测，0.035 理论）
    batteries:      储能枚举 [(E_kWh, P_kW), ...]，默认 DEFAULT_BATTERIES
    pv_steps:       光伏装机枚举档数（0 到 上限 均匀取档）
    verbose:        是否打印方案表

    返回
    ----
    dict {recommended, schemes, factory, land_hectare, pv_max_kw,
          base_cost, flex_cost, flex_saving}
    """
    factory = factory.upper()
    batteries = batteries or DEFAULT_BATTERIES

    # 1. 读负荷 + 辐射
    data = load_factory(factory)
    load_arr = data["load"]
    rad_arr = data["rad"]

    # 2. 光伏上限 = 占地 × 系数
    land_sqm = land_hectare * 10000.0
    pv_max_kw = land_sqm * pv_per_sqm

    # 3. 两个基准
    base_cost = baseline_cost(load_arr)      # 刚性基准（无光伏无储能无柔性）
    base_carbon = baseline_carbon(load_arr)

    # 柔性基准：无光伏无储能，但柔性负荷已启用（零投资节能）
    zero_pv = np.zeros_like(rad_arr)
    flex_ops = annual_operation(zero_pv, load_arr, 0, 0,
                                config.SOC_INIT, config.W_COST, config.W_GREEN)
    flex_cost = flex_ops["cost"] - flex_ops["export"] * config.PRICE_SELL
    flex_carbon = flex_ops["carbon"]
    flex_saving = base_cost - flex_cost           # 柔性零投资节能（元/年）

    # 4. 枚举：光伏装机 × 储能，收益 = 相对柔性基准的增量
    pv_kws = np.linspace(0.0, pv_max_kw, pv_steps)
    schemes = []
    for pv_kw in pv_kws:
        pv_arr = pv_output_from_radiation(rad_arr, pv_kw, config.PV_SYSTEM_PR)
        for E_max, P_max in batteries:
            ops = annual_operation(pv_arr, load_arr, E_max, P_max,
                                   config.SOC_INIT, config.W_COST, config.W_GREEN)

            pv_invest = pv_kw * config.PV_INVEST_PER_KW
            bat_invest = E_max * config.BATTERY_E_INVEST_PER_KWH + P_max * config.BATTERY_P_INVEST_PER_KW
            total_invest = pv_invest + bat_invest

            run_cost = ops["cost"] - ops["export"] * config.PRICE_SELL
            annual_saving = flex_cost - run_cost               # 纯光伏储能增量（元/年）
            carbon_saved = flex_carbon - ops["carbon"]         # 纯增量减碳（kgCO2/年）
            carbon_value = carbon_saved * config.CARBON_PRICE  # 减碳价值（元/年）
            combined = annual_saving + carbon_value            # 综合收益（电碳双驱）
            green = ops["pv"] / load_arr.sum() * 100           # 绿电占比

            if total_invest > 0 and combined > 0:
                payback = total_invest / combined
                return_rate = 100.0 / payback
            else:
                payback = float("inf")
                return_rate = 0.0

            schemes.append({
                "pv_kw": pv_kw, "e_kwh": E_max, "p_kw": P_max,
                "invest_wan": total_invest / 1e4,
                "saving_wan": annual_saving / 1e4,
                "carbon_t": carbon_saved / 1000,
                "combined_wan": combined / 1e4,
                "payback": payback, "return_rate": return_rate, "green": green,
                "fail": ops["fail"],
            })

    # 5. 推荐 = 收益率 ≥ 目标门槛(IRR_TARGET) 的方案里，综合收益(绝对)最大
    #    收益率达标后，装越多赚越多；若全部不达标，退而选收益率最高者
    investable = [s for s in schemes if s["pv_kw"] > 0 or s["e_kwh"] > 0]
    irr_floor = config.IRR_TARGET * 100.0
    eligible = [s for s in investable if s["return_rate"] >= irr_floor]
    if eligible:
        best = max(eligible, key=lambda s: s["combined_wan"])
    else:
        best = max(investable, key=lambda s: s["return_rate"])

    # 6. 输出
    if verbose:
        print("=" * 92)
        print(f"容量推荐：{factory} 厂 | 占地 {land_hectare} 公顷 | 系数 {pv_per_sqm} kW/㎡"
              f" | 光伏上限 {pv_max_kw/1000:.1f} MW")
        print(f"负荷峰值 {load_arr.max():.0f} kW | 年用电 {load_arr.sum()/1e4:.0f} 万 kWh")
        print(f"刚性基准成本 {base_cost/1e4:.0f} 万/年 | 柔性基准成本 {flex_cost/1e4:.0f} 万/年"
              f"（柔性零投资节能 {flex_saving/1e4:.0f} 万/年）")
        print("=" * 92)
        print("下表「省电费/减碳/综合」均为**相对柔性基准的增量**（不含柔性零投资节能）")
        header = (f"{'光伏MW':>7}{'储能kWh':>8}{'投资万':>7}{'省电费万':>8}{'减碳吨':>8}"
                  f"{'综合万':>8}{'收益率%':>8}{'回收期':>7}{'绿电%':>7}{'无解':>5}")
        print(header)
        print("-" * 92)
        for s in schemes:
            pb = f"{s['payback']:.1f}" if s["payback"] != float("inf") else "∞"
            print(f"{s['pv_kw']/1000:>7.1f}{s['e_kwh']:>8.0f}{s['invest_wan']:>7.0f}"
                  f"{s['saving_wan']:>8.0f}{s['carbon_t']:>8.0f}{s['combined_wan']:>8.0f}"
                  f"{s['return_rate']:>8.1f}{pb:>7}{s['green']:>7.1f}{s['fail']:>5}")
        print("-" * 92)
        print(f"\n★ 推荐：光伏 {best['pv_kw']/1000:.1f} MW + 储能 {best['e_kwh']/1000:.1f} MWh")
        print(f"  综合收益率 {best['return_rate']:.1f}%（回收期 {best['payback']:.1f} 年）"
              f" | 绿电 {best['green']:.1f}% | 减碳 {best['carbon_t']:.0f} 吨/年")

    return {
        "recommended": best,
        "schemes": schemes,
        "factory": factory,
        "land_hectare": land_hectare,
        "pv_max_kw": pv_max_kw,
        "base_cost": base_cost,
        "flex_cost": flex_cost,
        "flex_saving": flex_saving,
    }


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    # 默认演示 A 厂（30 公顷，实测系数）；命令行可传 厂名 占地 系数
    _f = sys.argv[1] if len(sys.argv) > 1 else "A"
    _land = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    _coef = float(sys.argv[3]) if len(sys.argv) > 3 else PV_PER_SQM_ACTUAL
    recommend_capacity(_f, _land, _coef)
