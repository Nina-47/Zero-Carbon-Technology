"""
广东省平均数据计算：对 5 个代表城市取算术平均（或求和）。
"""

import pandas as pd
from datetime import datetime, timedelta
from config import (
    LOCATIONS,
    AGGREGATION_SUM_PARAMS,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_FORECAST_DAYS,
    convert_units,
)
from src.api.fallback import (
    fetch_forecast_safe,
    fetch_historical_safe,
    DataSourceStatus,
)


def compute_province_average(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """
    对多个城市的数据计算广东省平均值。

    规则：
    - 降水量等累积量 → 求和
    - 温度、湿度、风等连续量 → 算术平均
    - 风向 → 矢量平均（单位圆均值）

    参数
    ----
    dfs : list[pd.DataFrame]
        各城市的逐小时数据，datetime 对齐后取平均。

    返回
    ----
    pd.DataFrame
        聚合后的省平均数据。
    """
    if not dfs:
        return pd.DataFrame()

    # 合并所有城市数据，按 datetime 对齐
    all_data = pd.concat(dfs, ignore_index=True)

    # 获取参数列（排除元数据列）
    meta_cols = {"location_id", "datetime", "data_type", "source", "fetched_at"}
    param_cols = [c for c in all_data.columns if c not in meta_cols]

    # 按 datetime 分组聚合（as_index=True，聚合后 reset_index 生成唯一 datetime 列）
    grouped = all_data.groupby("datetime", as_index=True)

    agg_results = {}
    for col in param_cols:
        if col == "wind_direction_10m":
            agg_results[col] = grouped[col].apply(_wind_dir_vector_mean)
        elif col in AGGREGATION_SUM_PARAMS:
            agg_results[col] = grouped[col].sum()
        else:
            agg_results[col] = grouped[col].mean()

    result = pd.DataFrame(agg_results).reset_index()
    # reset_index() 将 datetime 索引转为列，保证唯一，不会出现重复列

    # 元数据
    result["location_id"] = "guangdong_avg"
    if "data_type" in all_data.columns:
        result["data_type"] = all_data["data_type"].iloc[0]
    result["source"] = "openmeteo"

    return result


def _wind_dir_vector_mean(series: pd.Series) -> float:
    """风向矢量平均（单位圆取均值后转回角度）。"""
    import numpy as np
    values = series.dropna().values
    if len(values) == 0:
        return float("nan")
    radians = np.deg2rad(values)
    sin_mean = np.nanmean(np.sin(radians))
    cos_mean = np.nanmean(np.cos(radians))
    mean_deg = np.rad2deg(np.arctan2(sin_mean, cos_mean))
    return float(mean_deg % 360)


def fetch_guangdong_average(
    data_type: str,
    status: DataSourceStatus | None = None,
    history_days: int = DEFAULT_HISTORY_DAYS,
    forecast_days: int = DEFAULT_FORECAST_DAYS,
) -> pd.DataFrame:
    """
    获取广东省平均天气数据。

    参数
    ----
    data_type : str
        'historical' 或 'forecast'。
    status : DataSourceStatus | None
    history_days, forecast_days : int

    返回
    ----
    pd.DataFrame
        聚合后的省平均数据。
    """
    child_cities = LOCATIONS["guangdong_avg"]["child_cities"]
    all_dfs = []
    today = datetime.now()

    for city_id, city_info in child_cities.items():
        lat = city_info["latitude"]
        lon = city_info["longitude"]

        if data_type == "historical":
            end_date = today.strftime("%Y-%m-%d")
            start_date = (today - timedelta(days=history_days)).strftime("%Y-%m-%d")
            df = fetch_historical_safe(lat, lon, city_id, start_date, end_date, status)
        else:
            df = fetch_forecast_safe(lat, lon, city_id, forecast_days, status)

        if not df.empty:
            # 先算每市体感温度（非线性公式，逐城计算后平均才准确）
            df = convert_units(df)
            all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    result = compute_province_average(all_dfs)
    # 注意: convert_units 已在逐城阶段调用，此处不再重复调用
    # sunshine_duration 已在小时单位，聚合后无需再次换算
    return result
