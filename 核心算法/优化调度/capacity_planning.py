# -*- coding: utf-8 -*-
"""
容量规划：枚举不同 光伏规模 × 储能规模 方案，算投资回报率，找合理配置。

经济模型（分时电价版）：
  基准成本 = 无光伏无储能时，负荷按分时目录电价购电的总成本
  运行成本 = 优化后的分时购电成本 - 余电上网收益
  年节省   = 基准成本 - 运行成本
  回收期   = 投资 / 年节省

多目标优化：优化器目标 = w_cost×分时成本 + w_green×外购电量

枚举维度：
  光伏放大倍数 PV_SCALE ∈ [1.0, 1.5, 2.0, 2.5, 3.0]
  储能容量 E ∈ [0, 4000, 8000, 16000, 32000] kWh，功率 = 容量/2h
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from storage_optimizer import daily_opt_dispatch
from validate_optimizer import load_data_source
from mode_controller import ModeController


def annual_operation(pv_arr, load_arr, E_max, P_max, soc0, w_cost, w_green):
    """给定光伏倍率 + 储能规模，跑全年，返回全年电量+分时成本。"""
    day_num = len(pv_arr)
    soc_now = soc0
    buy = export = net = load_total = pv_total = cost_total = 0.0
    chg_total = dis_total = chg_pv_total = dis_replace_total = 0.0
    carbon_total = 0.0
    fail = 0
    mc = ModeController(
        flex_min=config.FLEX_MIN, flex_min_safe=config.FLEX_MIN_SAFE,
        flex_max=config.FLEX_MAX,
        flex_down_cont_h=config.FLEX_DOWN_CONT_H,
        load_shock_ratio=config.LOAD_SHOCK_RATIO,
        hysteresis_days=config.HYSTERESIS_DAYS,
        flex_energy_ratio=config.FLEX_ENERGY_RATIO,
    )
    for d in range(day_num):
        price = config.price_for_day(d)
        flex_min_override, flex_energy_ratio, mode, is_shock = mc.decide(load_arr[d])
        res = daily_opt_dispatch(
            pv_kw=pv_arr[d], load_kw=load_arr[d],
            E_max=E_max, P_max=P_max,
            eta_ch=config.ETA_CH, eta_dis=config.ETA_DIS,
            soc_min=config.SOC_MIN, soc_max=config.SOC_MAX,
            soc0=soc_now,
            price=price, w_cost=w_cost, w_green=w_green,
            w_carbon=config.W_CARBON, carbon_price=config.CARBON_PRICE,
            ef_opt=config.ef_opt_for_day(d),
            flex_min=config.FLEX_MIN, flex_max=config.FLEX_MAX, flex_penalty=config.FLEX_PENALTY,
            flex_enabled=config.FLEX_ENABLED,
            flex_min_override=flex_min_override,
            flex_dev_cost=config.FLEX_DEV_COST,
            flex_energy_ratio=flex_energy_ratio,
        )
        if res.get("soc") is None:
            fail += 1
            continue
        mc.update_after_optimize(res, load_kw=load_arr[d])
        soc_now = res["soc"][-1]
        buy += res["buy_kwh"]
        export += res["export_kwh"]
        net += res["net_grid_kwh"]
        load_total += res["flex"].sum()
        pv_total += pv_arr[d].sum()
        cost_total += res["cost_yuan"]
        carbon_total += res["carbon_kg"]
        chg_total += res["chg_kwh"]
        dis_total += res["dis_kwh"]
        chg_pv_total += res["chg_pv_kwh"]
        dis_replace_total += res["dis_replace_kwh"]

    return {
        "buy": buy, "export": export, "net": net,
        "load": load_total, "pv": pv_total, "fail": fail,
        "cost": cost_total,
        "carbon": carbon_total,
        "chg": chg_total, "dis": dis_total,
        "chg_pv": chg_pv_total, "dis_replace": dis_replace_total,
    }


def baseline_cost(load_arr):
    """无光伏无储能基准：全年负荷按逐日节点电价购电的总成本。"""
    return sum((load_arr[d] * config.price_for_day(d)).sum() for d in range(len(load_arr)))


def baseline_carbon(load_arr):
    """无光伏无储能基准：全年负荷按逐日碳因子购电的碳排放（kgCO2）。"""
    return sum((load_arr[d] * config.ef_opt_for_day(d)).sum() for d in range(len(load_arr)))


def capacity_planning():
    config.print_config()
    pv_arr_base, load_arr, day_num = load_data_source()

    # 基准：无光伏无储能，全年负荷全部按逐日节点电价购电
    base_cost = baseline_cost(load_arr)
    base_carbon = baseline_carbon(load_arr)
    print(f"\n基准（无光伏无储能）购电成本 = {base_cost/1e4:.0f} 万元/年")
    print(f"（等效平均购电价 {base_cost/load_arr.sum():.3f} 元/kWh）")
    print(f"基准（无光伏无储能）碳排放 = {base_carbon/1000:,.0f} 吨/年（碳价 {config.CARBON_PRICE*1000:.0f} 元/吨）")

    pv_scales = [1.0, 1.5, 2.0, 2.5, 3.0]
    batteries = [(0, 0), (4000, 2000), (8000, 4000), (16000, 8000), (32000, 16000)]

    print("\n" + "=" * 118)
    print("电碳双驱容量对比表（综合收益 = 电费节省 + 减碳价值）")
    print("=" * 118)
    header = (f"{'光伏MW':>6} {'储能kWh':>8} {'投资万':>7} {'省电费万':>8} {'减碳吨':>8} "
              f"{'综合收益万':>9} {'回收期':>7} {'绿电%':>6} {'无解':>4}")
    print(header)
    print("-" * 118)

    results = []
    for pv_scale in pv_scales:
        # pv_arr_base 已含 PV_SCALE 放大，这里按"相对真实基准的倍率"还原再放大，
        # 修正二次放大 bug（此前 pv_arr_base * pv_scale 把光伏翻倍虚高绿电占比）
        pv_arr = pv_arr_base / config.PV_SCALE * pv_scale
        for E_max, P_max in batteries:
            ops = annual_operation(pv_arr, load_arr, E_max, P_max,
                                   config.SOC_INIT,
                                   config.W_COST, config.W_GREEN)

            pv_capacity_kw = config.PV_BASE_CAPACITY_KW * pv_scale
            pv_invest = pv_capacity_kw * config.PV_INVEST_PER_KW
            bat_invest = E_max * config.BATTERY_E_INVEST_PER_KWH + P_max * config.BATTERY_P_INVEST_PER_KW
            total_invest = pv_invest + bat_invest

            # 运行成本 = 分时购电成本 - 余电上网收益
            run_cost = ops["cost"] - ops["export"] * config.PRICE_SELL
            annual_saving = base_cost - run_cost                      # 电费节省（元/年）
            carbon_saved = base_carbon - ops["carbon"]                # 减碳量（kgCO2/年）
            carbon_value = carbon_saved * config.CARBON_PRICE         # 减碳价值（元/年）
            combined_saving = annual_saving + carbon_value            # 综合收益（电碳双驱）
            payback = total_invest / combined_saving if combined_saving > 0 else float("inf")
            green = ops["pv"] / load_arr.sum() * 100   # 绿电占比=光伏发电÷原始负荷（统一口径）
            export_pct = ops["export"] / ops["pv"] * 100 if ops["pv"] > 0 else 0

            eco = {
                "pv_mw": pv_capacity_kw / 1000, "e_kwh": E_max, "p_kw": P_max,
                "invest_wan": total_invest / 1e4, "saving_wan": annual_saving / 1e4,
                "carbon_t": carbon_saved / 1000, "combined_wan": combined_saving / 1e4,
                "payback": payback, "green": green, "export_pct": export_pct,
                "fail": ops["fail"],
            }
            results.append(eco)

            pb = f"{payback:.1f}" if payback != float("inf") else "∞"
            print(f"{eco['pv_mw']:>6.1f} {E_max:>8.0f} {eco['invest_wan']:>7.0f} "
                  f"{eco['saving_wan']:>8.0f} {eco['carbon_t']:>8.0f} {eco['combined_wan']:>9.0f} "
                  f"{pb:>7} {eco['green']:>6.1f} {eco['fail']:>4}")

    print("-" * 118)

    # 帕累托前沿：两个目标 = 投资回报率(100/回收期) 和 绿电，都是越大越好
    pareto = []
    for r in results:
        irr = 100 / r["payback"] if r["payback"] != float("inf") else 0
        dominated = False
        for r2 in results:
            irr2 = 100 / r2["payback"] if r2["payback"] != float("inf") else 0
            if (irr2 >= irr and r2["green"] >= r["green"]) and (irr2 > irr or r2["green"] > r["green"]):
                dominated = True
                break
        if not dominated:
            r["irr"] = irr
            pareto.append(r)

    pareto.sort(key=lambda x: x["green"])
    print("\n=== 帕累托前沿（投资回报率↑ 与 绿电占比↑ 不可同时改进） ===")
    print(f"{'光伏MW':>7} {'储能kWh':>9} {'投资万':>7} {'收益率%':>7} {'绿电%':>6} {'回收期':>6}")
    for p in pareto:
        print(f"{p['pv_mw']:>7.1f} {p['e_kwh']:>9.0f} {p['invest_wan']:>7.0f} "
              f"{p['irr']:>7.1f} {p['green']:>6.1f} {p['payback']:>6.1f}")

    return results, pareto


if __name__ == "__main__":
    capacity_planning()
