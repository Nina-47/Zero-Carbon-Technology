"""
相似日分析可视化：叠加对比图、信息卡片、相似度分解图
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# 配色方案
COLORS = {
    "target": "#E74C3C",     # 目标日 = 红色
    "similar_1": "#3498DB",  # 相似日 #1 = 蓝色
    "similar_2": "#2ECC71",  # 相似日 #2 = 绿色
    "similar_3": "#9B59B6",  # 相似日 #3 = 紫色
}
RANK_LABELS = {0: "🥇 最相似", 1: "🥈 第二相似", 2: "🥉 第三相似"}
COLOR_KEYS = ["similar_1", "similar_2", "similar_3"]


# ============================================================
# 目标日天气概览卡片
# ============================================================

def render_target_weather_card(target_summary: dict, target_date_str: str):
    """
    渲染目标日天气概览卡片。

    参数
    ----
    target_summary : dict
        {tmax, tmin, precip_sum, precip_level, rad_daily_sum, dew_point_avg}
    target_date_str : str
        目标日期字符串。
    """
    st.subheader(f"🎯 目标日天气概览 — {target_date_str}")

    precip_labels = ["无降水", "小雨", "中雨", "大雨", "暴雨", "大暴雨及以上"]
    plvl = int(target_summary.get("precip_level", 0))
    precip_label = precip_labels[min(plvl, len(precip_labels) - 1)]

    cols = st.columns(6)
    metrics = [
        ("🌡️ 最高温", f"{_fmt(target_summary.get('tmax'))} °C"),
        ("🌡️ 最低温", f"{_fmt(target_summary.get('tmin'))} °C"),
        ("🌧️ 降水量", f"{_fmt(target_summary.get('precip_sum'))} mm"),
        ("☀️ 总辐射", f"{_fmt(target_summary.get('rad_daily_sum'))} MJ/m²"),
        ("💧 露点温度", f"{_fmt(target_summary.get('dew_point_avg'))} °C"),
        ("📊 降水等级", precip_label),
    ]
    for i, (label, value) in enumerate(metrics):
        with cols[i]:
            st.metric(label=label, value=value)


# ============================================================
# 相似日信息卡片（3列）
# ============================================================

def render_similar_day_cards(similar_days: list[dict]):
    """
    渲染 3 列相似日信息卡片。

    参数
    ----
    similar_days : list[dict]
        find_similar_days() 返回的 Top-N 结果。
    """
    if not similar_days:
        st.info("未找到相似日")
        return

    st.subheader("📋 相似日匹配结果")

    cols = st.columns(len(similar_days))
    precip_labels = ["无降水", "小雨", "中雨", "大雨", "暴雨", "大暴雨及以上"]

    for i, day in enumerate(similar_days):
        color_key = COLOR_KEYS[i] if i < len(COLOR_KEYS) else "similar_1"
        color = COLORS[color_key]
        date_str = day["date"].strftime("%Y-%m-%d") if hasattr(day["date"], "strftime") else str(day["date"])
        plvl = int(day.get("precip_level", 0))

        with cols[i]:
            # 排名徽章 + 相似度
            st.markdown(
                f"<h3 style='color:{color};margin-bottom:0;'>"
                f"{RANK_LABELS.get(i, f'#{i+1}')}</h3>",
                unsafe_allow_html=True,
            )
            st.metric(
                label="相似度",
                value=f"{day.get('similarity_pct', 0):.1f}%",
            )
            st.caption(f"📅 {date_str} | {day.get('weekday_label', '')} | {day.get('season_label', '')}")

            # 关键天气对比
            st.markdown("---")
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("最高温", f"{_fmt(day.get('tmax'))} °C")
                st.metric("最低温", f"{_fmt(day.get('tmin'))} °C")
                st.metric("降水", f"{_fmt(day.get('precip_sum'))} mm")
            with col_b:
                st.metric("总辐射", f"{_fmt(day.get('rad_daily_sum'))} MJ/m²")
                st.metric("露点", f"{_fmt(day.get('dew_point_avg'))} °C")
                st.metric("降水等级", precip_labels[min(plvl, len(precip_labels) - 1)])

            # 距离得分
            st.caption(f"距离得分: {day.get('similarity_score', 0):.4f}")


# ============================================================
# 叠加对比图（核心图表）
# ============================================================

def plot_similar_day_overlay(
    target_date_str: str,
    similar_days: list[dict],
    load_data_map: dict[str, pd.DataFrame],
    target_weather: pd.DataFrame | None = None,
    location_label: str = "",
) -> go.Figure:
    """
    相似日负荷-温度叠加对比图。

    左Y轴：3 个相似日的历史实际负荷曲线 (MW)
    右Y轴：目标日预报温度 (°C)

    参数
    ----
    target_date_str : str
        目标日期字符串。
    similar_days : list[dict]
        find_similar_days() 的返回结果。
    load_data_map : dict
        {date_str: pd.DataFrame} 负荷曲线数据映射。
    target_weather : pd.DataFrame | None
        目标日逐小时预报天气（用于右Y轴温度）。
    location_label : str
        地点标签。

    返回
    ----
    plotly.graph_objects.Figure
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    has_data = False

    # --- 左侧：3 个相似日负荷曲线 ---
    for i, day in enumerate(similar_days):
        color_key = COLOR_KEYS[i] if i < len(COLOR_KEYS) else "similar_1"
        color = COLORS[color_key]
        date_str = day["date"].strftime("%Y-%m-%d") if hasattr(day["date"], "strftime") else str(day["date"])

        load_df = load_data_map.get(date_str)
        if load_df is None or load_df.empty:
            continue

        has_data = True
        pct = day.get("similarity_pct", 0)
        label = f"{RANK_LABELS.get(i, f'#{i+1}')} ({date_str}, 相似度 {pct:.1f}%)"

        # 构建 X 轴（小时）
        hours = [f"{h:02d}:00" for h in range(24)]
        # 取前 24 行
        load_vals = load_df["load_mw"].values[:24] if "load_mw" in load_df.columns else []

        fig.add_trace(
            go.Scatter(
                x=hours[:len(load_vals)],
                y=load_vals,
                mode="lines+markers",
                name=label,
                line=dict(color=color, width=2.5),
                marker=dict(size=4),
            ),
            secondary_y=False,
        )

    # --- 右侧：目标日预报温度 ---
    if target_weather is not None and not target_weather.empty:
        tw = target_weather.copy()
        if "datetime" in tw.columns:
            tw["hour"] = tw["datetime"].dt.hour
            tw = tw.sort_values("hour")

        if "temperature_2m" in tw.columns:
            temp_vals = tw["temperature_2m"].values[:24]
            hours_temp = [f"{h:02d}:00" for h in tw["hour"].values[:24]] if "hour" in tw.columns else [f"{h:02d}:00" for h in range(24)]

            fig.add_trace(
                go.Scatter(
                    x=hours_temp[:len(temp_vals)],
                    y=temp_vals,
                    mode="lines",
                    name=f"目标日 {target_date_str} 预报温度 (°C)",
                    line=dict(color=COLORS["target"], width=2, dash="dot"),
                ),
                secondary_y=True,
            )

    if not has_data:
        fig.add_trace(
            go.Scatter(x=[], y=[], name="暂无负荷数据"),
            secondary_y=False,
        )

    fig.update_layout(
        title=f"🔮 相似日负荷曲线对比 {location_label}（目标日: {target_date_str}）",
        xaxis_title="小时",
        hovermode="x unified",
        height=500,
        margin=dict(l=20, r=20, t=60, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=10)),
    )
    fig.update_yaxes(title_text="负荷 (MW)", secondary_y=False)
    fig.update_yaxes(title_text="温度 (°C)", secondary_y=True)

    return fig


