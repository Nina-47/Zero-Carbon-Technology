"""
负荷叠加分析图表：降水-负荷叠加、温度-负荷散点、多因子面板、相关性统计
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import pearsonr


def plot_precip_load_overlay(
    weather_df: pd.DataFrame,
    load_df: pd.DataFrame,
    location_label: str = "",
) -> go.Figure:
    """
    降水-负荷叠加图（核心图表）：
    负荷折线（左Y轴，MW）+ 降水量柱（右Y轴，mm，倒置）。
    """
    if weather_df.empty or load_df.empty:
        return go.Figure()

    # 对齐时间
    merged = _align_weather_load(weather_df, load_df)

    if merged.empty:
        return go.Figure()

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 负荷曲线（左Y轴）
    fig.add_trace(
        go.Scatter(
            x=merged["datetime"], y=merged["load_mw"],
            mode="lines", name="负荷 (MW)",
            line=dict(color="#E74C3C", width=2),
        ),
        secondary_y=False,
    )

    # 降水柱状图（右Y轴，倒置）
    if "precipitation" in merged.columns:
        merged["precip_inverted"] = -merged["precipitation"]
        fig.add_trace(
            go.Bar(
                x=merged["datetime"], y=merged["precip_inverted"],
                name="降水量 (mm)",
                marker=dict(color="#3498DB", opacity=0.6),
            ),
            secondary_y=True,
        )

    fig.update_layout(
        title=f"🔗 降水-负荷叠加 {location_label}",
        xaxis_title="时间",
        hovermode="x unified",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_yaxes(title_text="负荷 (MW)", secondary_y=False)
    fig.update_yaxes(title_text="降水量 (mm) ↓", secondary_y=True)

    return fig


def plot_temp_load_scatter(
    weather_df: pd.DataFrame,
    load_df: pd.DataFrame,
    location_label: str = "",
) -> go.Figure:
    """
    温度-负荷散点图：X=温度，Y=负荷，按月份着色，可选线性回归线。
    """
    merged = _align_weather_load(weather_df, load_df)
    if merged.empty or "temperature_2m" not in merged.columns:
        return go.Figure()

    merged["month"] = merged["datetime"].dt.month

    fig = go.Figure()

    months = sorted(merged["month"].unique())
    colors = [
        "#3498DB", "#E74C3C", "#2ECC71", "#F39C12",
        "#9B59B6", "#1ABC9C", "#E67E22", "#34495E",
        "#16A085", "#C0392B", "#2980B9", "#8E44AD",
    ]

    for i, m in enumerate(months):
        mask = merged["month"] == m
        fig.add_trace(go.Scatter(
            x=merged.loc[mask, "temperature_2m"],
            y=merged.loc[mask, "load_mw"],
            mode="markers",
            name=f"{m}月",
            marker=dict(
                color=colors[i % len(colors)],
                size=6,
                opacity=0.6,
            ),
        ))

    # 线性回归趋势线
    valid = merged[["temperature_2m", "load_mw"]].dropna()
    if len(valid) > 2:
        z = np.polyfit(valid["temperature_2m"], valid["load_mw"], 1)
        p = np.poly1d(z)
        x_range = np.linspace(
            valid["temperature_2m"].min(),
            valid["temperature_2m"].max(),
            100,
        )
        fig.add_trace(go.Scatter(
            x=x_range, y=p(x_range),
            mode="lines", name="线性趋势",
            line=dict(color="#2C3E50", width=2, dash="dash"),
        ))

    fig.update_layout(
        title=f"🌡️ 温度-负荷散点 {location_label}",
        xaxis_title="温度 (°C)",
        yaxis_title="负荷 (MW)",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def plot_multi_factor(
    weather_df: pd.DataFrame,
    load_df: pd.DataFrame,
    x_param: str,
    chart_type: str = "scatter",
) -> go.Figure:
    """
    多因子对比面板：用户自选X轴参数 vs 负荷。
    """
    merged = _align_weather_load(weather_df, load_df)
    if merged.empty or x_param not in merged.columns:
        return go.Figure()

    param_cn = x_param  # 简化，直接用参数名

    fig = go.Figure()

    if chart_type == "scatter":
        fig.add_trace(go.Scatter(
            x=merged[x_param], y=merged["load_mw"],
            mode="markers",
            marker=dict(color="#3498DB", size=6, opacity=0.6),
            name=f"{param_cn} vs 负荷",
        ))
        # 趋势线
        valid = merged[[x_param, "load_mw"]].dropna()
        if len(valid) > 2:
            z = np.polyfit(valid[x_param], valid["load_mw"], 1)
            p = np.poly1d(z)
            x_range = np.linspace(valid[x_param].min(), valid[x_param].max(), 100)
            fig.add_trace(go.Scatter(
                x=x_range, y=p(x_range),
                mode="lines", name="线性趋势",
                line=dict(color="#E74C3C", width=2, dash="dash"),
            ))

    elif chart_type == "bar":
        # 按参数分箱聚合
        merged["_bin"] = pd.cut(merged[x_param], bins=20)
        agg = merged.groupby("_bin", observed=False).agg(
            avg_load=("load_mw", "mean"),
        ).reset_index()
        agg["_bin_mid"] = agg["_bin"].apply(lambda x: x.mid)
        fig.add_trace(go.Bar(
            x=agg["_bin_mid"], y=agg["avg_load"],
            name=f"各{param_cn}区间平均负荷",
            marker=dict(color="#3498DB", opacity=0.7),
        ))

    fig.update_layout(
        title=f"📊 {param_cn} vs 负荷",
        xaxis_title=param_cn,
        yaxis_title="负荷 (MW)",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig


def compute_correlations(
    weather_df: pd.DataFrame,
    load_df: pd.DataFrame,
    params: list[str] | None = None,
) -> dict[str, dict]:
    """
    计算各气象参数与负荷的 Pearson 相关系数。

    返回
    ----
    dict: {param: {"r": float, "p_value": float, "n": int}}
    """
    merged = _align_weather_load(weather_df, load_df)
    if merged.empty:
        return {}

    if params is None:
        # 默认用数值型天气参数
        exclude = {"datetime", "load_mw", "location_id", "data_type", "source",
                   "wind_direction_10m", "month", "_bin"}
        params = [c for c in merged.columns if c not in exclude and pd.api.types.is_numeric_dtype(merged[c])]

    results = {}
    for param in params:
        if param not in merged.columns:
            continue
        valid = merged[[param, "load_mw"]].dropna()
        if len(valid) < 3:
            continue
        try:
            r, p = pearsonr(valid[param], valid["load_mw"])
            results[param] = {"r": round(r, 4), "p_value": round(p, 4), "n": len(valid)}
        except Exception:
            results[param] = {"r": float("nan"), "p_value": float("nan"), "n": 0}

    return results


def render_correlation_cards(correlations: dict[str, dict], param_labels: dict | None = None):
    """
    渲染相关性统计卡片（Streamlit columns）。
    """
    import streamlit as st

    if not correlations:
        st.info("无法计算相关性：数据不足")
        return

    # 按 |r| 降序排列
    sorted_params = sorted(
        correlations.items(),
        key=lambda x: abs(x[1]["r"]) if not np.isnan(x[1]["r"]) else 0,
        reverse=True,
    )

    cols = st.columns(min(4, len(sorted_params)))
    for i, (param, stats) in enumerate(sorted_params[:8]):
        col_idx = i % 4
        label = (param_labels or {}).get(param, param.replace("_", " ").title()) if param_labels else param
        r_val = stats["r"]
        if not np.isnan(r_val):
            color = "🟢" if abs(r_val) > 0.6 else ("🟡" if abs(r_val) > 0.3 else "🔴")
            with cols[col_idx]:
                st.metric(
                    label=f"{label}-负荷 r",
                    value=f"{r_val:.3f}",
                )


def _align_weather_load(weather_df: pd.DataFrame, load_df: pd.DataFrame) -> pd.DataFrame:
    """
    将天气数据与负荷数据按 datetime 对齐（取整点）。
    """
    if weather_df.empty or load_df.empty:
        return pd.DataFrame()

    w = weather_df.copy()
    l = load_df.copy()

    if "datetime" not in w.columns or "datetime" not in l.columns:
        return pd.DataFrame()

    w["_dt_hour"] = w["datetime"].dt.floor("h")
    l["_dt_hour"] = l["datetime"].dt.floor("h")

    merged = pd.merge(w, l[["_dt_hour", "load_mw"]], on="_dt_hour", how="inner")
    merged["datetime"] = merged["_dt_hour"]
    merged.drop(columns=["_dt_hour"], inplace=True)

    return merged
