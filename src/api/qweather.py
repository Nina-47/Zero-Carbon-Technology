"""
和风天气 API 封装 — 备用数据源
文档: https://dev.qweather.com/docs/api/
"""

import pandas as pd
import requests
import streamlit as st
from config import (
    QWATHER_FORECAST_URL,
    QWATHER_HISTORY_URL,
    API_TIMEOUT_SECONDS,
)


def _get_api_key() -> str | None:
    """从 Streamlit Secrets 或环境变量获取和风天气 API Key。"""
    try:
        return st.secrets.get("QWATHER_API_KEY", None)
    except Exception:
        import os
        return os.environ.get("QWATHER_API_KEY", None)


def is_available() -> bool:
    """检查和风天气备用源是否可用。"""
    return _get_api_key() is not None


def fetch_forecast_qweather(
    latitude: float,
    longitude: float,
    location_id: str,
    forecast_days: int = 3,
) -> pd.DataFrame | None:
    """
    从和风天气获取逐小时预报（备用）。

    注意：和风天气的免费 API 仅支持 24h-7d 逐日，
    逐小时需要付费版。此处提供基础实现框架。
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    # 和风天气需要 Location ID，先查询
    location_key = f"{longitude:.2f},{latitude:.2f}"
    params = {
        "location": location_key,
        "key": api_key,
    }
    try:
        resp = requests.get(
            QWATHER_FORECAST_URL,
            params=params,
            timeout=API_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "200":
            return None

        hourly = data.get("hourly", [])
        if not hourly:
            return None

        df = pd.DataFrame(hourly)
        df["datetime"] = pd.to_datetime(df["fxTime"])
        df["location_id"] = location_id
        df["data_type"] = "forecast"
        df["source"] = "qweather"

        # 字段映射：和风天气 → 统一列名
        col_map = {
            "temp": "temperature_2m",
            "humidity": "relative_humidity_2m",
            "precip": "precipitation",
            "windSpeed": "wind_speed_10m",
            "windDir": "wind_direction_10m",
            "pressure": "surface_pressure",
            "cloud": "cloud_cover",
        }
        df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
        return df

    except (requests.Timeout, requests.ConnectionError, Exception):
        return None


def fetch_historical_qweather(
    latitude: float,
    longitude: float,
    location_id: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
    """
    从和风天气获取历史天气（备用）。
    免费版仅支持最近 7 天。
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    location_key = f"{longitude:.2f},{latitude:.2f}"
    params = {
        "location": location_key,
        "key": api_key,
        "date": start_date,
    }
    try:
        resp = requests.get(
            QWATHER_HISTORY_URL,
            params=params,
            timeout=API_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "200":
            return None

        hourly = data.get("weatherHourly", [])
        if not hourly:
            return None

        df = pd.DataFrame(hourly)
        df["datetime"] = pd.to_datetime(df["time"])
        df["location_id"] = location_id
        df["data_type"] = "historical"
        df["source"] = "qweather"

        col_map = {
            "temp": "temperature_2m",
            "humidity": "relative_humidity_2m",
            "precip": "precipitation",
            "windSpeed": "wind_speed_10m",
            "windDir": "wind_direction_10m",
            "pressure": "surface_pressure",
        }
        df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)
        return df

    except (requests.Timeout, requests.ConnectionError, Exception):
        return None
