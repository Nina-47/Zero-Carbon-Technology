"""
天气总览图表：温度、降水、风况、日照小时数
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from config import VIS_PARAMS


def plot_temperature(df: pd.DataFrame, location_label: str = "") -> go.Figure:
    """
    温度曲线：实际温度 + 体感温度（双折线）。
    历史实线，预报虚线。
    """
    fig = go.Figure()

    if "datetime" not in df.columns or df.empty:
        return fig

    # 区分历史和预报
    hist_mask = df.get("data_type", pd.Series(["historical"] * len(df))) == "historical"
    forecast_mask = ~hist_mask

    for col, label, color in [
        ("temperature_2m", "实际/预报温度", "#E74C3C"),
        ("apparent_temp_cn", "体感温度(中国公式)", "#E67E22"),
    ]:
        if col not in df.columns:
            continue

        # 历史部分（实线）
        hist_data = df[hist_mask] if hist_mask.any() else pd.DataFrame()
        if not hist_data.empty and col in hist_data.columns:
            fig.add_trace(go.Scatter(
                x=hist_data["datetime"], y=hist_data[col],
                mode="lines", name=f"{label} (历史)",
                line=dict(color=color, width=2, dash="solid"),
                legendgroup=col,
            ))

        # 预报部分（虚线）
        fc_data = df[forecast_mask] if forecast_mask.any() else pd.DataFrame()
        if not fc_data.empty and col in fc_data.columns:
            fig.add_trace(go.Scatter(
                x=fc_data["datetime"], y=fc_data[col],
                mode="lines", name=f"{label} (预报)",
                line=dict(color=color, width=2, dash="dot"),
                legendgroup=col,
            ))

    fig.update_layout(
        title=f"🌡️ 温度曲线 {location_label}",
        xaxis_title="时间",
        yaxis_title="温度 (°C)",
        hovermode="x unified",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def plot_precipitation(df: pd.DataFrame, location_label: str = "") -> go.Figure:
    """
    降水柱状图 + 24h 累积降水折线（右Y轴）。
    """
    if "precipitation" not in df.columns or "datetime" not in df.columns or df.empty:
        return go.Figure()

    df = df.copy().sort_values("datetime")
    df["cumulative_24h"] = df["precipitation"].rolling(24, min_periods=1).sum()

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 逐小时降水柱状图
    fig.add_trace(
        go.Bar(
            x=df["datetime"], y=df["precipitation"],
            name="逐小时降水",
            marker=dict(color="#3498DB", opacity=0.7),
        ),
        secondary_y=False,
    )

    # 24h 累积折线
    fig.add_trace(
        go.Scatter(
            x=df["datetime"], y=df["cumulative_24h"],
            mode="lines", name="24h累积降水",
            line=dict(color="#2C3E50", width=2),
        ),
        secondary_y=True,
    )

    # 暴雨阈值线 (50mm/24h)
    max_x = df["datetime"].max()
    min_x = df["datetime"].min()
    fig.add_hline(
        y=50, line_dash="dash", line_color="#E74C3C",
        secondary_y=True,
        annotation_text="暴雨阈值 50mm",
    )

    fig.update_layout(
        title=f"🌧️ 降水 {location_label}",
        hovermode="x unified",
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_yaxes(title_text="降水量 (mm)", secondary_y=False)
    fig.update_yaxes(title_text="24h累积 (mm)", secondary_y=True)

    return fig


def plot_wind(df: pd.DataFrame, location_label: str = "") -> go.Figure:
    """
    风速折线 + 风向标记点。
    """
    if "wind_speed_10m" not in df.columns or "datetime" not in df.columns or df.empty:
        return go.Figure()

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["datetime"], y=df["wind_speed_10m"],
        mode="lines", name="风速",
        line=dict(color="#1ABC9C", width=2),
        fill="tozeroy",
        fillcolor="rgba(26, 188, 156, 0.1)",
    ))

    # 风向标记（每隔 N 个点显示一个）
    if "wind_direction_10m" in df.columns:
        step = max(1, len(df) // 24)
        marker_df = df.iloc[::step]
        fig.add_trace(go.Scatter(
            x=marker_df["datetime"], y=marker_df["wind_speed_10m"],
            mode="markers+text",
            name="风向",
            marker=dict(
                symbol="triangle-up",
                size=12,
                color="#2C3E50",
            ),
            text=[_dir_arrow(d) for d in marker_df["wind_direction_10m"].fillna(0)],
            textposition="top center",
            textfont=dict(size=14),
            showlegend=False,
        ))

    fig.update_layout(
        title=f"💨 风况 {location_label}",
        xaxis_title="时间",
        yaxis_title="风速 (km/h)",
        hovermode="x unified",
        height=280,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig


def plot_sunshine(df: pd.DataFrame, location_label: str = "") -> go.Figure:
    """
    日照小时数面积图，叠加云量虚线（右Y轴倒置）。
    """
    if "sunshine_duration" not in df.columns or "datetime" not in df.columns or df.empty:
        return go.Figure()

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 日照面积
    fig.add_trace(
        go.Scatter(
            x=df["datetime"], y=df["sunshine_duration"],
            mode="none", name="日照时长",
            fill="tozeroy",
            fillcolor="rgba(241, 196, 15, 0.4)",
            line=dict(color="#F1C40F"),
        ),
        secondary_y=False,
    )

    # 日照边界线
    fig.add_trace(
        go.Scatter(
            x=df["datetime"], y=df["sunshine_duration"],
            mode="lines", name="日照值",
            line=dict(color="#F39C12", width=1.5),
            showlegend=False,
        ),
        secondary_y=False,
    )

    # 云量虚线（倒置：云量越高，线越低）
    if "cloud_cover" in df.columns:
        # 将云量映射到日照Y轴范围的倒置
        sun_max = df["sunshine_duration"].max() or 1.0
        scaled_cloud = (100 - df["cloud_cover"]) / 100 * sun_max
        fig.add_trace(
            go.Scatter(
                x=df["datetime"], y=scaled_cloud,
                mode="lines", name="云量 (倒置)",
                line=dict(color="#7F8C8D", width=1.5, dash="dot"),
            ),
            secondary_y=False,
        )

    fig.update_layout(
        title=f"☀️ 日照小时 {location_label}",
        xaxis_title="时间",
        hovermode="x unified",
        height=280,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_yaxes(title_text="日照 (h)", secondary_y=False)

    return fig


def _dir_arrow(degrees: float) -> str:
    """风向角度 → 箭头符号。"""
    arrows = ["↓", "↙", "←", "↖", "↑", "↗", "→", "↘"]
    idx = round(degrees / 45) % 8
    return arrows[idx]
