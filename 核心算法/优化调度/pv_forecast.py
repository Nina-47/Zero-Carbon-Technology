# -*- coding: utf-8 -*-
"""
光伏预测：KNN 相似日匹配（用历史数据验证）

方法：光伏出力由逐时辐射形状决定。给定目标日逐时天气特征，
在历史库里找 K 个"逐时辐射最相似"的日子，加权合成逐时光伏出力曲线。

数据：合并数据集_光伏×天气.csv
  逐时光伏 发电_kWh_{t}时 (kW, 每小时发电量≈平均功率)
  逐时辐射 辐射_MJpm2_{t}时
  逐时温度 气温_℃_{t}时
  日级     日总辐射_MJpm2、晴空指数、季节
"""

import numpy as np
import pandas as pd


def load_pv_data(csv_path):
    """读光伏×天气CSV，返回 DataFrame（含日期 + 逐时数组列）。"""
    df = pd.read_csv(csv_path)
    return df


def _get_hourly(df, prefix, h=24):
    """提取逐时字段为 (n_days, 24) 数组。"""
    cols = [f"{prefix}_{t}时" for t in range(h)]
    cols = [c for c in cols if c in df.columns]
    if len(cols) != h:
        return None
    return df[cols].values.astype(float)


def build_pv_library(df):
    """
    构建光伏相似日模板库。每条模板 = {
        date, hourly_pv(24), hourly_rad(24), hourly_temp(24),
        rad_daily, clear_index, season,
    }
    """
    dates = df["日期"].values
    hourly_pv = _get_hourly(df, "发电_kWh")
    hourly_rad = _get_hourly(df, "辐射_MJpm2")
    hourly_temp = _get_hourly(df, "气温_℃")

    templates = []
    n = len(df)
    for i in range(n):
        tpl = {
            "date": str(dates[i]),
            "hourly_pv": hourly_pv[i] if hourly_pv is not None else None,
            "hourly_rad": hourly_rad[i] if hourly_rad is not None else None,
            "hourly_temp": hourly_temp[i] if hourly_temp is not None else None,
        }
        # 日级字段可选
        for col in ["日总辐射_MJpm2", "晴空指数"]:
            if col in df.columns:
                v = df[col].iloc[i]
                tpl[col] = 0.0 if pd.isna(v) else float(v)
        # 季节是中文文本，存原文
        if "季节" in df.columns:
            tpl["季节"] = str(df["季节"].iloc[i])
        if tpl["hourly_pv"] is not None and tpl["hourly_rad"] is not None:
            templates.append(tpl)
    return templates


def match_similar_days(templates, target_hourly_rad, k=5):
    """
    按逐时辐射相似度匹配 K 个历史相似日。

    相似度 = 1 - 归一化逐时相关性距离，同时考虑日总辐射量偏差。
    返回 (加权逐时光伏曲线, 匹配到的模板下标列表)
    """
    # 计算每个模板与目标日的距离
    dists = []
    for idx, tpl in enumerate(templates):
        rad = tpl["hourly_rad"]
        tgt = target_hourly_rad
        # 逐时辐射相关性
        if np.std(rad) > 1e-6 and np.std(tgt) > 1e-6:
            corr = np.corrcoef(rad, tgt)[0, 1]
            d_shape = max(0.0, 1.0 - corr)  # 形状差
        else:
            d_shape = 0.0
        # 日总辐射量偏差
        rad_daily_tpl = rad.sum()
        rad_daily_tgt = tgt.sum()
        d_total = abs(rad_daily_tpl - rad_daily_tgt) / (rad_daily_tgt + 1e-3)
        # 综合距离：形状为主，总量为辅
        dist = 0.7 * d_shape + 0.3 * d_total
        dists.append((dist, idx))

    dists.sort(key=lambda x: x[0])
    top_k = dists[:min(k, len(dists))]

    # 加权合成（权重 = 1/(dist + eps)）
    weights = np.array([1.0 / (d + 0.01) for d, _ in top_k])
    weights /= weights.sum()

    profiles = np.array([templates[idx]["hourly_pv"] for _, idx in top_k])
    weighted_pv = np.average(profiles, axis=0, weights=weights)

    matched_idx = [idx for _, idx in top_k]
    matched_dates = [templates[idx]["date"] for idx in matched_idx]

    return weighted_pv, matched_dates


