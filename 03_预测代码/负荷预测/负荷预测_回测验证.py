# -*- coding: utf-8 -*-
"""
负荷预测回测验证 —— A 公司（中嘉污水厂）

目的：验证现有预测模型（自适应窗口日总量 + KNN 模板逐时分配）在
      新整理好的 A 公司数据上的电量预测准确度。

回测设计：
  训练集：2025-07-01 ~ 2026-06-30（12 个月，365 天）
  测试集：2026-07-01 ~ 2026-07-31（1 个月，31 天，对应此前的「7月预测」）

关键对比（两个口径）：
  1. 电网电量   = 净购电（现有模型预测的对象，午间受光伏自发自用影响会凹陷）
  2. 实际用电量 = 总负荷（= 电网 + 光伏自发自用，不受光伏干扰，更规律）

数据：02_原始数据/负荷数据/A_中嘉污水厂.xlsx（逐时数据 sheet，单位 MWh）
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import os
import numpy as np
import pandas as pd
import openpyxl

# 让 import prediction 能找到模块
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CODE_DIR)

from prediction.load_forecast import run_forecast
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

DATA = r"C:/Users/xiaoY/Desktop/零碳科技/02_原始数据/负荷数据/A_中嘉污水厂.xlsx"
TRAIN_END = pd.Timestamp("2026-06-30")
TEST_START = pd.Timestamp("2026-07-01")
TEST_END = pd.Timestamp("2026-07-31")


def load_company_hourly(path, which):
    """
    读 A_中嘉污水厂.xlsx 的「逐时数据」sheet。
    which: 'grid' 电网电量(列2-25) / 'actual' 实际用电量(列50-73)
    返回长表 DataFrame [datetime, date, hour, load_mw]
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["逐时数据"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # 第 1、2 行是表头；数据从第 3 行开始
    # 列布局: 0日期 | 1-24电网电量 | 25-48光伏发电 | 49-72实际用电量
    if which == "grid":
        col_start, col_end = 1, 25
    else:
        col_start, col_end = 49, 73

    records = []
    for r in rows[2:]:
        if r[0] is None:
            continue
        date = pd.Timestamp(str(r[0]).strip())
        for h in range(24):
            v = r[col_start + h]
            if v is None:
                continue
            records.append({
                "datetime": date + pd.Timedelta(hours=h),
                "date": date,
                "hour": h,
                "load_mw": float(v),
            })
    df = pd.DataFrame(records)
    df["company"] = "A公司"
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def backtest(which, label):
    df = load_company_hourly(DATA, which)
    train = df[df["date"] <= TRAIN_END]
    test = df[(df["date"] >= TEST_START) & (df["date"] <= TEST_END)]

    print(f"\n{'='*60}")
    print(f"回测：预测【{label}】—— 训练 {train['date'].min().date()} ~ {train['date'].max().date()} "
          f"({len(train)//24} 天)，预测 {TEST_START.date()} ~ {TEST_END.date()}")
    print(f"{'='*60}")

    result = run_forecast("A公司", train, forecast_horizon=31)

    pred = pd.DataFrame(result["hourly_results"])
    pred["date"] = pd.to_datetime(pred["date"])

    # 对齐实际与预测
    merged = test.merge(pred[["date", "hour", "load_mw"]],
                        on=["date", "hour"], how="inner", suffixes=("_actual", "_pred"))
    merged = merged.dropna(subset=["load_mw_actual", "load_mw_pred"])

    mae = mean_absolute_error(merged["load_mw_actual"], merged["load_mw_pred"])
    rmse = np.sqrt(mean_squared_error(merged["load_mw_actual"], merged["load_mw_pred"]))
    r2 = r2_score(merged["load_mw_actual"], merged["load_mw_pred"])

    # 日总 MAPE
    daily = merged.groupby("date").agg(actual=("load_mw_actual", "sum"),
                                       pred=("load_mw_pred", "sum"))
    mape_daily = (abs(daily["actual"] - daily["pred"]) / daily["actual"] * 100).mean()

    # 午间 vs 其他时段
    midday = merged[merged["hour"].between(10, 15)]
    other = merged[~merged["hour"].between(10, 15)]
    midday_mae = mean_absolute_error(midday["load_mw_actual"], midday["load_mw_pred"])
    other_mae = mean_absolute_error(other["load_mw_actual"], other["load_mw_pred"])

    print(f"  逐时 MAE  = {mae:.4f} MWh  (≈平均功率 {mae:.2f} MW)")
    print(f"  逐时 RMSE = {rmse:.4f} MWh")
    print(f"  逐时 R²   = {r2:.4f}")
    print(f"  日总 MAPE = {mape_daily:.2f}%")
    print(f"  午间(10-15h) MAE = {midday_mae:.4f}，其他时段 MAE = {other_mae:.4f}，"
          f"午间/其他 = {midday_mae/other_mae:.2f}x")

    # 汇总每日误差
    daily_err = daily.copy()
    daily_err["误差%"] = abs(daily_err["actual"] - daily_err["pred"]) / daily_err["actual"] * 100
    return {
        "label": label, "mae": mae, "rmse": rmse, "r2": r2,
        "mape_daily": mape_daily, "midday_mae": midday_mae, "other_mae": other_mae,
        "daily_err": daily_err, "merged": merged,
    }


r_grid = backtest("grid", "电网电量(净购电)")
r_actual = backtest("actual", "实际用电量(总负荷)")

print("\n\n" + "="*60)
print("两个口径对比")
print("="*60)
print(f"{'指标':<16}{'电网电量':>14}{'实际用电量':>14}")
for key, name in [("mae", "逐时MAE(MWh)"), ("rmse", "逐时RMSE(MWh)"),
                  ("r2", "逐时R²"), ("mape_daily", "日总MAPE(%)"),
                  ("midday_mae", "午间MAE"), ("other_mae", "其他时段MAE")]:
    print(f"{name:<16}{r_grid[key]:>14.4f}{r_actual[key]:>14.4f}")

# 输出每日误差对比到 CSV（供后续画图/分析）
err_out = pd.DataFrame({
    "日期": r_grid["daily_err"].index,
    "电网_实际": r_grid["daily_err"]["actual"].values,
    "电网_预测": r_grid["daily_err"]["pred"].values,
    "电网_误差%": r_grid["daily_err"]["误差%"].values,
    "实际用电_实际": r_actual["daily_err"]["actual"].values,
    "实际用电_预测": r_actual["daily_err"]["pred"].values,
    "实际用电_误差%": r_actual["daily_err"]["误差%"].values,
})
out_path = os.path.join(CODE_DIR, "回测_每日误差对比.csv")
err_out.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\n每日误差已存: {out_path}")
