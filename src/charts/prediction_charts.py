"""
预测结果可视化图表
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def plot_daily_forecast(
    historical_daily: pd.Series,
    forecast: pd.Series,
    lower: pd.Series,
    upper: pd.Series,
    company: str = "",
) -> go.Figure:
    """日总量预测图：历史 + 预测 + 80% 置信区间。"""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=historical_daily.index, y=historical_daily.values,
        mode="lines", name="历史日总量",
        line=dict(color="#2563eb", width=1.5),
    ))

    fig.add_trace(go.Scatter(
        x=forecast.index, y=forecast.values,
        mode="lines", name="预测日总量",
        line=dict(color="#dc2626", width=2),
    ))

    fig.add_trace(go.Scatter(
        x=forecast.index.tolist() + forecast.index.tolist()[::-1],
        y=upper.values.tolist() + lower.values.tolist()[::-1],
        fill="toself", fillcolor="rgba(220,38,38,0.15)",
        line=dict(color="rgba(220,38,38,0)"),
        name="80% 置信区间",
    ))

    fig.add_vline(
        x=forecast.index[0], line_dash="dash", line_color="gray",
        opacity=0.5, annotation_text="预测起点",
    )

    fig.update_layout(
        title=f"{company} 日总量预测" if company else "日总量预测",
        xaxis_title="日期",
        yaxis_title="日总用电量 (MWh)",
        hovermode="x unified",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def plot_hourly_profile(
    hourly_results: list[dict],
    selected_dates: list = None,
    company: str = "",
) -> go.Figure:
    """
    逐时负荷曲线：多日叠加。

    hourly_results: generate_hourly_forecast 的输出
    """
    df = pd.DataFrame(hourly_results)
    if df.empty:
        return go.Figure()

    if selected_dates:
        df = df[df["date"].isin(selected_dates)]

    if "date" in df.columns:
        df["date_str"] = pd.to_datetime(df["date"]).dt.strftime("%m-%d")

    dates = sorted(df["date_str"].unique())
    colors = ["#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed",
              "#0891b2", "#be123c", "#4f46e5"]

    fig = go.Figure()
    for i, d in enumerate(dates[:8]):
        day_df = df[df["date_str"] == d].sort_values("hour")
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=day_df["hour"], y=day_df["load_mw"],
            mode="lines+markers", name=d,
            line=dict(color=color, width=2),
            marker=dict(size=4),
        ))

    fig.update_layout(
        title=f"{company} 逐时负荷预测" if company else "逐时负荷预测",
        xaxis_title="小时",
        yaxis_title="负荷 (MW)",
        hovermode="x unified",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(tickvals=list(range(0, 24, 2)))
    return fig


def plot_weekday_vs_rest(
    hourly_results: list[dict],
    calendar_df: pd.DataFrame = None,
    company: str = "",
) -> go.Figure:
    """工作日 vs 休息日 平均逐时负荷对比。"""
    df = pd.DataFrame(hourly_results)
    if df.empty:
        return go.Figure()

    df["date_dt"] = pd.to_datetime(df["date"])
    df["dow"] = df["date_dt"].dt.dayofweek

    cal_map = {}
    if calendar_df is not None and not calendar_df.empty:
        for _, row in calendar_df.iterrows():
            d = pd.Timestamp(row["date"])
            cal_map[d.date()] = row.get("day_type", "production")

    def get_day_type(dt):
        key = dt.date()
        if key in cal_map:
            return cal_map[key]
        return "rest" if dt.dayofweek >= 5 else "production"

    df["day_type"] = df["date_dt"].apply(get_day_type)

    prod_avg = df[df["day_type"] == "production"].groupby("hour")["load_mw"].mean()
    rest_avg = df[df["day_type"] == "rest"].groupby("hour")["load_mw"].mean()

    fig = go.Figure()

    if not prod_avg.empty:
        fig.add_trace(go.Scatter(
            x=prod_avg.index, y=prod_avg.values,
            mode="lines+markers", name="生产日平均",
            line=dict(color="#2563eb", width=2),
        ))

    if not rest_avg.empty:
        fig.add_trace(go.Scatter(
            x=rest_avg.index, y=rest_avg.values,
            mode="lines+markers", name="休息日平均",
            line=dict(color="#d97706", width=2, dash="dash"),
        ))

    fig.update_layout(
        title=f"{company} 生产日 vs 休息日 负荷曲线" if company else "生产日 vs 休息日",
        xaxis_title="小时",
        yaxis_title="负荷 (MW)",
        hovermode="x unified",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    fig.update_xaxes(tickvals=list(range(0, 24, 2)))
    return fig


def plot_template_matches(
    hourly_results: list[dict],
    df_hourly: pd.DataFrame = None,
    company: str = "",
) -> go.Figure:
    """展示一条预测曲线与其匹配的历史模板曲线。"""
    df_pred = pd.DataFrame(hourly_results)
    if df_pred.empty:
        return go.Figure()

    sample_date = df_pred["date"].iloc[0]
    sample = df_pred[df_pred["date"] == sample_date].sort_values("hour")

    matched_dates_str = sample["matched_dates"].iloc[0] if "matched_dates" in sample.columns else []
    matched_dates = pd.to_datetime(matched_dates_str)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=sample["hour"], y=sample["load_mw"],
        mode="lines+markers", name=f"预测 {pd.Timestamp(sample_date).strftime('%m-%d')}",
        line=dict(color="#dc2626", width=2.5),
        marker=dict(size=5),
    ))

    if df_hourly is not None and not df_hourly.empty:
        colors = ["#94a3b8", "#cbd5e1", "#e2e8f0"]
        for i, md in enumerate(matched_dates[:3]):
            md_date = md.date() if hasattr(md, "date") else md
            hist_day = df_hourly[df_hourly["date"] == md_date]
            if hist_day.empty:
                hist_day = df_hourly[
                    pd.to_datetime(df_hourly["datetime"]).dt.date == md_date
                ]
            if not hist_day.empty:
                hist_hourly = hist_day.groupby("hour")["load_mw"].mean()
                fig.add_trace(go.Scatter(
                    x=hist_hourly.index, y=hist_hourly.values,
                    mode="lines", name=f"历史 {pd.Timestamp(md_date).strftime('%m-%d')}",
                    line=dict(color=colors[i % 3], width=1.5, dash="dot"),
                    opacity=0.7,
                ))

    fig.update_layout(
        title=f"{company} 预测 vs 匹配历史模板" if company else "预测 vs 匹配历史模板",
        xaxis_title="小时",
        yaxis_title="负荷 (MW)",
        hovermode="x unified",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(tickvals=list(range(0, 24, 2)))
    return fig
