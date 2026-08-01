"""
概览卡片：当前温度、今日降水、平均风速、太阳总辐射
"""

import streamlit as st
import pandas as pd
from datetime import datetime


def render_overview_cards(df: pd.DataFrame):
    """
    渲染顶部概览卡片行（4列）。

    参数
    ----
    df : pd.DataFrame
        逐小时数据，需含当前时刻附近的数据。
    """
    if df.empty:
        st.info("暂无数据")
        return

    now = datetime.now()
    # 找最近整点的数据
    df_sorted = df.copy()
    if "datetime" in df.columns:
        df_sorted = df_sorted.dropna(subset=["datetime"])
        df_sorted["_diff"] = abs((df_sorted["datetime"] - now).dt.total_seconds())
        latest = df_sorted.loc[df_sorted["_diff"].idxmin()]
    else:
        latest = df_sorted.iloc[-1] if len(df_sorted) > 0 else None

    if latest is None:
        st.info("暂无当前数据")
        return

    # 今日累计量
    today = now.date()
    today_mask = df["datetime"].dt.date == today if "datetime" in df.columns else pd.Series([False] * len(df))

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        temp = latest.get("temperature_2m", "—")
        apparent = latest.get("apparent_temp_cn", latest.get("apparent_temperature", "—"))
        temp_str = f"{temp:.1f}°C" if isinstance(temp, (int, float)) and not pd.isna(temp) else "—°C"
        app_str = f"体感 {apparent:.1f}°C" if isinstance(apparent, (int, float)) and not pd.isna(apparent) else ""
        st.metric(
            label="当前温度",
            value=temp_str,
            delta=app_str if app_str else None,
        )

    with col2:
        precip_today = df.loc[today_mask, "precipitation"].sum() if "precipitation" in df.columns else 0
        precip_str = f"{precip_today:.1f} mm" if isinstance(precip_today, (int, float)) and not pd.isna(precip_today) else "— mm"
        # 粗略降水概率（有降水的时段占比）
        if "precipitation" in df.columns and today_mask.any():
            rain_hours = (df.loc[today_mask, "precipitation"] > 0.1).sum()
            total_hours = today_mask.sum()
            prob = f"概率 {rain_hours / max(total_hours, 1) * 100:.0f}%"
        else:
            prob = ""
        st.metric(
            label="今日降水",
            value=precip_str,
            delta=prob if prob else None,
        )

    with col3:
        wind = latest.get("wind_speed_10m", "—")
        wind_str = f"{wind:.1f} km/h" if isinstance(wind, (int, float)) and not pd.isna(wind) else "— km/h"

        wind_dir = latest.get("wind_direction_10m", None)
        if isinstance(wind_dir, (int, float)) and not pd.isna(wind_dir):
            dir_str = _wind_dir_label(wind_dir)
        else:
            dir_str = ""
        st.metric(
            label="平均风速",
            value=wind_str,
            delta=dir_str if dir_str else None,
        )

    with col4:
        radiation = latest.get("shortwave_radiation", "—")
        if isinstance(radiation, (int, float)) and not pd.isna(radiation):
            rad_str = f"{radiation:.0f} W/m²"
        else:
            rad_str = "— W/m²"

        cloud = latest.get("cloud_cover", None)
        if isinstance(cloud, (int, float)) and not pd.isna(cloud):
            cloud_str = f"云量 {cloud:.0f}%"
        else:
            cloud_str = ""
        st.metric(
            label="太阳总辐射",
            value=rad_str,
            delta=cloud_str if cloud_str else None,
        )


def _wind_dir_label(degrees: float) -> str:
    """将风向角度转为 8 方位中文标签。"""
    directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    idx = round(degrees / 45) % 8
    return f"{directions[idx]}风"
