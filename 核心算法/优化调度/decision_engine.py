# -*- coding: utf-8 -*-
"""
决策引擎：串联 预测 → 优化 → 操作建议

当前版本（用历史数据演示流程）：
  - 负荷：用历史某天的实际负荷（暂代机器学习预测）
  - 光伏：用 KNN 相似日预测（pv_forecast）
  - 优化：daily_opt_dispatch
  - 输出：明日逐时操作建议

后续替换：负荷预测接 load_forecast.run_forecast()，光伏接实时天气预报。
"""

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from storage_optimizer import daily_opt_dispatch
from validate_optimizer import load_data_source
from pv_forecast import load_pv_data, forecast_day
from mode_controller import ModeController


def run_daily_decision(target_day_idx=-1, k=5, prev_mode=None, prev_low_hours=0,
                       use_load_forecast=False):
    """
    生成某一天的"明日运行决策"。

    target_day_idx: 目标日在全年数据中的下标（默认最后一天）
    k: 光伏预测 KNN 相似日个数
    prev_mode: 昨日双模式状态('eco'/'safe'/None)。用于跨天滞回，None=从节能模式起算
    prev_low_hours: 昨日压曝气小时数（供今日低曝气判定）
    use_load_forecast: 是否用负荷预测(load_forecast,三厂口径示范) 替代历史实际负荷。默认 False。

    返回 dict: 含逐时建议表 + 汇总指标 + 匹配相似日
    """
    # ---- 1. 负荷 ----
    pv_arr, load_arr, day_num = load_data_source()
    target_idx = target_day_idx % day_num

    if use_load_forecast:
        # 负荷预测：三厂合计口径示范流程（load_forecast），缩放回单厂量级
        from load_forecast import load_load_weather, forecast_next_day
        lw = load_load_weather()
        pred_load_3plant, load_matched = forecast_next_day(lw, k=k)
        # 单厂/三厂 缩放系数（data_source 单厂日总 ~195 MW vs 三厂 ~519 MW）
        scale = float(load_arr[target_idx].sum()) / (pred_load_3plant.sum() + 1e-6)
        load_24h = pred_load_3plant * scale
        load_source = "预测(三厂缩放)"
    else:
        load_24h = load_arr[target_idx]  # kW，历史实际（默认）
        load_source = "历史实际"

    # ---- 2. 光伏预测（KNN 相似日） ----

    # ---- 2. 光伏预测（KNN 相似日） ----
    # 负荷数据源 2025-07-01~2026-06-30 (365天)，光伏CSV 2025-07-05~2026-06-30 (361天)
    # 两个都到 2026-06-30，故取尾部共同 361 天对齐，负荷比光伏早 4 天
    pv_df = load_pv_data(config.PV_WEATHER_CSV)
    # 光伏CSV中与负荷 target_idx 对齐的下标（负荷末天=光伏末天）
    offset = day_num - len(pv_df)
    pv_idx = target_idx - offset
    if pv_idx < 0 or pv_idx >= len(pv_df):
        pv_idx = len(pv_df) - 1
    target_date = pv_df["日期"].iloc[pv_idx]
    pred_pv, actual_pv, matched_dates = forecast_day(pv_df, target_date, k=k)
    # 光伏已是三站合计真实出力（CSV≈8.12MWp 装机），与回测链路一致，
    # 直接 × PV_SCALE(=1.0)；旧代码 ×2 会虚高光伏（已修正）
    pv_scale_factor = config.PV_SCALE
    pv_24h = pred_pv * pv_scale_factor

    # ---- 3. 双模式判定（跨天滞回，与回测链路一致） ----
    mc = ModeController(
        flex_min=config.FLEX_MIN, flex_min_safe=config.FLEX_MIN_SAFE,
        flex_max=config.FLEX_MAX,
        flex_down_cont_h=config.FLEX_DOWN_CONT_H,
        load_shock_ratio=config.LOAD_SHOCK_RATIO,
        hysteresis_days=config.HYSTERESIS_DAYS,
        flex_energy_ratio=config.FLEX_ENERGY_RATIO,
    )
    if prev_mode is not None:
        mc.mode = prev_mode
    mc.last_low_hours = prev_low_hours
    flex_min_override, flex_energy_ratio, mode, is_shock = mc.decide(load_24h)

    # ---- 4. 优化调度 ----
    price = config.price_for_day(target_idx)
    res = daily_opt_dispatch(
        pv_kw=pv_24h, load_kw=load_24h,
        E_max=config.E_BAT_MAX, P_max=config.P_BAT_MAX,
        eta_ch=config.ETA_CH, eta_dis=config.ETA_DIS,
        soc_min=config.SOC_MIN, soc_max=config.SOC_MAX,
        soc0=config.SOC_INIT,
        price=price, w_cost=config.W_COST, w_green=config.W_GREEN,
        w_carbon=config.W_CARBON, carbon_price=config.CARBON_PRICE,
        ef_opt=config.ef_opt_for_day(target_idx),
        flex_min=config.FLEX_MIN, flex_max=config.FLEX_MAX, flex_penalty=config.FLEX_PENALTY,
        flex_enabled=config.FLEX_ENABLED,
        flex_min_override=flex_min_override,
        flex_dev_cost=config.FLEX_DEV_COST,
        flex_energy_ratio=flex_energy_ratio,
    )

    if res.get("soc") is None:
        return {"error": "优化求解失败"}

    # ---- 5. 组装逐时建议表 ----
    rows = []
    for t in range(24):
        pch, pdis = res["pch"][t], res["pdis"][t]
        if pch > 1:
            battery_action = f"充电 {pch:.0f} kW"
        elif pdis > 1:
            battery_action = f"放电 {pdis:.0f} kW"
        else:
            battery_action = "静置"

        if res["psell"][t] > 1:
            pv_action = f"余电上网 {res['psell'][t]:.0f} kW"
        else:
            pv_action = "全部自用" if pv_24h[t] > 1 else "无光伏"

        rows.append({
            "小时": t,
            "预测负荷_kW": round(load_24h[t]),
            "预测光伏_kW": round(pv_24h[t]),
            "储能动作": battery_action,
            "购电_kW": round(res["pgrid"][t]),
            "光伏去向": pv_action,
            "曝气下调_kW": round(res["flex_down"][t]),
            "SOC": round(res["soc"][t], 3),
        })

    # ---- 汇总 ----
    summary = {
        "目标日": str(target_date),
        "匹配相似日": matched_dates,
        "预测日总光伏_kWh": round(pv_24h.sum()),
        "预测日总负荷_kWh": round(load_24h.sum()),
        "负荷来源": load_source,
        "外购电量_kWh": round(res["buy_kwh"]),
        "余电上网_kWh": round(res["export_kwh"]),
        "绿电占比_pct": round(res["green_ratio"], 2),
        "分时购电成本_元": round(res["cost_yuan"]),
        "运行模式": "安全" if mode == 'safe' else "节能",
        "冲击负荷豁免": is_shock,
        "曝气下限": round(flex_min_override * 100),
        "当日储能充电总量_kWh": round(res["chg_kwh"]),
    }

    return {"hourly": rows, "summary": summary, "res": res}


