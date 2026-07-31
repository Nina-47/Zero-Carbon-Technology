"""
相似日分析核心算法模块

基于加权欧氏距离（min-max标准化），从历史天气数据中找出
与目标日气象条件最相似的 Top-N 日期，用于辅助工业负荷预测。

8因子权重定义见 config.SIMILARITY_WEIGHTS。
"""

import numpy as np
import pandas as pd
from datetime import datetime

from config import SIMILARITY_WEIGHTS, PRECIP_LEVELS


# ============================================================
# 辅助函数：降水等级 / 季节匹配 / 星期匹配 / 日期衰减
# ============================================================

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
    """
    季节匹配得分：同季=0, 相邻季=0.5, 相反季=1。

    参数
    ----
    d1, d2 : datetime 或 pd.Timestamp
    """
    s1, s2 = _season_idx(d1), _season_idx(d2)
    if s1 == s2:
        return 0.0
    diff = abs(s1 - s2)
    if diff == 2:  # 冬↔夏 或 春↔秋
        return 1.0
    return 0.5


def match_weekday(d1, d2):
    """
    星期类型匹配：同类型(工作日/周末)=0, 不同=1。
    """
    w1 = 1 if d1.weekday() >= 5 else 0
    w2 = 1 if d2.weekday() >= 5 else 0
    return 0.0 if w1 == w2 else 1.0


def compute_date_decay(target_date, candidate_date, max_days=365):
    """
    日期距离衰减因子（指数衰减）。
    越远惩罚越大，范围 [0, 1)。半衰期约 180 天。

    参数
    ----
    target_date, candidate_date : datetime 或 pd.Timestamp
    """
    delta_days = abs((target_date - candidate_date).days)
    if delta_days <= 1:
        return 0.0
    decay = 1.0 - np.exp(-delta_days / 180.0)
    return float(decay)


# ============================================================
# 逐时 → 逐日聚合
# ============================================================

def compute_daily_weather(df: pd.DataFrame) -> pd.DataFrame:
    """
    将逐小时天气 DataFrame 聚合为逐日摘要。

    参数
    ----
    df : pd.DataFrame
        逐小时天气数据。需包含 datetime 列及以下气象参数列
        （列名与 EXPORT_PARAMS 一致）：
        - temperature_2m
        - precipitation
        - shortwave_radiation
        - dew_point_2m

    返回
    ----
    pd.DataFrame
        每日一行，列：
        date, tmax, tmin, precip_sum, precip_level,
        rad_daily_sum, dew_point_avg
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

    # 派生：降水等级
    if "precip_sum" in daily.columns:
        daily["precip_level"] = daily["precip_sum"].apply(compute_precip_level)

    return daily


# ============================================================
# Min-Max 标准化
# ============================================================

def _fit_min_max(historical: pd.DataFrame, factor_keys: list[str]) -> dict:
    """从历史数据中学习每个因子的 min/max/range。"""
    min_max = {}
    for key in factor_keys:
        if key in historical.columns and historical[key].notna().any():
            vmin = float(historical[key].min())
            vmax = float(historical[key].max())
            rng = vmax - vmin
            min_max[key] = {"min": vmin, "max": vmax, "range": rng if rng > 0 else 1.0}
        else:
            min_max[key] = {"min": 0.0, "max": 1.0, "range": 1.0}
    return min_max


def _normalize(val, params: dict) -> float:
    """将单个值缩放到 [0, 1]。无信息时返回 0.5。"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 0.5
    if params["range"] == 0:
        return 0.5
    return float((val - params["min"]) / params["range"])


def normalize_factors(historical: pd.DataFrame, target: dict,
                      factor_keys: list[str]) -> tuple[dict, dict]:
    """
    学习 min-max 参数并标准化目标日。

    返回
    ----
    (normalized_target, min_max_params)
        normalized_target : {key: float}  目标日各因子标准化值
        min_max_params    : {key: {min, max, range}}  供候选项复用
    """
    min_max = _fit_min_max(historical, factor_keys)
    normalized = {key: _normalize(target.get(key), min_max[key]) for key in factor_keys}
    return normalized, min_max


# ============================================================
# 加权距离计算
# ============================================================

