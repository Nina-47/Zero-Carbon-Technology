# -*- coding: utf-8 -*-
"""
阶段4灵敏度对比：有无储能/柔性的外购差异。

场景对比（都用全年 365 天回测）：
  A 基准       无光伏/无储能/无柔性
  B 只有光伏    光伏 12.2MW，无储能无柔性
  C 光+储      光伏 12.2MW + 储能 16MWh，无柔性
  D 光+储+柔   光伏 12.2MW + 储能 16MWh + 柔性(双模式)  ← 完整方案

产出：外购电量 / 绿电占比 / 购电成本 三类指标的年对比，
加上储能、柔性各自的边际贡献，用于答辩「1图+3数字」。
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from storage_optimizer import daily_opt_dispatch
from validate_optimizer import load_data_source
from mode_controller import ModeController


def run_scenario(use_pv, use_storage, use_flex):
    """跑一整年，返回 (外购电量kWh, 绿电占比%, 购电成本元, 年节省元)。"""
    pv_arr, load_arr, day_num = load_data_source()
    soc_now = config.SOC_INIT
    buy = export = net = load_total = pv_total = cost_total = flex_down_total = 0.0
    base_cost = 0.0
    mc = ModeController(
        flex_min=config.FLEX_MIN, flex_min_safe=config.FLEX_MIN_SAFE,
        flex_max=config.FLEX_MAX,
        flex_down_cont_h=config.FLEX_DOWN_CONT_H,
        load_shock_ratio=config.LOAD_SHOCK_RATIO,
        hysteresis_days=config.HYSTERESIS_DAYS,
        flex_energy_ratio=config.FLEX_ENERGY_RATIO,
    )

    for d in range(day_num):
        pv = pv_arr[d] if use_pv else np.zeros(24)
        load = load_arr[d]
        price = config.price_for_day(d)
        base_cost += (load * price).sum()
        E = config.E_BAT_MAX if use_storage else 0.0
        P = config.P_BAT_MAX if use_storage else 0.0

        flex_enabled = use_flex
        flex_min_override = None
        flex_energy_ratio = 1.0
        if use_flex:
            flex_min_override, flex_energy_ratio, mode, is_shock = mc.decide(load)

        res = daily_opt_dispatch(
            pv_kw=pv, load_kw=load,
            E_max=E, P_max=P,
            eta_ch=config.ETA_CH, eta_dis=config.ETA_DIS,
            soc_min=config.SOC_MIN, soc_max=config.SOC_MAX,
            soc0=soc_now, price=price, w_cost=config.W_COST, w_green=config.W_GREEN,
            flex_min=config.FLEX_MIN, flex_max=config.FLEX_MAX, flex_penalty=config.FLEX_PENALTY,
            flex_enabled=flex_enabled,
            flex_min_override=flex_min_override,
            flex_dev_cost=config.FLEX_DEV_COST,
            flex_energy_ratio=flex_energy_ratio,
        )
        if res.get("soc") is None:
            continue
        if use_flex:
            mc.update_after_optimize(res, load_kw=load)
        soc_now = res["soc"][-1]
        buy += res["buy_kwh"]
        export += res["export_kwh"]
        net += res["net_grid_kwh"]
        load_total += res["flex"].sum()
        pv_total += pv.sum()
        cost_total += res["cost_yuan"]
        flex_down_total += res["flex_down"].sum()

    green = (load_total - net) / load_total * 100 if load_total > 0 else 0.0
    # 基准成本用"无光伏无储能"的全额购电（逐日节点电价）
    saving = base_cost - cost_total
    return buy, green, cost_total, saving, flex_down_total


def main():
    config.print_config()
    scenarios = [
        ("A 基准(无光无储无柔)", False, False, False),
        ("B 只有光伏",           True,  False, False),
        ("C 光+储",              True,  True,  False),
        ("D 光+储+柔(完整)",      True,  True,  True),
    ]

    print("\n" + "=" * 90)
    print("阶段4灵敏度对比")
    print("=" * 90)
    print(f"{'场景':<24} {'外购电量万kWh':>12} {'绿电占比%':>9} {'购电成本万':>10} {'年节省万':>9} {'曝气下调万kWh':>12}")
    print("-" * 90)

    results = {}
    for name, use_pv, use_storage, use_flex in scenarios:
        buy, green, cost, saving, flex_down = run_scenario(use_pv, use_storage, use_flex)
        results[name] = {"buy": buy, "green": green, "cost": cost, "saving": saving, "flex_down": flex_down}
        print(f"{name:<24} {buy/1e7:>12.1f} {green:>9.2f} {cost/1e4:>10.0f} {saving/1e4:>9.0f} {flex_down/1e6:>12.1f}")

    print("-" * 90)

    # ---- 边际贡献（用于答辩"3数字"）----
    base = results["A 基准(无光无储无柔)"]
    only_pv = results["B 只有光伏"]
    pv_bat = results["C 光+储"]
    full = results["D 光+储+柔(完整)"]

    print("\n=== 边际贡献拆解（答辩 3 数字）===")
    pv_effect = only_pv["green"] - base["green"]
    bat_effect = pv_bat["green"] - only_pv["green"]
    flex_effect = full["green"] - pv_bat["green"]
    print(f"① 光伏的绿电贡献      : +{pv_effect:.2f} 个百分点（从 0 到 {only_pv['green']:.2f}%）")
    print(f"② 储能：绿电微变 {bat_effect:+.2f}pp，但省钱 +{(pv_bat['saving']-only_pv['saving'])/1e4:.0f} 万（储能本质是削峰省钱，不是提绿电）")
    print(f"③ 柔性的绿电贡献      : +{flex_effect:.2f} 个百分点，且再省钱 +{(full['saving']-pv_bat['saving'])/1e4:.0f} 万（唯一既提绿电又省钱的手段）")

    print("\n=== 年节省贡献（万元/年）===")
    print(f"光伏带来      : {only_pv['saving']/1e4:.0f} 万")
    print(f"+储能         : {pv_bat['saving']/1e4:.0f} 万 (增量 {(pv_bat['saving']-only_pv['saving'])/1e4:.0f})")
    print(f"+柔性         : {full['saving']/1e4:.0f} 万 (增量 {(full['saving']-pv_bat['saving'])/1e4:.0f})")

    # ---- 生成对比图 ----
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
        plt.rcParams['axes.unicode_minus'] = False

        labels = ["A 基准", "B 光+储", "C 光+储\n+柔性(完整)", "D 光+储+柔\n(目标方案)"]
        names = list(results.keys())
        greens = [results[n]["green"] for n in names]
        savings = [results[n]["saving"] / 1e4 for n in names]

        fig, ax1 = plt.subplots(figsize=(8, 5))
        x = np.arange(len(names))
        bars = ax1.bar(x, greens, 0.5, color='#4C9F70', label='绿电占比 %')
        ax1.set_ylabel('绿电占比 %', color='#4C9F70')
        ax1.set_ylim(0, 30)
        ax1.set_xticks(x)
        ax1.set_xticklabels([n.split('(')[0] for n in names])
        ax1.tick_params(axis='y', labelcolor='#4C9F70')

        ax2 = ax1.twinx()
        ax2.plot(x, savings, 'o--', color='#D1495B', label='年节省(万)')
        ax2.set_ylabel('年节省(万元)', color='#D1495B')
        ax2.tick_params(axis='y', labelcolor='#D1495B')

        for i, (g, s) in enumerate(zip(greens, savings)):
            ax1.text(i, g + 0.5, f'{g:.1f}%', ha='center', fontsize=9)
            ax2.text(i, s + 60, f'{s:.0f}万', ha='center', fontsize=9, color='#D1495B')

        plt.title('光/储/柔 三要素的绿电占比与年节省对比')
        fig.savefig(os.path.join(config.OUTPUT_DIR, '阶段4灵敏度对比.png'), dpi=150)
        plt.close(fig)
        print(f"\n图表已保存: {os.path.join(config.OUTPUT_DIR, '阶段4灵敏度对比.png')}")
    except Exception as e:
        print(f"\n[图表生成失败] {e}")

    return results


if __name__ == "__main__":
    main()