def forecast_day(df, target_date, k=5):
    """
    预测 target_date 的逐时光伏出力（两步法：辐射→日总量回归 + KNN 形状分配）。
    用历史库中逐时辐射特征最相似的日子加权合成。
    """
    # 目标日的逐时辐射：这里用历史数据里 target_date 那天的实际辐射
    # （回测演示用；实时场景换成天气预报的逐时辐射）
    target_row = df[df["日期"].astype(str) == str(target_date)]
    if len(target_row) == 0:
        return None, None, []
    target_hourly_rad = _get_hourly(target_row, "辐射_MJpm2")[0]
    target_actual_pv = _get_hourly(target_row, "发电_kWh")[0]

    # 用除目标日外的历史天做模板库（留出验证）
    train_df = df[df["日期"].astype(str) != str(target_date)]

    pred_pv = _forecast_two_stage(train_df, target_hourly_rad, k=k)
    _, matched_dates = match_similar_days(build_pv_library(train_df), target_hourly_rad, k=k)

    return pred_pv, target_actual_pv, matched_dates


def evaluate(df, k=5, n_test=60):
    """
    留出法回测：用后 n_test 天做测试，前 N-n_test 天做模板库。
    两步法：①辐射→日总量线性回归校核 ②KNN 形状分配逐时。
    返回逐日 MAPE 和逐时 RMSE。
    """
    df = df.sort_values("日期").reset_index(drop=True)
    n = len(df)
    test_idx = list(range(n - n_test, n))

    daily_ape = []
    hourly_errors = []

    for i in test_idx:
        target_date = df["日期"].iloc[i]
        target_hourly_rad = _get_hourly(df.iloc[[i]], "辐射_MJpm2")[0]
        target_actual_pv = _get_hourly(df.iloc[[i]], "发电_kWh")[0]

        # 训练库 = 目标日之前的全部历史（只用过去，不偷看未来）
        train_df = df.iloc[:i]

        pred_pv = _forecast_two_stage(train_df, target_hourly_rad, k=k)

        # 逐时误差
        hourly_errors.extend((pred_pv - target_actual_pv).tolist())

        # 日总量误差
        daily_pred = pred_pv.sum()
        daily_actual = target_actual_pv.sum()
        if daily_actual > 0:
            daily_ape.append(abs(daily_pred - daily_actual) / daily_actual * 100)

    hourly_rmse = np.sqrt(np.mean(np.array(hourly_errors) ** 2))
    mean_daily_ape = np.mean(daily_ape) if daily_ape else float("nan")

    return {
        "hourly_rmse_kw": hourly_rmse,
        "daily_mape_pct": mean_daily_ape,
        "n_test": len(test_idx),
    }


def _forecast_two_stage(train_df, target_hourly_rad, k=5):
    """
    两步法预测（回测验证的最优实用方案，日总量 MAPE ~27%）：
    ① 用"日总辐射→日总发电量"线性回归预测目标日总量
    ② 用 KNN 相似日的"逐时发电形状"分配该总量到 24 小时
    返回 24 维逐时发电预测（kW·h/小时）。

    注：曾尝试 GBR（梯度提升）可达日总量 MAPE 7.7%，但依赖"真实晴空指数/容量因子"
    这类未来不可知特征，属"偷看答案"，实时场景拿不到，故不采用。
    只用"日总辐射"这一天气预报可提供的输入，线性校核就是现实天花板 ~27%。
    """
    from sklearn.linear_model import LinearRegression

    train_templates = build_pv_library(train_df)

    # ① 辐射→日总量线性回归
    rads = []
    gens = []
    for tpl in train_templates:
        if tpl["hourly_rad"] is not None and tpl["hourly_pv"] is not None:
            rads.append(tpl["hourly_rad"].sum())
            gens.append(tpl["hourly_pv"].sum())
    rads = np.array(rads).reshape(-1, 1)
    gens = np.array(gens)
    lr = LinearRegression().fit(rads, gens)
    target_rad_total = target_hourly_rad.sum()
    pred_daily_total = lr.predict([[target_rad_total]])[0]
    pred_daily_total = max(pred_daily_total, 0.0)

    # ② KNN 形状匹配，归一化后乘以预测总量
    weighted_pv, _ = match_similar_days(train_templates, target_hourly_rad, k=k)
    shape_sum = weighted_pv.sum()
    if shape_sum <= 0:
        return np.zeros(24)
    pred_pv = weighted_pv / shape_sum * pred_daily_total
    return pred_pv


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config

    df = load_pv_data(config.PV_WEATHER_CSV)
    print(f"光伏数据: {len(df)} 天")

    # 单日预测示例
    target = df["日期"].iloc[-1]
    pred, actual, matched = forecast_day(df, target, k=5)
    if pred is not None:
        print(f"\n预测目标日: {target}")
        print(f"匹配到的相似日: {matched}")
        print(f"日总发电: 预测 {pred.sum():.0f} kWh vs 实际 {actual.sum():.0f} kWh")

    # 留出法回测
    print("\n=== 留出法回测 ===")
    for k in [3, 5, 10]:
        r = evaluate(df, k=k, n_test=60)
        print(f"K={k}: 逐时RMSE={r['hourly_rmse_kw']:.1f} kW, 日总量MAPE={r['daily_mape_pct']:.1f}%")
