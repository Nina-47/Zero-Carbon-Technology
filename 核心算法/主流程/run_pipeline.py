# -*- coding: utf-8 -*-
"""
四模块闭环主流程：负荷预测 → 优化调度 → 碳核算。

跑通 A 厂的完整数据流：
  1. 用历史负荷（实际用电量列）预测目标期逐时负荷
  2. 基于预测负荷 + 目标期辐射/电价做光储优化调度
  3. 把调度结果送入碳核算，得出省电费 / 减碳 / 绿电占比
  4. 输出一份「全流程结果」JSON，供网页大屏消费

目标期：数据末尾 FORECAST_HORIZON 天（默认 31 天 = 7 月，有真实负荷可验证预测精度）。

用法：
  python run_pipeline.py [厂名] [预测天数] [训练天数]
  默认：A 厂，预测 31 天，训练窗口 91 天（4-6 月）。

设计要点：
  - 只做「胶水」，复用 负荷预测/优化调度/碳核算 三个模块的既有函数，不重写核心算法。
  - 负荷/辐射/电价三份数据均已覆盖到 2026-07-31，故 7 月闭环有真实数据支撑。
  - 两个模块各有 config.py（同名），用 importlib 以别名加载，规避模块名冲突。
"""

import importlib.util
import io
import json
import os
import sys

import numpy as np
import pandas as pd

# ---- 中文输出（Windows 控制台）----
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ---- 路径 ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # 主流程/
CODE_DIR = os.path.dirname(BASE_DIR)                        # 03_预测代码/
PROJECT_ROOT = os.path.dirname(CODE_DIR)                    # 项目根
DISPATCH_DIR = os.path.join(CODE_DIR, "优化调度")
FORECAST_DIR = os.path.join(CODE_DIR, "负荷预测")
CARBON_DIR = os.path.join(CODE_DIR, "碳核算")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "04_预测输出", "V4_优化调度")

# ---- 可配置参数 ----
FACTORY = "A"              # 厂名（A/B/C）
FORECAST_HORIZON = 31      # 预测天数（7 月 = 31 天）
TRAIN_DAYS = 91            # 训练窗口天数（4-6 月 = 91 天）
PV_CAPACITY_KW = 8120.0    # 光伏装机 kW（A 厂真实台账 8.12 MWp）


