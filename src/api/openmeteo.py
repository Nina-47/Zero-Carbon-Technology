"""
Open-Meteo API 封装 — 历史数据 (ERA5-Land) + 预报数据
"""

import time
import pandas as pd
import requests
from config import (
    OPENMETEO_ARCHIVE_URL,
    OPENMETEO_FORECAST_URL,
    FORECAST_PARAMS_STR,
    ARCHIVE_PARAMS_STR,
    TIMEZONE,
    API_TIMEOUT_SECONDS,
)


def _build_hourly_df(response_json: dict, location_id: str, data_type: str) -> pd.DataFrame:
    """将 Open-Meteo JSON 响应解析为逐小时 DataFrame。"""
    hourly = response_json.get("hourly", {})
    if not hourly or "time" not in hourly:
        raise ValueError(f"API 返回数据为空: {response_json}")

    df = pd.DataFrame(hourly)
    df.rename(columns={"time": "datetime"}, inplace=True)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["location_id"] = location_id
    df["data_type"] = data_type
    df["source"] = "openmeteo"
    return df


def fetch_forecast(
    latitude: float,
    longitude: float,
    location_id: str,
    forecast_days: int = 3,
    past_days: int = 0,
) -> pd.DataFrame:
    """
    获取逐小时天气预报（含近期历史）。

    参数
    ----
    latitude, longitude : float
        目标坐标。
    location_id : str
        地点标识。
    forecast_days : int
        预报天数 (默认 3)。
    past_days : int
        往回拉的天数（Forecast API 最多支持 92 天）。

    返回
    ----
    pd.DataFrame
        逐小时预报数据，列包含所有 EXPORT_PARAMS 中的气象参数。
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": FORECAST_PARAMS_STR,
        "forecast_days": forecast_days,
        "past_days": past_days,
        "timezone": TIMEZONE,
    }
    resp = requests.get(
        OPENMETEO_FORECAST_URL,
        params=params,
        timeout=API_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data_type = "historical" if past_days > 0 and forecast_days == 0 else "forecast"
    return _build_hourly_df(resp.json(), location_id, data_type)


def fetch_historical(
    latitude: float,
    longitude: float,
    location_id: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    获取历史逐小时天气数据 (ERA5-Land)。

    参数
    ----
    latitude, longitude : float
        目标坐标。
    location_id : str
        地点标识。
    start_date, end_date : str
        日期范围 'YYYY-MM-DD'。

    返回
    ----
    pd.DataFrame
        逐小时历史数据。
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ARCHIVE_PARAMS_STR,
        "timezone": TIMEZONE,
    }
    resp = requests.get(
        OPENMETEO_ARCHIVE_URL,
        params=params,
        timeout=API_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return _build_hourly_df(resp.json(), location_id, "historical")


def fetch_with_retry(
    fetch_func,
    *args,
    max_retries: int = 2,
    **kwargs,
) -> pd.DataFrame:
    """
    带重试的 API 调用包装器。

    参数
    ----
    fetch_func : callable
        fetch_forecast 或 fetch_historical。
    max_retries : int
        最大重试次数。

    返回
    ----
    pd.DataFrame 或抛出异常。
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return fetch_func(*args, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_error = e
            if attempt < max_retries:
                wait = 2 ** attempt  # 指数退避: 1s, 2s
                time.sleep(wait)
    raise last_error
