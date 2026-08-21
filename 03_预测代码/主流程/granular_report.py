# -*- coding: utf-8 -*-
"""
日/月/年 三粒度报告：调度 + 碳核算 一键汇总。

读 优化调度/output/yearly_dispatch.json（逐日 summary + 逐时 hourly），产出：
  1) 调度 —— 日（逐时+日汇总，直接引用）、月（聚合）、年（聚合）
  2) 碳核算 —— 日/月/年 的 范围二(scope2) + 减排(ER)；范围一(工艺)按 365 天均匀分摊

口径与模块二/三完全一致：
  - scope2 = 净购电 p_grid × EF_REPORT(0.4419)
  - ER = 基准 BE(无储能) - 项目 PE(有储能)，碳因子用节点电价代理法 ef_opt(t)
  - 范围一工艺排放全年固定 28454.8 t（365 天口径），按天均匀分摊到日/月

用法：python granular_report.py [输出json路径]
"""

import io
import os
import sys
import json

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ---- 路径 ----
BASE = os.path.dirname(os.path.abspath(__file__))          # 主流程/
CODE_DIR = os.path.dirname(BASE)                            # 03_预测代码/
DISPATCH_DIR = os.path.join(CODE_DIR, "优化调度")
CARBON_DIR = os.path.join(CODE_DIR, "碳核算")
PROJECT = os.path.dirname(CODE_DIR)
DISPATCH_OUT = os.path.join(PROJECT, "04_预测输出", "V4_优化调度")
CARBON_OUT = os.path.join(PROJECT, "04_预测输出", "V3_碳核算")

DISPATCH_JSON = os.path.join(DISPATCH_DIR, "output", "yearly_dispatch.json")

# ---- 复用碳核算模块（避免 config 同名冲突：这里只用碳核算的 config）----
sys.path.insert(0, CARBON_DIR)
from carbon_accounting import CarbonAccounting
from data_loader import build_schedule_from_module2, load_node_price
from emission_factors import price_to_carbon_intensity
import config as C

# ============================================================
# 1. 读逐日调度结果
# ============================================================
with open(DISPATCH_JSON, encoding="utf-8") as f:
    payload = json.load(f)
days = payload["days"]
ok_days = [d for d in days if d.get("status") == "ok"]

SUM_KEYS = ["load_kWh", "pv_kWh", "buy_kWh", "export_kWh", "net_grid_kWh",
            "chg_kWh", "dis_kWh", "chg_pv_kWh", "dis_replace_kWh"]

# 中文表头（CSV 导出用，Excel 友好）
DISPATCH_COLS_CN = {
    "date": "日期", "mode": "运行模式", "month": "月份", "days": "天数",
    "load_kWh": "用电量(kWh)", "pv_kWh": "光伏发电(kWh)", "buy_kWh": "购电量(kWh)",
    "export_kWh": "余电上网(kWh)", "net_grid_kWh": "净购电(kWh)",
    "chg_kWh": "储能充电(kWh)", "dis_kWh": "储能放电(kWh)",
    "chg_pv_kWh": "光伏充储能(kWh)", "dis_replace_kWh": "储能替代购电(kWh)",
    "cost_yuan": "电费(元)", "green_ratio_pct": "绿电占比(%)",
}
CARBON_COLS_CN = {
    "date": "日期", "month": "月份", "days": "天数",
    "grid_kWh": "净购电量(kWh)",
    "scope1_t": "范围一排放(tCO2e)", "scope2_t": "范围二排放(tCO2e)",
    "BE_t": "基准排放(tCO2e)", "PE_t": "项目排放(tCO2e)", "ER_t": "减排量(tCO2e)",
}


def agg_dispatch(subset):
    """把一组 day 的 summary 累加为一份汇总。"""
    a = {k: sum(d["summary"].get(k, 0.0) for d in subset) for k in SUM_KEYS}
    a["cost_yuan"] = sum(d["summary"].get("cost_yuan", 0.0) for d in subset)
    a["green_ratio_pct"] = round(a["pv_kWh"] / a["load_kWh"] * 100, 2) if a["load_kWh"] else 0.0
    return a