def _load_as(name, path):
    """把某路径的 .py 以指定模块名加载并注册进 sys.modules（规避同名 config 冲突）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# ---- 加载三个模块（顺序关键：先用调度 config 占住 "config" 名，再被碳核算 config 覆盖）----
dispatch_cfg = _load_as("config", os.path.join(DISPATCH_DIR, "config.py"))
sys.path.insert(0, DISPATCH_DIR)
from factory_loader import load_factory                  # 内部 import config → 命中调度 config
from storage_optimizer import daily_opt_dispatch         # 纯函数（不依赖 config）
from pv_output_model import pv_output_from_radiation     # 纯函数

sys.path.insert(0, FORECAST_DIR)
from prediction.load_forecast import run_forecast, prepare_load_data  # 纯函数

_carbon_cfg = _load_as("config", os.path.join(CARBON_DIR, "config.py"))  # 覆盖 sys.modules["config"]
sys.path.insert(0, CARBON_DIR)
from carbon_accounting import CarbonAccounting            # import config as C → 命中碳核算 config


def main():
    # ============================================================
    # 1. 读数据（负荷 + 辐射，实际用电量口径）
    # ============================================================
    data = load_factory(FACTORY)
    load_arr = data["load"]       # (N, 24) kW
    rad_arr = data["rad"]         # (N, 24) W/m²
    dates = data["dates"]         # list[datetime.date]
    n_days = data["day_num"]
    print(f"负荷数据：{FACTORY} 厂 {n_days} 天，{dates[0]} ~ {dates[-1]}")

    # 切训练 / 预测窗口
    fc_start = n_days - FORECAST_HORIZON             # 预测期首日下标
    train_start = max(0, fc_start - TRAIN_DAYS)      # 训练期首日下标
    print(f"训练窗口：{dates[train_start]} ~ {dates[fc_start - 1]}"
          f"（{fc_start - train_start} 天） → 预测期：{dates[fc_start]} ~ {dates[-1]}"
          f"（{FORECAST_HORIZON} 天）")

    # ============================================================
    # 2. 负荷预测（训练期历史 → 目标期逐时负荷）
    # ============================================================
    print("\n[1/4] 负荷预测中...")
    rows = []
    for i in range(train_start, fc_start):
        d = dates[i]
        for h in range(24):
            rows.append({
                "datetime": pd.Timestamp(d) + pd.Timedelta(hours=h),
                "load_mw": load_arr[i, h] / 1000.0,   # kW → MW（预测模块口径）
                "company": "A公司",
            })
    df_hourly = pd.DataFrame(rows)
    df_hourly = prepare_load_data(df_hourly, "A公司")   # 补 date/hour/dow/is_weekend 列

    fc = run_forecast("A公司", df_hourly, forecast_horizon=FORECAST_HORIZON)
    if "error" in fc:
        print("预测失败：", fc["error"])
        return
    hourly = fc["hourly_results"]

    # 预测逐时负荷 → (H, 24) kW（按日期+小时对齐）
    date_to_idx = {dates[fc_start + i]: i for i in range(FORECAST_HORIZON)}
    pred_load = np.zeros((FORECAST_HORIZON, 24))
    for p in hourly:
        d = pd.Timestamp(p["date"]).date()
        if d in date_to_idx:
            pred_load[date_to_idx[d], int(p["hour"])] = p["load_mw"] * 1000.0  # MW → kW

    # 验证：预测 vs 目标期真实负荷
    actual_load = load_arr[fc_start:fc_start + FORECAST_HORIZON]
    daily_mape = float(np.mean(
        np.abs(actual_load.sum(axis=1) - pred_load.sum(axis=1)) / actual_load.sum(axis=1)) * 100)
    hourly_mae = float(np.mean(np.abs(actual_load - pred_load)))
    print(f"  预测精度：日总 MAPE {daily_mape:.2f}%，逐时 MAE {hourly_mae:.1f} kW")

    # ============================================================
    # 3. 优化调度（预测负荷 + 光伏 + 电价 → 逐日光储方案）
    # ============================================================
    print("\n[2/4] 优化调度中...")
    rad_target = rad_arr[fc_start:fc_start + FORECAST_HORIZON]
    pv_target = pv_output_from_radiation(rad_target, PV_CAPACITY_KW, dispatch_cfg.PV_SYSTEM_PR)

    pch_all = np.zeros((FORECAST_HORIZON, 24))
    pdis_all = np.zeros((FORECAST_HORIZON, 24))
    psell_all = np.zeros((FORECAST_HORIZON, 24))
    pgrid_all = np.zeros((FORECAST_HORIZON, 24))
    soc_all = np.zeros((FORECAST_HORIZON, 24))

    soc_now = dispatch_cfg.SOC_INIT
    sum_buy = sum_export = sum_cost = sum_carbon = 0.0
    n_fail = 0
    for d in range(FORECAST_HORIZON):
        day_idx = fc_start + d
        price = dispatch_cfg.price_for_day(day_idx)
        ef_opt = dispatch_cfg.ef_opt_for_day(day_idx)
        res = daily_opt_dispatch(
            pv_kw=pv_target[d], load_kw=pred_load[d],
            E_max=dispatch_cfg.E_BAT_MAX, P_max=dispatch_cfg.P_BAT_MAX,
            eta_ch=dispatch_cfg.ETA_CH, eta_dis=dispatch_cfg.ETA_DIS,
            soc_min=dispatch_cfg.SOC_MIN, soc_max=dispatch_cfg.SOC_MAX,
            soc0=soc_now,
            price=price, w_cost=dispatch_cfg.W_COST, w_green=dispatch_cfg.W_GREEN,
            w_carbon=dispatch_cfg.W_CARBON, carbon_price=dispatch_cfg.CARBON_PRICE,
            ef_opt=ef_opt,
            flex_min=dispatch_cfg.FLEX_MIN, flex_max=dispatch_cfg.FLEX_MAX,
            flex_penalty=dispatch_cfg.FLEX_PENALTY, flex_enabled=dispatch_cfg.FLEX_ENABLED,
            flex_dev_cost=dispatch_cfg.FLEX_DEV_COST,
            flex_energy_ratio=dispatch_cfg.FLEX_ENERGY_RATIO,
        )
        if res.get("soc") is None:
            n_fail += 1
            print(f"  第 {d} 天（{dates[fc_start + d]}）求解失败：{res.get('message')}")
            continue
        soc_now = res["soc"][-1]
        pch_all[d] = res["pch"]; pdis_all[d] = res["pdis"]
        psell_all[d] = res["psell"]; pgrid_all[d] = res["pgrid"]; soc_all[d] = res["soc"]
        sum_buy += res["buy_kwh"]; sum_export += res["export_kwh"]
        sum_cost += res["cost_yuan"]; sum_carbon += res["carbon_kg"]

    total_load = pred_load.sum()
    total_pv = pv_target.sum()
    green_ratio = total_pv / total_load * 100 if total_load > 0 else 0.0
    print(f"  调度完成（无解 {n_fail} 天）：总负荷 {total_load/1e4:.1f} 万kWh，"
          f"光伏 {total_pv/1e4:.1f} 万kWh，购电 {sum_buy/1e4:.1f} 万kWh，"
          f"余电 {sum_export/1e4:.1f} 万kWh")
    print(f"  绿电占比 {green_ratio:.1f}%，购电成本 {sum_cost/1e4:.1f} 万元，"
          f"调度侧碳成本 {sum_carbon/1e3:.0f} 吨")

    # ============================================================
    # 4. 碳核算（调度结果 → 范围二 + 项目减排）
    # ============================================================
    print("\n[3/4] 碳核算中...")
    carbon_rows = []
    ef_opt_list = []
    for d in range(FORECAST_HORIZON):
        date = dates[fc_start + d]
        ef = dispatch_cfg.ef_opt_for_day(fc_start + d)
        for h in range(24):
            pv = pv_target[d, h]
            psell = psell_all[d, h]
            pgrid = pgrid_all[d, h]
            carbon_rows.append({
                "timestamp": pd.Timestamp(date) + pd.Timedelta(hours=h),
                "load": pred_load[d, h],                 # kWh（kW×1h）
                "pv": pv,
                "pv_self": pv - psell,                   # 自用
                "pv_sell": psell,                        # 余电上网
                "p_bat": pch_all[d, h] - pdis_all[d, h],  # 正=充电，负=放电
                "p_grid": max(pgrid - psell, 0.0),       # 净购电（clip 0，余电不计负）
                "soc": soc_all[d, h],
                "p_aux": 0.0,
            })
            ef_opt_list.append(ef[h])

    df_carbon = pd.DataFrame(carbon_rows)
    ef_series = pd.Series(ef_opt_list, dtype=float)
    acct = CarbonAccounting(df_carbon, ef_opt=ef_series)
    cr = acct.run_all()

    scope2 = cr["scope2"]
    proj = cr["project"]
    scope1 = cr["scope1"]

    print(f"  范围二（7月外购电）排放 = {scope2['scope2_kg']/1e3:,.1f} tCO2"
          f"（净购电 {scope2['e_grid_kwh']/1e4:,.1f} 万kWh × {scope2['ef_report']}）")
    print(f"  项目减排 ER（7月） = {proj['ER_t']:,.1f} tCO2"
          f"（基准 {proj['BE_kg']/1e3:,.0f} - 项目 {proj['PE_kg']/1e3:,.0f} - 泄漏 {proj['LE_kg']/1e3:,.2f}）")
    print(f"  范围一（全年工艺，固定不随调度变） = {scope1['scope1_kg']/1e3:,.1f} tCO2e")

    # ============================================================
    # 5. 汇总输出
    # ============================================================
    print("\n[4/4] 汇总输出...")
    summary = {
        "meta": {
            "factory": FACTORY,
            "pipeline": "负荷预测 → 优化调度 → 碳核算",
            "forecast_horizon_days": FORECAST_HORIZON,
            "train_days": TRAIN_DAYS,
            "pv_capacity_kw": PV_CAPACITY_KW,
            "pv_pr": dispatch_cfg.PV_SYSTEM_PR,
            "battery": {
                "E_kWh": dispatch_cfg.E_BAT_MAX,
                "P_kW": dispatch_cfg.P_BAT_MAX,
            },
            "target_range": [str(dates[fc_start]), str(dates[-1])],
        },
        "forecast": {
            "daily_mape_pct": round(daily_mape, 2),
            "hourly_mae_kw": round(hourly_mae, 1),
        },
        "dispatch": {
            "total_load_kwh": round(float(total_load), 0),
            "total_pv_kwh": round(float(total_pv), 0),
            "total_buy_kwh": round(sum_buy, 0),
            "total_export_kwh": round(sum_export, 0),
            "green_ratio_pct": round(green_ratio, 2),
            "total_cost_yuan": round(sum_cost, 1),
            "n_fail_days": n_fail,
        },
        "carbon": {
            "scope2_t": round(scope2["scope2_kg"] / 1e3, 1),
            "er_t": round(proj["ER_t"], 1),
            "scope1_annual_t": round(scope1["scope1_kg"] / 1e3, 1),
        },
    }

    out_path = os.path.join(OUTPUT_DIR, "全流程_7月闭环.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 60)
    print("闭环跑通！一张表看清 7 月完整方案：")
    print("=" * 60)
    print(f"  预测     ：日总 MAPE {daily_mape:.2f}%，逐时 MAE {hourly_mae:.1f} kW")
    print(f"  调度     ：购电 {sum_buy/1e4:.1f} 万kWh，绿电 {green_ratio:.1f}%，"
          f"电费 {sum_cost/1e4:.1f} 万元")
    print(f"  碳核算   ：7月减排 {proj['ER_t']:,.1f} tCO2，范围二 {scope2['scope2_kg']/1e3:,.1f} tCO2")
    print(f"  结果已存：{out_path}")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        FACTORY = sys.argv[1].upper()
    if len(sys.argv) > 2:
        FORECAST_HORIZON = int(sys.argv[2])
    if len(sys.argv) > 3:
        TRAIN_DAYS = int(sys.argv[3])
    main()
