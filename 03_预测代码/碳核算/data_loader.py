"""数据加载与装配。

读取模块二导出的负荷宽表、光伏发电宽表，装配为逐时长表，并生成
储能调度、节点电价的占位数据（真实文件到位后替换）。

关键口径：负荷宽表是厂区【总负荷】（含光伏），范围为 2025-07-01 起；
光伏宽表是逐时【发电量】，自用/上网拆分按项目设定。
"""

import os

import numpy as np
import pandas as pd

from config import (
    BATTERY_CAPACITY, BATTERY_POWER_MAX, ETA_RT, SOC_MIN, SOC_MAX,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
MODULE2_DIR = os.path.normpath(os.path.join(PROJECT_DIR, "..", "模块二"))


def _wide_to_long(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """宽表(日期 + 合计 + 0时..23时) → 长表(timestamp, value)。"""
    hour_cols = [f"{h}时" for h in range(24)]
    long = df.melt(
        id_vars=[df.columns[0]],
        value_vars=hour_cols,
        var_name="hour",
        value_name=value_col,
    )
    long["hour"] = long["hour"].str.replace("时", "").astype(int)
    long["timestamp"] = pd.to_datetime(long[df.columns[0]]) + pd.to_timedelta(long["hour"], unit="h")
    return long[["timestamp", value_col]].sort_values("timestamp").reset_index(drop=True)


def load_module2_data() -> pd.DataFrame:
    """装配逐时明细长表，含总负荷与三站光伏发电量。

    单位口径：负荷宽表各列为 MW（平均功率），小时电量 MWh = 列值 × 1h；
    光伏宽表各列已是 kWh（小时电量）。两者统一到 kWh。
    """
    path = os.path.join(MODULE2_DIR, "data_source.xlsx")
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到模块二数据源: {path}")

    load_wide = pd.read_excel(path, sheet_name="负荷数据")
    load_long = _wide_to_long(load_wide, "load")
    # 负荷列值是 MW（平均功率），1h 电量 MWh = 列值×1h；转 kWh 需 ×1000
    load_long["load"] = load_long["load"].astype(float) * 1000.0  # → kWh

    # 光伏：优先读「光伏合计」sheet（一期+二期+车棚三站真实合计），
    # 缺少时退回一期+二期相加
    hour_cols = ["0点", "1点", "2点", "3点", "4点", "5点", "6点", "7点",
                 "8点", "9点", "10点", "11点", "12点", "13点", "14点",
                 "15点", "16点", "17点", "18点", "19点", "20点", "21点",
                 "22点", "23点"]
    xls = pd.ExcelFile(path)
    if "光伏合计" in xls.sheet_names:
        wide = pd.read_excel(path, sheet_name="光伏合计")
        long = wide.melt(id_vars=[wide.columns[0]], value_vars=hour_cols,
                         var_name="hour", value_name="pv")
        long["hour"] = long["hour"].str.replace("点", "").astype(int)
        long["timestamp"] = pd.to_datetime(long[wide.columns[0]]) + pd.to_timedelta(long["hour"], unit="h")
        pv_all = long[["timestamp", "pv"]].sort_values("timestamp").reset_index(drop=True)
        pv_all["pv"] = pv_all["pv"].astype(float)
        # 三站真实合计 × PV_SCALE = 规划装机12.2MW
        pv_all["pv"] = (pv_all["pv"] * 2.0).round(2)
    else:
        pv_sheets = ["污水处理厂8MWp光伏电站(一期)", "污水处理厂8MWp光伏电站(二期)"]
        pv_parts = []
        for sheet in pv_sheets:
            wide = pd.read_excel(path, sheet_name=sheet)
            long = wide.melt(id_vars=[wide.columns[0]], value_vars=hour_cols,
                             var_name="hour", value_name="pv")
            long["hour"] = long["hour"].str.replace("点", "").astype(int)
            long["timestamp"] = pd.to_datetime(long[wide.columns[0]]) + pd.to_timedelta(long["hour"], unit="h")
            pv_parts.append(long[["timestamp", "pv"]].sort_values("timestamp").reset_index(drop=True))
        pv_all = pv_parts[0].merge(pv_parts[1], on="timestamp", how="outer", suffixes=("_p1", "_p2"))
        for c in ["pv_p1", "pv_p2"]:
            pv_all[c] = pv_all[c].fillna(0).astype(float)
        pv_all["pv"] = (pv_all["pv_p1"] + pv_all["pv_p2"]).round(2) * 2.0

    df = load_long.merge(pv_all[["timestamp", "pv"]], on="timestamp", how="left")
    df["pv"] = df["pv"].fillna(0.0)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # 负荷缺失兜底插值并标记（负荷已补全时此分支不触发）
    df["load_raw_missing"] = df["load"].isna()
    df["load"] = df["load"].interpolate(method="linear").ffill().bfill()
    return df


def build_schedule(df: pd.DataFrame, self_use_ratio: float = 1.0) -> pd.DataFrame:
    """在逐时明细上装配储能调度、光伏自用/上网、关口净购电。

    self_use_ratio：光伏自发自用比例；余电 1-ratio 为上网电量。

    储能调度当前为占位（真实模块二逐时曲线到位后替换）：
    低谷(0-8点)充电、高峰(10-12/14-19点)放电，SOC 在 [10,90] 闭环。
    schedule_method 字段标记来源。
    """
    df = df.copy()
    n = len(df)
    hour = df["timestamp"].dt.hour.values

    # 光伏自用/上网拆分
    df["pv_self"] = df["pv"] * self_use_ratio
    df["pv_sell"] = df["pv"] - df["pv_self"]

    # 占位储能调度功率（正=充电，负=放电）
    p_bat = np.zeros(n)
    capacity_kwh = BATTERY_CAPACITY
    soc = np.zeros(n)
    soc[0] = 50.0
    for i in range(1, n):
        h = hour[i]
        desired = 0.0
        if 0 <= h <= 8:
            desired = min(BATTERY_POWER_MAX, 0.4 * BATTERY_POWER_MAX)  # 充电
        elif (10 <= h <= 12) or (14 <= h <= 19):
            desired = -min(BATTERY_POWER_MAX, 0.5 * BATTERY_POWER_MAX)  # 放电
        # 依据 SOC 边界钳制
        if desired > 0:
            room = (SOC_MAX * capacity_kwh - soc[i - 1] * capacity_kwh / 100.0)
            desired = min(desired, room * 100.0 / capacity_kwh * ETA_RT / ETA_RT)
            p_bat[i] = min(desired, (SOC_MAX * 100 - soc[i - 1]) * capacity_kwh / 100.0 / ETA_RT)
        elif desired < 0:
            avail = (soc[i - 1] - SOC_MIN * 100) * capacity_kwh / 100.0
            p_bat[i] = max(desired, -avail * ETA_RT)
        else:
            p_bat[i] = 0.0
        # SOC 更新（忽略辅助损耗的简单时序）
        soc[i] = soc[i - 1] + (p_bat[i] * ETA_RT if p_bat[i] > 0 else p_bat[i] / ETA_RT) / capacity_kwh * 100.0
        soc[i] = float(np.clip(soc[i], 0, 100))

    df["p_bat"] = p_bat
    df["soc"] = soc

    # 关口净购电 = 总负荷 - 光伏自用 - 储能放电（+储能充电视为购电）
    # 约定：储能充电从电网取电（购电侧），放电抵消负荷
    df["p_grid"] = df["load"] - df["pv_self"] + np.where(p_bat > 0, p_bat, 0) \
        - np.where(p_bat < 0, -p_bat, 0)
    # p_grid 实际为“净购电”，允许为负表示反送（本项目余电上网不计负排放，clip到0做保守处理）
    df["p_grid"] = df["p_grid"].clip(lower=0)

    # 辅助电耗（泄漏排放用）
    df["p_aux"] = (np.abs(p_bat) * 0.0) + np.abs(p_bat) * (0.03 if False else 0.03)

    # 标记
    df["schedule_method"] = "mock"
    return df


def load_node_price() -> pd.DataFrame:
    """加载广东电力现货节点实时电价（元/MWh → 元/kWh）。

    读取 config.PRICE_XLSX 的「逐时数据」sheet（宽表：日期 + 0~23时实时电价），
    展开为长表(timestamp, price)。文件缺失时回退到 mock 占位曲线。
    """
    import config as C

    if os.path.exists(C.PRICE_XLSX):
        import openpyxl
        wb = openpyxl.load_workbook(C.PRICE_XLSX, read_only=True, data_only=True)
        ws = wb["逐时数据"]
        rows = []
        for row in ws.iter_rows(min_row=3, values_only=True):  # 前 2 行是表头
            if row[0] is None:
                continue
            d = str(row[0]).strip()[:10]
            # 列布局：0日期 | 1-24日前电价 | 25-48实时电价(元/MWh)
            vals = [0.0 if v is None else max(float(v), 0.0) / 1000.0 for v in row[25:49]]
            if len(vals) != 24:
                continue
            for h, p in enumerate(vals):
                rows.append({"timestamp": pd.Timestamp(f"{d} {h:02d}:00:00"), "price": p})
        wb.close()
        if rows:
            out = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
            out["price"] = out["price"].clip(lower=0)
            return out

    from emission_factors import mock_price_curve
    ts = pd.date_range("2025-07-01", periods=8760, freq="h")
    price = mock_price_curve(ts.hour.values)
    return pd.DataFrame({"timestamp": ts, "price": price})


def load_linked_price(df: pd.DataFrame) -> pd.Series:
    """逐时到户电价（中长期90% + 现货10% 联动），与优化调度 price_for_day 同源。

    返回与 df.timestamp 对齐的 Series（元/kWh），供构造 EF_opt 时变碳因子。
    关键口径：碳因子代理的价格信号必须与储能调度省电费的价格信号一致——
    调度按联动价做削峰填谷，碳因子也按联动价推碳强度，避免"调度用一套价、
    减碳评估用另一套价"的错位。复用优化调度 config（单一事实源），不重复维护参数。
    """
    import importlib.util
    from datetime import datetime

    dispatch_config_path = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "优化调度", "config.py"))
    spec = importlib.util.spec_from_file_location("dispatch_config", dispatch_config_path)
    dispatch_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dispatch_config)

    start = datetime.strptime(dispatch_config.DATA_START_DATE, "%Y-%m-%d").date()
    day_cache = {}
    out = np.empty(len(df), dtype=float)
    for i, ts in enumerate(df["timestamp"]):
        t = pd.Timestamp(ts)
        day_idx = (t.date() - start).days
        if day_idx < 0:
            day_idx = 0
        if day_idx not in day_cache:
            day_cache[day_idx] = dispatch_config.price_for_day(day_idx)
        out[i] = day_cache[day_idx][t.hour]
    return pd.Series(out, index=df.index)


