# -*- coding: utf-8 -*-
"""
优化层全年回测验证。

用 data_source.xlsx 的真实光伏+负荷数据，逐日滚动跑 365 天，
输出全年汇总指标，用于：
  1. 验证 storage_optimizer.py 从 text.m 迁移的正确性
  2. 复现 text.m 的全年仿真结果（含余电上网）
"""

import sys
import os
import numpy as np
import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from storage_optimizer import daily_opt_dispatch
from mode_controller import ModeController


def load_data_source():
    """读 A_中嘉污水厂.xlsx 的「逐时数据」，返回全年光伏(kW)+实际用电量(kW) 数组。

    光伏 = 光伏发电列(MWh)×1000 → kW（一期+二期+车棚三站真实合计），
           再乘 PV_SCALE 放大到规划装机。
    负荷 = 实际用电量列(MWh)×1000 → kW（总负荷，含光伏自发自用）。
    """
    wb = openpyxl.load_workbook(config.DATA_SOURCE_XLSX, read_only=True, data_only=True)
    ws = wb["逐时数据"]

    pv_list = []
    load_list = []
    for row in ws.iter_rows(min_row=3, values_only=True):  # 前 2 行是表头(类型+小时)
        if row[0] is None:
            continue
        # 列布局: 0日期 | 1-24电网电量 | 25-48光伏发电 | 49-72实际用电量
        pv = [0.0 if v is None else float(v) for v in row[25:49]]   # 光伏发电(MWh)
        ld = [0.0 if v is None else float(v) for v in row[49:73]]   # 实际用电量(MWh)
        if len(pv) == 24 and len(ld) == 24:
            pv_list.append(pv)
            load_list.append(ld)
    wb.close()

    pv_arr = np.array(pv_list) * 1000.0 * config.PV_SCALE   # MWh→kW，×规划放大
    load_arr = np.array(load_list) * 1000.0                 # MWh→kW

    day_num = len(pv_arr)
    return pv_arr, load_arr, day_num