def print_decision(result):
    """打印可读的操作建议。"""
    if "error" in result:
        print(result["error"])
        return
    s = result["summary"]
    print("\n" + "=" * 60)
    print(f"【明日运行方案】{s['目标日']}  运行模式:{s['运行模式']}")
    print("=" * 60)
    print(f"光伏预测：日总 {s['预测日总光伏_kWh']} kWh（匹配相似日：{', '.join(s['匹配相似日'])}）")
    print(f"负荷预测：日总 {s['预测日总负荷_kWh']} kWh（来源：{s['负荷来源']}）")
    print(f"曝气下限：{s['曝气下限']}%，冲击豁免：{'是' if s['冲击负荷豁免'] else '否'}")
    print()
    print(f"{'时':>3} {'负荷kW':>7} {'光伏kW':>7} {'储能动作':>16} {'购电kW':>7} {'曝气降kW':>8} {'光伏去向':>14} {'SOC':>6}")
    for r in result["hourly"]:
        print(f"{r['小时']:>3} {r['预测负荷_kW']:>7} {r['预测光伏_kW']:>7} "
              f"{r['储能动作']:>16} {r['购电_kW']:>7} {r['曝气下调_kW']:>8} {r['光伏去向']:>14} {r['SOC']:>6}")
    print()
    print(f"今日小结：")
    print(f"  外购电量 {s['外购电量_kWh']} kWh，余电上网 {s['余电上网_kWh']} kWh")
    print(f"  绿电占比 {s['绿电占比_pct']}%")
    print(f"  分时购电成本 {s['分时购电成本_元']:.0f} 元")
