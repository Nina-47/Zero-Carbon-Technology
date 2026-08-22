"""
双源切换逻辑：Open-Meteo（主）→ 和风天气（备）
"""

import pandas as pd
import streamlit as st
from src.api.openmeteo import fetch_forecast as om_fetch_forecast
from src.api.openmeteo import fetch_historical as om_fetch_historical
from src.api.qweather import is_available as qw_available
from src.api.qweather import fetch_forecast_qweather
from src.api.qweather import fetch_historical_qweather


class DataSourceStatus:
    """数据源状态追踪。"""

    def __init__(self):
        self.primary_ok = True
        self.fallback_used = False
        self.error_message = ""

    @property
    def status_icon(self) -> str:
        if not self.primary_ok and self.fallback_used:
            return "🟡"  # 使用了备用源
        if not self.primary_ok and not self.fallback_used:
            return "🔴"  # 双源失败
        return "🟢"  # 正常

    @property
    def status_text(self) -> str:
        if not self.primary_ok and self.fallback_used:
            return "备用数据源"
        if not self.primary_ok and not self.fallback_used:
            return "数据更新失败"
        return "数据正常"


def fetch_forecast_safe(
    latitude: float,
    longitude: float,
    location_id: str,
    forecast_days: int = 3,
    status: DataSourceStatus | None = None,
) -> pd.DataFrame:
    """
    获取预报数据，主源失败自动 fallback 到备用源。

    返回
    ----
    pd.DataFrame
        成功时返回数据；双源均失败时返回空 DataFrame。
    """
    if status is None:
        status = DataSourceStatus()

    # 尝试主源
    try:
        df = om_fetch_forecast(latitude, longitude, location_id, forecast_days)
        status.primary_ok = True
        return df
    except Exception as e:
        status.primary_ok = False
        status.error_message = str(e)

    # Fallback 到备用源
    if qw_available():
        try:
            df = fetch_forecast_qweather(latitude, longitude, location_id, forecast_days)
            if df is not None and not df.empty:
                status.fallback_used = True
                return df
        except Exception:
            pass

    # 双源均失败
    return pd.DataFrame()


def fetch_historical_safe(
    latitude: float,
    longitude: float,
    location_id: str,
    start_date: str,
    end_date: str,
    status: DataSourceStatus | None = None,
) -> pd.DataFrame:
    """
    获取历史数据，主源失败自动 fallback 到备用源。
    """
    if status is None:
        status = DataSourceStatus()

    # 尝试主源
    try:
        df = om_fetch_historical(latitude, longitude, location_id, start_date, end_date)
        status.primary_ok = True
        return df
    except Exception as e:
        status.primary_ok = False
        status.error_message = str(e)

    # Fallback 到备用源
    if qw_available():
        try:
            df = fetch_historical_qweather(latitude, longitude, location_id, start_date, end_date)
            if df is not None and not df.empty:
                status.fallback_used = True
                return df
        except Exception:
            pass

    return pd.DataFrame()


def fetch_past_days_safe(
    latitude: float,
    longitude: float,
    location_id: str,
    past_days: int = 92,
    status: DataSourceStatus | None = None,
) -> pd.DataFrame:
    """
    用 Forecast API 的 past_days 参数拉取近期历史（最多 92 天）。
    这个端点比 Archive API 更稳定，在国内能通。
    """
    if status is None:
        status = DataSourceStatus()

    try:
        df = om_fetch_forecast(latitude, longitude, location_id, forecast_days=0, past_days=past_days)
        df["data_type"] = "historical"
        status.primary_ok = True
        return df
    except Exception as e:
        status.primary_ok = False
        status.error_message = str(e)

    return pd.DataFrame()
