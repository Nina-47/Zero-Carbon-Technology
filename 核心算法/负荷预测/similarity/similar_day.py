"""
相似日分析核心算法模块 (v2)

基于 z-score 标准化 + 加权欧氏距离，从历史天气数据中找出
与目标日气象条件最相似的 Top-N 日期，用于辅助负荷预测。

6因子权重定义见 config.SIMILARITY_WEIGHTS。
"""

import numpy as np
import pandas as pd
from datetime import datetime

from config import SIMILARITY_WEIGHTS, PRECIP_LEVELS


def compute_precip_level(precip_sum: float) -> int:
    """将日降水量 (mm) 映射为 0-5 等级。"""
    if precip_sum is None or (isinstance(precip_sum, float) and np.isnan(precip_sum)):
        return 0
    for i, (threshold, _) in enumerate(PRECIP_LEVELS):
        if precip_sum < threshold:
            return i
    return len(PRECIP_LEVELS) - 1


def _season_idx(dt):
    """返回季节索引: 0=冬, 1=春, 2=夏, 3=秋"""
    m = dt.month
    if m in [12, 1, 2]:
        return 0
    if m in [3, 4, 5]:
        return 1
    if m in [6, 7, 8]:
        return 2
    return 3


def match_season(d1, d2):
    """季节匹配得分：同季=0, 相邻季=0.5, 相反季=1。"""
    s1, s2 = _season_idx(d1), _season_idx(d2)
    if s1 == s2:
        return 0.0
    diff = abs(s1 - s2)
    if diff == 2:
        return 1.0
    return 0.5


def match_weekday(d1, d2):
    """星期类型匹配：同类型=0, 不同=1。"""
    w1 = 1 if d1.weekday() >= 5 else 0
    w2 = 1 if d2.weekday() >= 5 else 0
    return 0.0 if w1 == w2 else 1.0


def compute_date_decay(target_date, candidate_date):
    """
    日期距离衰减因子。
    近 90 天不衰减(0)，90天后指数衰减，半衰期 180 天。

    target_date, candidate_date : datetime 或 pd.Timestamp
    """
    delta_days = abs((target_date - candidate_date).days)
    if delta_days <= 90:
        return 0.0
    decay = 1.0 - np.exp(-(delta_days - 90) / 180.0)
    return float(decay)


# ============================================================
# 逐时 → 逐日聚合
# ============================================================

def compute_daily_weather(df: pd.DataFrame) -> pd.DataFrame:
    """
    将逐小时天气 DataFrame 聚合为逐日摘要。
    """
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["date"] = df["datetime"].dt.date

    agg_dict = {}
    if "temperature_2m" in df.columns:
        agg_dict["tmax"] = ("temperature_2m", "max")
        agg_dict["tmin"] = ("temperature_2m", "min")
    if "precipitation" in df.columns:
        agg_dict["precip_sum"] = ("precipitation", "sum")
    if "shortwave_radiation" in df.columns:
        agg_dict["rad_daily_sum"] = ("shortwave_radiation", "sum")
    if "dew_point_2m" in df.columns:
        agg_dict["dew_point_avg"] = ("dew_point_2m", "mean")

    daily = df.groupby("date", as_index=False).agg(**agg_dict)
    daily["date"] = pd.to_datetime(daily["date"])

    if "precip_sum" in daily.columns:
        daily["precip_level"] = daily["precip_sum"].apply(compute_precip_level)

    return daily


# ============================================================
# Z-Score 标准化
# ============================================================

def _fit_zscore(historical: pd.DataFrame, factor_keys: list[str]) -> dict:
    """从历史数据中学习每个因子的 mean/std。"""
    stats = {}
    for key in factor_keys:
        if key in historical.columns and historical[key].notna().any():
            s = historical[key].dropna()
            stats[key] = {"mean": float(s.mean()), "std": float(s.std()) or 1.0}
        else:
            stats[key] = {"mean": 0.0, "std": 1.0}
    return stats