# 日粒度：直接用 ok_days（含逐时明细）
daily_dispatch = [{"date": d["date"], "mode": d["mode"], **{k: d["summary"].get(k) for k in SUM_KEYS},
                   "cost_yuan": d["summary"].get("cost_yuan"),
                   "green_ratio_pct": d["summary"].get("green_ratio_pct")} for d in ok_days]

# 月/年粒度
df_days = pd.DataFrame([{"ym": d["date"][:7], "date": d["date"], "summary": d["summary"]} for d in ok_days])
monthly_dispatch = []
for ym, grp in df_days.groupby("ym"):
    sub = [d for d in ok_days if d["date"][:7] == ym]
    monthly_dispatch.append({"month": ym, "days": len(sub), **agg_dispatch(sub)})
yearly_dispatch = agg_dispatch(ok_days)
yearly_dispatch["days"] = len(ok_days)

# ============================================================
# 2. 碳核算 日/月/年
# ============================================================
df = build_schedule_from_module2()   # 逐时：timestamp/load/pv/pv_self/p_bat/p_grid/soc

# ef_opt 时变碳因子（同 run_real 口径）
price_df = load_node_price()
price_map = price_df.set_index("timestamp")["price"]
aligned = price_map.reindex(df["timestamp"]).ffill().bfill()
if aligned.isna().any():
    aligned = aligned.fillna(aligned.mean())
df["ef_opt"] = price_to_carbon_intensity(aligned).values

# 基准情景（无储能，光伏仍自用）
df["baseline_grid"] = np.clip(df["load"] - df["pv_self"], 0, None)

# 范围一全年（365 天口径固定值）
scope1_annual_kg = CarbonAccounting(df).scope1_process()["scope1_kg"]
scope1_per_day_kg = scope1_annual_kg / 365.0


def carbon_for(sub):
    e_grid = sub["p_grid"].sum()
    be = (sub["baseline_grid"] * sub["ef_opt"]).sum()
    pe = (sub["p_grid"] * sub["ef_opt"]).sum()
    er = be - pe
    n_days = sub["timestamp"].dt.date.nunique()
    return {
        "days": int(n_days),
        "grid_kWh": float(e_grid),
        "scope1_t": round(scope1_per_day_kg * n_days * 1e-3, 2),
        "scope2_t": round(e_grid * C.EF_REPORT * 1e-3, 2),
        "BE_t": round(be * 1e-3, 2),
        "PE_t": round(pe * 1e-3, 2),
        "ER_t": round(er * 1e-3, 2),
    }


df["date"] = df["timestamp"].dt.date
df["ym"] = df["timestamp"].dt.strftime("%Y-%m")

daily_carbon = []
for date, sub in df.groupby("date"):
    daily_carbon.append({"date": str(date), **carbon_for(sub)})

monthly_carbon = []
for ym, sub in df.groupby("ym"):
    monthly_carbon.append({"month": ym, **carbon_for(sub)})

yearly_carbon = carbon_for(df)
yearly_carbon["scope1_t"] = round(scope1_annual_kg * 1e-3, 2)   # 年口径直接取全年值

# ============================================================
# 3. 汇总输出
# ============================================================
result = {
    "meta": {
        "factory": "A（中嘉）",
        "date_range": [ok_days[0]["date"], ok_days[-1]["date"]],
        "total_days": len(ok_days),
        "ef_report": C.EF_REPORT,
        "scope1_annual_t": round(scope1_annual_kg * 1e-3, 2),
    },
    "dispatch": {
        "yearly": yearly_dispatch,
        "monthly": monthly_dispatch,
        "daily": daily_dispatch,
    },
    "carbon": {
        "yearly": yearly_carbon,
        "monthly": monthly_carbon,
        "daily": daily_carbon,
    },
}

# 按版本铁律分开：调度 → V4_优化调度，碳核算 → V3_碳核算
os.makedirs(DISPATCH_OUT, exist_ok=True)
os.makedirs(CARBON_OUT, exist_ok=True)