# ============================================================
# 相似度分解图
# ============================================================

def plot_similarity_breakdown(similar_days: list[dict]) -> go.Figure:
    """
    相似度分解横向堆叠条形图，展示每个因子的加权距离分量。

    参数
    ----
    similar_days : list[dict]
        find_similar_days() 的返回结果。

    返回
    ----
    plotly.graph_objects.Figure
    """
    if not similar_days:
        fig = go.Figure()
        fig.update_layout(title="暂无相似度分解数据")
        return fig

    # 构建数据
    categories = list(similar_days[0].get("distance_components", {}).keys())
    if not categories:
        fig = go.Figure()
        fig.update_layout(title="暂无分解数据")
        return fig

    fig = go.Figure()

    for i, day in enumerate(similar_days):
        color_key = COLOR_KEYS[i] if i < len(COLOR_KEYS) else "similar_1"
        color = COLORS[color_key]
        date_str = day["date"].strftime("%Y-%m-%d") if hasattr(day["date"], "strftime") else str(day["date"])
        components = day.get("distance_components", {})

        values = [components.get(c, 0) for c in categories]

        fig.add_trace(go.Bar(
            y=categories,
            x=values,
            name=f"{date_str} (相似度 {day.get('similarity_pct', 0):.1f}%)",
            orientation="h",
            marker=dict(color=color, opacity=0.75),
            text=[f"{v:.3f}" for v in values],
            textposition="outside",
        ))

    fig.update_layout(
        title="📊 相似度因子分解（加权距离分量，越小越相似）",
        xaxis_title="加权距离分量",
        yaxis_title="",
        barmode="group",
        height=400,
        margin=dict(l=20, r=80, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, font=dict(size=10)),
    )

    return fig


# ============================================================
# 辅助
# ============================================================

def _fmt(val):
    """安全格式化数值为 1 位小数。"""
    if val is None:
        return "-"
    try:
        if np.isnan(float(val)):
            return "-"
        return f"{float(val):.1f}"
    except (ValueError, TypeError):
        return str(val)