def _zscore(val, params: dict) -> float:
    """标准化到 z-score。无信息时返回 0（即均值）。"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 0.0
    return float((val - params["mean"]) / params["std"])


def normalize_factors(historical: pd.DataFrame, target: dict,
                      factor_keys: list[str]) -> tuple[dict, dict]:
    """学习 z-score 参数并标准化目标日。"""
    stats = _fit_zscore(historical, factor_keys)
    normalized = {key: _zscore(target.get(key), stats[key]) for key in factor_keys}
    return normalized, stats


# ============================================================
# 加权距离计算 (v2)
# ============================================================

def compute_weighted_distance(
    norm_target: dict,
    norm_candidate: dict,
    candidate_discrete: dict,
    weights: dict,
) -> float:
    """
    计算加权距离（混合策略）。

    数值因子用曼哈顿距离（比欧氏距离对单维度差异更敏感）；
    离散/衰减因子直接使用 [0,1] 得分。

    数值距离乘以放大系数 ~4-6，使其与离散因子在同一尺度。
    """
    dist = 0.0

    SCALE = 5.0  # z-score 差异放大系数

    numeric_map = [
        ("tmax_deviation", "tmax"),
        ("tmin_deviation", "tmin"),
        ("radiation_deviation", "rad_daily_sum"),
        ("dew_point_deviation", "dew_point_avg"),
    ]
    for w_key, n_key in numeric_map:
        w = weights.get(w_key, 0.0)
        if w == 0:
            continue
        tv = norm_target.get(n_key, 0.0)
        cv = norm_candidate.get(n_key, 0.0)
        dist += w * SCALE * abs(tv - cv)

    discrete_map = [
        ("precip_match", "precip_match"),
        ("season_match", "season_match"),
        ("weekday_match", "weekday_match"),
        ("date_distance_decay", "date_distance_decay"),
    ]
    for w_key, d_key in discrete_map:
        w = weights.get(w_key, 0.0)
        val = candidate_discrete.get(d_key, 0.0)
        dist += w * val

    return dist


# ============================================================
# 主入口：查找相似日
# ============================================================

def find_similar_days(
    weather_df: pd.DataFrame,
    target_date: datetime,
    n: int = 3,
    weights: dict | None = None,
) -> list[dict]:
    """
    查找与目标日天气最相似的历史日期。

    参数
    ----
    weather_df : pd.DataFrame
        逐小时天气数据（含历史 + 预报）。
    target_date : datetime
        目标日期。
    n : int
        返回的相似日数量（默认 3）。
    weights : dict | None
        6因子权重。默认使用 config.SIMILARITY_WEIGHTS。
    """
    if weights is None:
        weights = SIMILARITY_WEIGHTS

    # 1. 聚合逐日
    daily = compute_daily_weather(weather_df)
    if daily.empty:
        return []

    # 2. 定位目标日
    target_dt = pd.Timestamp(target_date.date() if hasattr(target_date, "date") else target_date)
    target_row = daily[daily["date"] == target_dt]
    if target_row.empty:
        return []

    target_summary = {
        "tmax": _safe_get(target_row, "tmax"),
        "tmin": _safe_get(target_row, "tmin"),
        "precip_sum": _safe_get(target_row, "precip_sum"),
        "precip_level": _safe_get(target_row, "precip_level", 0),
        "rad_daily_sum": _safe_get(target_row, "rad_daily_sum"),
        "dew_point_avg": _safe_get(target_row, "dew_point_avg"),
    }

    # 3. 候选项（排除目标日本身）
    candidates = daily[daily["date"] != target_dt].copy()
    if candidates.empty:
        return []

    # 4. 晴雨硬约束：如果目标日是降水日，候选项也必须 > 0.1mm
    target_is_rainy = (target_summary.get("precip_sum") or 0) >= 0.5
    if target_is_rainy:
        rain_candidates = candidates[candidates["precip_sum"] >= 0.3]
        if len(rain_candidates) >= 10:
            candidates = rain_candidates

    # 5. z-score 标准化
    numeric_keys = ["tmax", "tmin", "rad_daily_sum", "dew_point_avg"]
    norm_target, stats = normalize_factors(candidates, target_summary, numeric_keys)

    # 6. 遍历所有候选项计算距离
    results = []
    season_names = ["冬", "春", "夏", "秋"]
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]

    # 降水归一化：用候选池中的 precip_sum 范围做线性映射
    precip_vals = candidates["precip_sum"].dropna()
    precip_min = float(precip_vals.min()) if not precip_vals.empty else 0.0
    precip_max = max(float(precip_vals.max()), 1.0) if not precip_vals.empty else 1.0

    for _, row in candidates.iterrows():
        cand_date = row["date"]
        if hasattr(cand_date, "to_pydatetime"):
            cand_date_py = cand_date.to_pydatetime()
        else:
            cand_date_py = cand_date

        # 数值因子 z-score 标准化
        cand_summary = {
            "tmax": row.get("tmax"),
            "tmin": row.get("tmin"),
            "rad_daily_sum": row.get("rad_daily_sum"),
            "dew_point_avg": row.get("dew_point_avg"),
        }
        norm_cand = {
            key: _zscore(cand_summary.get(key), stats[key])
            for key in numeric_keys
        }

        # 离散因子
        season_val = match_season(target_dt, cand_date_py)
        weekday_val = match_weekday(target_dt, cand_date_py)
        decay_val = compute_date_decay(target_dt, cand_date_py)

        # 降水：连续距离 + 等级交叉
        # 先用连续值归一化到 [0,1]，再与等级差混合
        target_p = target_summary.get("precip_sum") or 0.0
        cand_p = row.get("precip_sum") or 0.0
        precip_dist = abs(target_p - cand_p)
        # 对数压缩：降水 mm 差距小的时候精度高，差距大时影响递减
        if precip_dist <= 1.0:
            precip_continuous = precip_dist / 5.0  # [0, 0.2]
        elif precip_dist <= 10.0:
            precip_continuous = 0.2 + (precip_dist - 1.0) / 45.0  # [0.2, 0.4]
        else:
            precip_continuous = min(0.4 + (precip_dist - 10.0) / 200.0, 0.7)

        cand_plvl = int(row.get("precip_level", 0))
        target_plvl = target_summary.get("precip_level", 0)
        precip_level_dist = abs(target_plvl - cand_plvl) / 5.0  # [0, 1]

        # 混合距离：连续差异 70% + 等级差异 30%
        precip_match = 0.7 * precip_continuous + 0.3 * precip_level_dist

        candidate_discrete = {
            "precip_match": precip_match,
            "season_match": season_val,
            "weekday_match": weekday_val,
            "date_distance_decay": decay_val,
        }

        distance = compute_weighted_distance(
            norm_target, norm_cand, candidate_discrete, weights,
        )

        components = {
            "最高温偏差": weights.get("tmax_deviation", 0) * abs(norm_target["tmax"] - norm_cand["tmax"]),
            "最低温偏差": weights.get("tmin_deviation", 0) * abs(norm_target["tmin"] - norm_cand["tmin"]),
            "辐射偏差": weights.get("radiation_deviation", 0) * abs(norm_target["rad_daily_sum"] - norm_cand["rad_daily_sum"]),
            "露点偏差": weights.get("dew_point_deviation", 0) * abs(norm_target["dew_point_avg"] - norm_cand["dew_point_avg"]),
            "降水差异": weights.get("precip_match", 0) * precip_match,
            "季节匹配": weights.get("season_match", 0) * season_val,
            "星期类型": weights.get("weekday_match", 0) * weekday_val,
            "日期距离": weights.get("date_distance_decay", 0) * decay_val,
        }

        results.append({
            "date": cand_date_py,
            "similarity_score": distance,
            "tmax": row.get("tmax"),
            "tmin": row.get("tmin"),
            "precip_sum": row.get("precip_sum"),
            "precip_level": int(row.get("precip_level", 0)),
            "rad_daily_sum": row.get("rad_daily_sum"),
            "dew_point_avg": row.get("dew_point_avg"),
            "season_label": season_names[_season_idx(cand_date_py)],
            "weekday_label": weekday_names[cand_date_py.weekday()],
            "distance_components": components,
        })

    # 7. 排序并转换相似度
    # 用指数衰减: similarity = e^(-d/σ), σ = 距离中位数
    results.sort(key=lambda x: x["similarity_score"])
    sigma = np.median([r["similarity_score"] for r in results]) if results else 1.0
    if sigma < 0.001:
        sigma = 1.0
    for r in results:
        r["similarity_pct"] = max(0.0, round(100.0 * np.exp(-r["similarity_score"] / sigma), 1))

    return results[:n]


def _safe_get(row, col, default=None):
    """安全从 DataFrame 行取值。"""
    try:
        val = row[col].values[0] if hasattr(row[col], "values") else row[col]
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return val
    except (KeyError, IndexError):
        return default