def backtest_full_year():
    config.print_config()
    pv_arr, load_arr, day_num = load_data_source()
    print(f"\n数据载入：{day_num} 天，光伏峰值 {pv_arr.max():.0f} kW，负荷峰值 {load_arr.max():.0f} kW")

    # 逐日滚动
    soc_now = config.SOC_INIT
    buy_total = 0.0
    export_total = 0.0
    net_total = 0.0
    load_total = 0.0
    pv_total = 0.0
    cost_total = 0.0   # 分时购电成本
    fail_days = 0
    chg_total = 0.0    # 储能年充电量
    dis_total = 0.0    # 储能年放电量
    chg_pv_total = 0.0  # 充电中来自光伏的量
    dis_replace_total = 0.0  # 放电替代的购电量
    # 双模式状态机
    mc = ModeController(
        flex_min=config.FLEX_MIN, flex_min_safe=config.FLEX_MIN_SAFE,
        flex_max=config.FLEX_MAX,
        flex_down_cont_h=config.FLEX_DOWN_CONT_H,
        load_shock_ratio=config.LOAD_SHOCK_RATIO,
        hysteresis_days=config.HYSTERESIS_DAYS,
        flex_energy_ratio=config.FLEX_ENERGY_RATIO,
    )
    safe_days = 0      # 安全模式天数
    shock_days = 0     # 冲击负荷豁免天数
    flex_down_total = 0.0  # 全年曝气下调总量（kWh），度量柔性调节幅度

    # 分时电价：逐日读取真实节点现货价（缺省回退固定峰谷价）
    baseline_cost_total = 0.0  # 无光伏无储能基准成本（逐日电价累加）

    for d in range(day_num):
        pv = pv_arr[d]
        load = load_arr[d]
        price = config.price_for_day(d)
        baseline_cost_total += (load * price).sum()

        # 双模式判定：决定今日曝气下限 + 总量下调比例
        flex_min_override, flex_energy_ratio, mode, is_shock = mc.decide(load)
        if mode == 'safe':
            safe_days += 1
        if is_shock:
            shock_days += 1

        res = daily_opt_dispatch(
            pv_kw=pv, load_kw=load,
            E_max=config.E_BAT_MAX, P_max=config.P_BAT_MAX,
            eta_ch=config.ETA_CH, eta_dis=config.ETA_DIS,
            soc_min=config.SOC_MIN, soc_max=config.SOC_MAX,
            soc0=soc_now, price=price, w_cost=config.W_COST, w_green=config.W_GREEN,
            w_carbon=config.W_CARBON, carbon_price=config.CARBON_PRICE,
            ef_opt=config.ef_opt_for_day(d),
            flex_min=config.FLEX_MIN, flex_max=config.FLEX_MAX, flex_penalty=config.FLEX_PENALTY,
            flex_enabled=config.FLEX_ENABLED,
            flex_min_override=flex_min_override,
            flex_dev_cost=config.FLEX_DEV_COST,
            flex_energy_ratio=flex_energy_ratio,
        )
        if res.get("soc") is None:
            fail_days += 1
            continue

        # 更新状态机：记录今日压曝气小时数，供明日低曝气判定
        mc.update_after_optimize(res, load_kw=load)

        # 下一天的 SOC 初值 = 今天末 SOC
        soc_now = res["soc"][-1]

        buy_total += res["buy_kwh"]
        export_total += res["export_kwh"]
        net_total += res["net_grid_kwh"]
        load_total += res["flex"].sum()   # 柔性可调后的实际用电量
        pv_total += pv.sum()
        cost_total += res["cost_yuan"]
        chg_total += res["chg_kwh"]
        dis_total += res["dis_kwh"]
        chg_pv_total += res["chg_pv_kwh"]
        dis_replace_total += res["dis_replace_kwh"]
        flex_down_total += res["flex_down"].sum()

    # ---- 汇总 ----
    green_ratio = (load_total - net_total) / load_total * 100
    print("\n" + "=" * 50)
    print("全年回测汇总结果（分时电价 + 多目标）")
    print("=" * 50)
    print(f"总天数: {day_num}, 无解天数: {fail_days}")
    print(f"全年光伏发电量: {pv_total:,.0f} kWh ({pv_total/load_total*100:.1f}% 负荷)")
    print(f"全年负荷用电量: {load_total:,.0f} kWh")
    print(f"全年买电量: {buy_total:,.0f} kWh")
    print(f"全年余电上网量: {export_total:,.0f} kWh ({export_total/pv_total*100:.1f}% 光伏)")
    print(f"全年净购电量: {net_total:,.0f} kWh")
    print(f"全年分时购电成本: {cost_total:,.0f} 元 ({cost_total/1e4:.0f} 万元)")
    print(f"绿电占比(自发自用): {green_ratio:.2f} %")

    # 双模式统计（专利1 迁移产物）
    print("\n" + "=" * 50)
    print("双模式滞回调度统计")
    print("=" * 50)
    print(f"安全模式天数: {safe_days} / {day_num} ({safe_days/day_num*100:.1f}%)")
    print(f"  其中冲击负荷豁免天数: {shock_days}")
    print(f"节能模式天数: {day_num - safe_days} / {day_num} ({(day_num-safe_days)/day_num*100:.1f}%)")
    print(f"全年曝气下调总量: {flex_down_total:,.0f} kWh ({flex_down_total/load_total*100:.2f}% 负荷)")
    print(f"  （柔性负荷在光伏富余时段主动下调曝气、消纳绿电的幅度）")

    # 对比：无光伏无储能的基准成本（负荷按逐日节点电价全额购电）
    baseline_cost = baseline_cost_total
    print(f"\n基准(无光伏无储能)购电成本: {baseline_cost:,.0f} 元")
    print(f"年节省: {baseline_cost - cost_total:,.0f} 元 ({(baseline_cost-cost_total)/1e4:.0f} 万元)")

    # 储能减碳贡献（供后置碳核算拆分"储能单独减排"，docx 第三节）
    print("\n" + "=" * 50)
    print("储能减碳贡献（单独统计）")
    print("=" * 50)
    print(f"储能年充电总量: {chg_total:,.0f} kWh")
    print(f"  其中来自光伏充电: {chg_pv_total:,.0f} kWh ({chg_pv_total/chg_total*100 if chg_total>0 else 0:.1f}% 充电量)")
    print(f"储能年放电总量: {dis_total:,.0f} kWh")
    print(f"  其中被负荷吸收(替代购电): {dis_replace_total:,.0f} kWh")
    print(f"储能单独减排贡献(光伏充入储能量): {chg_pv_total:,.0f} kWh ({chg_pv_total/load_total*100:.2f}% 负荷)")

    return {
        "buy": buy_total, "export": export_total, "net": net_total,
        "load": load_total, "pv": pv_total, "green": green_ratio,
        "cost": cost_total, "baseline_cost": baseline_cost,
        "fail_days": fail_days,
        "chg": chg_total, "dis": dis_total,
        "chg_pv": chg_pv_total, "dis_replace": dis_replace_total,
        "safe_days": safe_days, "shock_days": shock_days,
        "flex_down": flex_down_total,
    }


if __name__ == "__main__":
    backtest_full_year()