with open(os.path.join(DISPATCH_OUT, "调度_粒度报告.json"), "w", encoding="utf-8") as f:
    json.dump({"meta": result["meta"], "dispatch": result["dispatch"]}, f, ensure_ascii=False, indent=1, default=str)
with open(os.path.join(CARBON_OUT, "碳核算_粒度报告.json"), "w", encoding="utf-8") as f:
    json.dump({"meta": result["meta"], "carbon": result["carbon"]}, f, ensure_ascii=False, indent=1, default=str)

# CSV（Excel 友好，utf-8-sig）
pd.DataFrame(daily_dispatch).rename(columns=DISPATCH_COLS_CN).to_csv(os.path.join(DISPATCH_OUT, "调度_日粒度.csv"), index=False, encoding="utf-8-sig")
pd.DataFrame(monthly_dispatch).rename(columns=DISPATCH_COLS_CN).to_csv(os.path.join(DISPATCH_OUT, "调度_月年汇总.csv"), index=False, encoding="utf-8-sig")
pd.DataFrame(daily_carbon).rename(columns=CARBON_COLS_CN).to_csv(os.path.join(CARBON_OUT, "碳核算_日粒度.csv"), index=False, encoding="utf-8-sig")
pd.DataFrame(monthly_carbon).rename(columns=CARBON_COLS_CN).to_csv(os.path.join(CARBON_OUT, "碳核算_月年汇总.csv"), index=False, encoding="utf-8-sig")

# ============================================================
# 4. 打印汇总（月 + 年，方便一眼看）
# ============================================================
print("=" * 78)
print("调度（月 + 年）  单位：万kWh / 万元")
print("=" * 78)
print(f"{'月份':<10}{'天数':>4}{'负荷':>8}{'光伏':>8}{'购电':>8}{'绿电%':>7}{'电费':>9}{'储能充':>8}{'储能放':>8}")
for m in monthly_dispatch:
    print(f"{m['month']:<10}{m['days']:>4}"
          f"{m['load_kWh']/1e4:>8.1f}{m['pv_kWh']/1e4:>8.1f}{m['buy_kWh']/1e4:>8.1f}"
          f"{m['green_ratio_pct']:>7.1f}{m['cost_yuan']/1e4:>9.1f}"
          f"{m['chg_kWh']/1e4:>8.1f}{m['dis_kWh']/1e4:>8.1f}")
y = yearly_dispatch
print("-" * 78)
print(f"{'全年':<10}{y['days']:>4}"
      f"{y['load_kWh']/1e4:>8.1f}{y['pv_kWh']/1e4:>8.1f}{y['buy_kWh']/1e4:>8.1f}"
      f"{y['green_ratio_pct']:>7.1f}{y['cost_yuan']/1e4:>9.1f}"
      f"{y['chg_kWh']/1e4:>8.1f}{y['dis_kWh']/1e4:>8.1f}")

print()
print("=" * 78)
print("碳核算（月 + 年）  单位：tCO2e")
print("=" * 78)
print(f"{'月份':<10}{'天数':>4}{'范围一':>9}{'范围二':>9}{'减排ER':>9}")
for m in monthly_carbon:
    print(f"{m['month']:<10}{m['days']:>4}{m['scope1_t']:>9.1f}{m['scope2_t']:>9.1f}{m['ER_t']:>9.1f}")
yc = yearly_carbon
print("-" * 78)
print(f"{'全年':<10}{yc['days']:>4}{yc['scope1_t']:>9.1f}{yc['scope2_t']:>9.1f}{yc['ER_t']:>9.1f}")

print()
print(f"调度结果 → 04_预测输出/V4_优化调度/（调度_粒度报告.json + 调度_日粒度.csv + 调度_月年汇总.csv）")
print(f"碳核算结果 → 04_预测输出/V3_碳核算/（碳核算_粒度报告.json + 碳核算_日粒度.csv + 碳核算_月年汇总.csv）")