def build_schedule_from_module2() -> pd.DataFrame:
    """读取模块二逐日调度 JSON，展平为逐时长表，字段对齐 CarbonAccounting。

    返回 df 含列：timestamp, load, pv, pv_self, pv_sell, p_bat, p_grid, soc, p_aux。
    模块二 JSON 中各 kW 值等价于 1h 电量(kWh)，直接复用。
    p_bat = 放电 - 充电（正=充电，负=放电，与 CarbonAccounting 一致）。
    """
    import json
    import config as C

    json_path = os.path.join(C.PROJECT_DIR, "03_预测代码", "优化调度", "output", "yearly_dispatch.json")
    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    rows = []
    for day in payload["days"]:
        if day.get("status") != "ok":
            continue
        date_str = day["date"]
        for h in day["hourly"]:
            t = pd.Timestamp(f"{date_str} {h['h']:02d}:00:00")
            pch = h["pch_kW"]      # 充电功率
            pdis = h["pdis_kW"]    # 放电功率
            rows.append({
                "timestamp": t,
                "load": h["load_kW"],
                "pv": h["pv_kW"],
                "pv_self": h["pv_kW"],          # 模块二余电上网模式下光伏几乎是全部自用
                "pv_sell": 0.0,
                "p_bat": pch - pdis,            # 正=充电，负=放电
                "p_grid": h["pgrid_kW"],        # 净购电
                "soc": h["soc"],
                "p_aux": 0.0,                   # 辅助电耗在 project_reduction 里按比例另算
            })

    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    return df


if __name__ == "__main__":
    df = load_module2_data()
    print("负荷明细：", len(df), "小时")
    print("时间范围：", df["timestamp"].min(), "~", df["timestamp"].max())
    print("总负荷合计(MWh)：", round(df["load"].sum() / 1000, 1))
    print("光伏合计(MWh)：", round(df["pv"].sum() / 1000, 1))