def compute_weighted_distance(
    norm_target: dict,
    norm_candidate: dict,
    candidate_discrete: dict,
    weights: dict,
) -> float:
    """
    计算加权欧氏距离。

    数值因子使用标准化后的欧氏距离分量；
    离散/衰减因子直接使用其 [0,1] 得分作为距离分量。

    参数
    ----
    norm_target : dict
        目标日数值因子标准化值 {tmax, tmin, rad_daily_sum, dew_point_avg}
    norm_candidate : dict
        候选项数值因子标准化值（同上结构）
    candidate_discrete : dict
        候选项离散因子 {precip_level_match, season_match, weekday_match, date_distance_decay}
    weights : dict
        因子权重（来自 config.SIMILARITY_WEIGHTS）

    返回
    ----
    float : 加权欧氏距离（越小越相似）
    """
    dist_sq = 0.0

    # --- 数值因子 ---
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
        tv = norm_target.get(n_key, 0.5)
        cv = norm_candidate.get(n_key, 0.5)
        dist_sq += w * ((tv - cv) ** 2)

    # --- 离散 / 衰减因子 ---
    discrete_map = [
        ("precip_level_match", "precip_level_match"),
        ("season_match", "season_match"),
        ("weekday_match", "weekday_match"),
        ("date_distance_decay", "date_distance_decay"),
    ]
    for w_key, d_key in discrete_map:
        w = weights.get(w_key, 0.0)
        val = candidate_discrete.get(d_key, 0.0)
        dist_sq += w * (val ** 2)

    return float(np.sqrt(dist_sq))


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
        需包含 datetime 列及 EXPORT_PARAMS 中的气象参数。
    target_date : datetime
        目标日期（通常为未来预报日）。
    n : int
        返回的相似日数量（默认 3）。
    weights : dict | None
        8因子权重。默认使用 config.SIMILARITY_WEIGHTS。

    返回
    ----
    list[dict]
        Top-N 相似日（按相似度降序），每项包含：
        - date, similarity_score (距离), similarity_pct (0-100%)
        - tmax, tmin, precip_sum, precip_level, rad_daily_sum, dew_point_avg
        - season_label, weekday_label
        - distance_components: {因子名: 加权距离分量}
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

    # 3. 候选项（仅历史，排除目标日及之后）
    candidates = daily[daily["date"] < target_dt].copy()
    if candidates.empty:
        return []

    # 4. Min-max 标准化
    numeric_keys = ["tmax", "tmin", "rad_daily_sum", "dew_point_avg"]
    norm_target, min_max = normalize_factors(candidates, target_summary, numeric_keys)

    # 5. 遍历所有候选项计算距离
    results = []
    season_names = ["冬", "春", "夏", "秋"]
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]

    for _, row in candidates.iterrows():
        cand_date = row["date"]
        if hasattr(cand_date, "to_pydatetime"):
            cand_date_py = cand_date.to_pydatetime()
        else:
            cand_date_py = cand_date

        # 数值因子标准化
        cand_summary = {
            "tmax": row.get("tmax"),
            "tmin": row.get("tmin"),
            "rad_daily_sum": row.get("rad_daily_sum"),
            "dew_point_avg": row.get("dew_point_avg"),
        }
        norm_cand = {
            key: _normalize(cand_summary.get(key), min_max[key])
            for key in numeric_keys
        }

        # 离散因子
        season_val = match_season(target_dt, cand_date_py)
        weekday_val = match_weekday(target_dt, cand_date_py)
        decay_val = compute_date_decay(target_dt, cand_date_py)

        target_plvl = target_summary.get("precip_level", 0)
        cand_plvl = int(row.get("precip_level", 0))
        precip_match = abs(target_plvl - cand_plvl) / 5.0  # [0, 1]

        candidate_discrete = {
            "precip_level_match": precip_match,
            "season_match": season_val,
            "weekday_match": weekday_val,
            "date_distance_decay": decay_val,
        }

        distance = compute_weighted_distance(
            norm_target, norm_cand, candidate_discrete, weights,
        )

        # 各因子分量（用于分解图）
        components = {
            "最高温偏差": weights.get("tmax_deviation", 0) * abs(norm_target["tmax"] - norm_cand["tmax"]),
            "最低温偏差": weights.get("tmin_deviation", 0) * abs(norm_target["tmin"] - norm_cand["tmin"]),
            "辐射偏差": weights.get("radiation_deviation", 0) * abs(norm_target["rad_daily_sum"] - norm_cand["rad_daily_sum"]),
            "露点偏差": weights.get("dew_point_deviation", 0) * abs(norm_target["dew_point_avg"] - norm_cand["dew_point_avg"]),
            "降水等级": weights.get("precip_level_match", 0) * precip_match,
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

    # 6. 排序并转换相似度
    results.sort(key=lambda x: x["similarity_score"])
    max_dist = max(r["similarity_score"] for r in results) if results else 1.0
    for r in results:
        if max_dist > 0:
            r["similarity_pct"] = max(0.0, round(100.0 * (1.0 - r["similarity_score"] / max_dist), 1))
        else:
            r["similarity_pct"] = 100.0

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
