"""
天气负荷分析平台 — Streamlit 主入口
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="天气负荷分析平台",
    page_icon="🌤️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 导入项目模块
# ============================================================
from config import (
    LOCATIONS,
    VIS_PARAMS,
    EXPORT_PARAMS,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_FORECAST_DAYS,
    CACHE_TTL_SECONDS,
    MAX_HISTORY_DAYS,
    convert_units,
)
from src.api.fallback import (
    fetch_forecast_safe,
    fetch_historical_safe,
    DataSourceStatus,
)
from src.aggregation.province_avg import fetch_guangdong_average
from src.db.models import (
    init_db,
    insert_weather_data,
    query_weather_data,
    get_setting,
    save_setting,
    clean_old_forecasts,
)
from src.charts.cards import render_overview_cards
from src.charts.weather_charts import (
    plot_temperature,
    plot_precipitation,
    plot_wind,
    plot_sunshine,
)
from src.charts.load_overlay import (
    plot_precip_load_overlay,
    plot_temp_load_scatter,
    plot_multi_factor,
    compute_correlations,
    render_correlation_cards,
)
from src.export.csv_writer import export_csv
from src.export.json_writer import export_json
from src.utils.csv_parser import parse_load_csv, list_load_columns
from src.utils.time_utils import date_range_dates

# ============================================================
# 初始化
# ============================================================
init_db()

# Session State 初始化
if "load_df" not in st.session_state:
    st.session_state.load_df = None
if "load_filename" not in st.session_state:
    st.session_state.load_filename = ""
if "load_error" not in st.session_state:
    st.session_state.load_error = ""
if "data_status" not in st.session_state:
    st.session_state.data_status = DataSourceStatus()
if "weather_loaded" not in st.session_state:
    st.session_state.weather_loaded = False

# ============================================================
# 数据获取（带缓存）
# ============================================================
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="正在获取天气数据...")
def fetch_all_weather_data(
    location_key: str,
    history_days: int,
    forecast_days: int,
) -> dict:
    """
    获取指定地点的历史+预报数据，写入 SQLite 后返回。

    返回
    ----
    dict: {"historical": DataFrame, "forecast": DataFrame, "status": DataSourceStatus}
    """
    status = DataSourceStatus()
    loc = LOCATIONS[location_key]

    result = {"historical": pd.DataFrame(), "forecast": pd.DataFrame(), "status": status}

    forecast_end = (datetime.now() + timedelta(days=forecast_days)).strftime("%Y-%m-%d")
    forecast_start = datetime.now().strftime("%Y-%m-%d")

    if loc.get("is_aggregate"):
        # 广东省平均
        result["historical"] = fetch_guangdong_average("historical", status, history_days, forecast_days)
        result["forecast"] = fetch_guangdong_average("forecast", status, history_days, forecast_days)
    else:
        # 单点城市
        hist_start, hist_end = date_range_dates(history_days, 0)
        result["historical"] = fetch_historical_safe(
            loc["latitude"], loc["longitude"], location_key, hist_start, hist_end, status,
        )
        result["forecast"] = fetch_forecast_safe(
            loc["latitude"], loc["longitude"], location_key, forecast_days, status,
        )

    # 广东省平均已在 fetch_guangdong_average 内部逐城 convert_units
    # 单点城市需要在此处调用 convert_units
    if not loc.get("is_aggregate"):
        if not result["historical"].empty:
            result["historical"] = convert_units(result["historical"])
        if not result["forecast"].empty:
            result["forecast"] = convert_units(result["forecast"])

    # 写入数据库
    if not result["historical"].empty:
        insert_weather_data(result["historical"])
    if not result["forecast"].empty:
        insert_weather_data(result["forecast"])

    return result


def load_cached_or_fetch(location_key: str, history_days: int, forecast_days: int) -> dict:
    """优先从 SQLite 读取，缓存过期则拉取 API。"""
    return fetch_all_weather_data(location_key, history_days, forecast_days)


# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.header("🌤️ 控制面板")

    # 地点选择
    st.subheader("📍 地点")
    selected_locations = st.multiselect(
        "选择地点（可多选）",
        options=list(LOCATIONS.keys()),
        default=["zhongshan"],
        format_func=lambda x: LOCATIONS[x]["display_name"],
        label_visibility="collapsed",
    )
    if not selected_locations:
        selected_locations = ["zhongshan"]

    # 时间范围
    st.subheader("📅 时间范围")
    history_days = st.slider(
        "历史回溯",
        min_value=1,
        max_value=MAX_HISTORY_DAYS,
        value=int(get_setting("default_history_days", str(DEFAULT_HISTORY_DAYS))),
        step=1,
        format="%d 天",
    )
    forecast_days = st.slider(
        "预报天数",
        min_value=1,
        max_value=7,
        value=DEFAULT_FORECAST_DAYS,
        step=1,
        format="%d 天",
    )

    # 可视化参数
    st.subheader("🌡️ 展示参数")
    vis_selection = {}
    for param, info in VIS_PARAMS.items():
        default_checked = param in [
            "temperature_2m", "apparent_temp_cn",
            "precipitation", "wind_speed_10m", "sunshine_duration",
        ]
        vis_selection[param] = st.checkbox(
            info["cn"],
            value=default_checked,
            key=f"vis_{param}",
        )

    st.divider()

    # 导出
    st.subheader("📥 导出")
    export_format = st.radio(
        "导出格式",
        options=["CSV", "JSON"],
        horizontal=True,
        label_visibility="collapsed",
    )
    export_all_cols = st.checkbox("导出全部参数（含模型用）", value=True)

    st.divider()

    # 设置
    st.subheader("⚙️ 设置")
    auto_refresh = st.checkbox(
        "自动刷新",
        value=get_setting("auto_refresh", "true") == "true",
    )

    # 数据源状态
    status = st.session_state.data_status
    st.info(f"{status.status_icon} 数据源: {status.status_text}")

    if st.button("🔄 强制刷新", use_container_width=True):
        st.cache_data.clear()
        st.session_state.weather_loaded = False
        st.rerun()

# ============================================================
# 页面标题
# ============================================================
st.title("🌤️ 天气负荷分析平台")

# 错误/警告横幅
status = st.session_state.data_status
if not status.primary_ok and not status.fallback_used:
    st.error(f"🔴 数据更新失败：{status.error_message}。显示最近可用缓存数据。")
elif not status.primary_ok and status.fallback_used:
    st.warning("🟡 主数据源响应慢，已切换至备用数据源（和风天气）。")

# ============================================================
# 加载数据
# ============================================================
all_weather = {}
for loc_key in selected_locations:
    all_weather[loc_key] = load_cached_or_fetch(loc_key, history_days, forecast_days)
    st.session_state.data_status = all_weather[loc_key]["status"]

st.session_state.weather_loaded = True

# 合并历史和预报
for loc_key in selected_locations:
    data = all_weather[loc_key]
    combined = pd.concat(
        [data["historical"], data["forecast"]],
        ignore_index=True,
    ) if not data["historical"].empty or not data["forecast"].empty else pd.DataFrame()
    # 防御性去重：避免 provincial_avg 等聚合产生的重复列
    if not combined.empty:
        combined = combined.loc[:, ~combined.columns.duplicated()].sort_values("datetime")
    all_weather[loc_key]["combined"] = combined

# 当前选中的主地点
primary_loc = selected_locations[0]
primary_data = all_weather[primary_loc]["combined"]
primary_label = LOCATIONS[primary_loc]["display_name"]

# ============================================================
# Tab 页签
# ============================================================
tab1, tab2, tab3 = st.tabs(["📊 天气总览", "🔗 负荷叠加分析", "📋 数据表格与导出"])

# ============================================================
# Tab 1: 天气总览
# ============================================================
with tab1:
    if primary_data.empty:
        st.info("正在加载天气数据，请稍候...")
    else:
        # 概览卡片
        st.subheader("📌 实时概览")
        render_overview_cards(primary_data)

        st.divider()

        # 温度
        if vis_selection.get("temperature_2m", True) or vis_selection.get("apparent_temp_cn", True):
            st.plotly_chart(
                plot_temperature(primary_data, primary_label),
                use_container_width=True,
            )

        # 降水
        if vis_selection.get("precipitation", True):
            st.plotly_chart(
                plot_precipitation(primary_data, primary_label),
                use_container_width=True,
            )

        # 风况
        if vis_selection.get("wind_speed_10m", True):
            st.plotly_chart(
                plot_wind(primary_data, primary_label),
                use_container_width=True,
            )

        # 日照
        if vis_selection.get("sunshine_duration", True):
            st.plotly_chart(
                plot_sunshine(primary_data, primary_label),
                use_container_width=True,
            )

# ============================================================
# Tab 2: 负荷叠加分析
# ============================================================
with tab2:
    st.subheader("📤 负荷数据")

    upload_col, info_col = st.columns([3, 2])

    with upload_col:
        uploaded_file = st.file_uploader(
            "上传负荷 CSV 文件",
            type=["csv"],
            help="支持格式：时间戳 + 负荷值(MW)。编码：UTF-8 或 GBK。",
            key="load_uploader",
        )

    # 处理上传
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        load_df, error_msg = parse_load_csv(file_bytes, uploaded_file.name)

        if error_msg and "未检测到负荷列" not in error_msg:
            st.error(error_msg)
        elif load_df is not None and not load_df.empty:
            # 检查是否需要手动选择负荷列
            if "load_mw" not in load_df.columns or load_df["load_mw"].isna().all():
                st.warning("未自动检测到负荷列，请手动选择：")
                candidate_cols = list_load_columns(load_df)
                if candidate_cols:
                    selected_col = st.selectbox("选择负荷列", options=candidate_cols)
                    if selected_col:
                        load_df["load_mw"] = pd.to_numeric(load_df[selected_col], errors="coerce")

            st.session_state.load_df = load_df
            st.session_state.load_filename = uploaded_file.name
            st.session_state.load_error = ""
        else:
            st.session_state.load_error = error_msg or ""

    with info_col:
        if st.session_state.load_df is not None and not st.session_state.load_df.empty:
            ld = st.session_state.load_df
            st.success(f"✅ 已加载: {st.session_state.load_filename}")
            st.caption(f"时间范围: {ld['datetime'].min()} ~ {ld['datetime'].max()}")
            st.caption(f"数据点数: {len(ld)}")
            if st.button("清除数据", key="clear_load"):
                st.session_state.load_df = None
                st.session_state.load_filename = ""
                st.rerun()
        else:
            st.info("尚未上传负荷数据。\n\n支持两列格式：\n`datetime, load_mw`")

    st.divider()

    # 叠加图表
    if primary_data.empty:
        st.info("天气数据加载中...")
    elif st.session_state.load_df is not None and not st.session_state.load_df.empty:
        load_df = st.session_state.load_df

        st.subheader("🔗 降水-负荷叠加")
        st.plotly_chart(
            plot_precip_load_overlay(primary_data, load_df, primary_label),
            use_container_width=True,
        )

        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("🌡️ 温度-负荷散点")
            st.plotly_chart(
                plot_temp_load_scatter(primary_data, load_df, primary_label),
                use_container_width=True,
            )

        with col_right:
            st.subheader("📊 多因子对比")
            numeric_params = [
                p for p in EXPORT_PARAMS.keys()
                if p in primary_data.columns and p != "wind_direction_10m"
            ]
            selected_param = st.selectbox(
                "选择 X 轴参数",
                options=numeric_params,
                format_func=lambda x: EXPORT_PARAMS.get(x, {}).get("cn", x),
                key="multi_factor_param",
            )
            chart_type = st.radio(
                "图表类型",
                options=["scatter", "bar"],
                format_func=lambda x: "散点图" if x == "scatter" else "柱状图",
                horizontal=True,
                key="multi_factor_chart",
            )
            st.plotly_chart(
                plot_multi_factor(primary_data, load_df, selected_param, chart_type),
                use_container_width=True,
            )

        # 相关性统计
        st.subheader("📈 天气-负荷相关性")
        correlations = compute_correlations(
            primary_data, load_df,
            params=list(EXPORT_PARAMS.keys()),
        )
        param_labels = {k: v["cn"] for k, v in EXPORT_PARAMS.items()}
        render_correlation_cards(correlations, param_labels)
    else:
        st.info("👆 请先上传负荷 CSV 文件以进行叠加分析")

# ============================================================
# Tab 3: 数据表格与导出
# ============================================================
with tab3:
    if primary_data.empty:
        st.info("数据加载中...")
    else:
        st.subheader("📋 数据表格")

        # 列选择
        available_cols = [c for c in EXPORT_PARAMS.keys() if c in primary_data.columns]
        selected_table_cols = st.multiselect(
            "选择显示列",
            options=available_cols,
            default=["temperature_2m", "precipitation", "wind_speed_10m", "sunshine_duration"][:4],
            format_func=lambda x: EXPORT_PARAMS.get(x, {}).get("cn", x),
        )

        # 表格
        display_cols = ["datetime", "location_id"] + selected_table_cols
        display_cols = [c for c in display_cols if c in primary_data.columns]
        table_df = primary_data[display_cols].copy()

        if "datetime" in table_df.columns:
            table_df["datetime"] = table_df["datetime"].dt.strftime("%Y-%m-%d %H:%M")

        st.dataframe(
            table_df,
            use_container_width=True,
            height=400,
            hide_index=True,
        )
        st.caption(f"共 {len(table_df)} 条记录")

        st.divider()
        st.subheader("📥 数据导出")

        export_col1, export_col2 = st.columns(2)

        with export_col1:
            # 导出列选择
            export_columns = st.multiselect(
                "导出参数（留空=全部）",
                options=available_cols,
                default=[],
                format_func=lambda x: f"{EXPORT_PARAMS.get(x, {}).get('cn', x)} ({EXPORT_PARAMS.get(x, {}).get('unit', '')})",
                key="export_cols",
            )
            export_locs = st.multiselect(
                "导出地点",
                options=selected_locations,
                default=selected_locations,
                format_func=lambda x: LOCATIONS[x]["display_name"],
            )

        with export_col2:
            export_time_range = st.radio(
                "时间范围",
                options=["全部数据", "仅历史", "仅预报"],
                horizontal=False,
            )

        # 筛选导出数据
        export_df = primary_data.copy()
        if export_time_range == "仅历史":
            export_df = all_weather[primary_loc]["historical"]
        elif export_time_range == "仅预报":
            export_df = all_weather[primary_loc]["forecast"]

        selected_export_cols = export_columns if export_columns else None

        if st.button("⬇️ 下载数据", type="primary", use_container_width=True):
            if export_format == "CSV":
                csv_bytes = export_csv(
                    export_df,
                    selected_columns=selected_export_cols,
                    include_location=True,
                )
                st.download_button(
                    label="📥 下载 CSV",
                    data=csv_bytes,
                    file_name=f"weather_{primary_loc}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                json_str = export_json(
                    export_df,
                    location_id=primary_loc,
                    selected_columns=selected_export_cols,
                )
                st.download_button(
                    label="📥 下载 JSON",
                    data=json_str,
                    file_name=f"weather_{primary_loc}_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                    mime="application/json",
                    use_container_width=True,
                )

# ============================================================
# 自动刷新逻辑
# ============================================================
if auto_refresh:
    # Streamlit 自动刷新：利用 st.rerun() + time.sleep
    # 注意：这会在每次 rerun 时触发，我们用 session_state 控制
    import time

    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = datetime.now()

    elapsed = (datetime.now() - st.session_state.last_refresh).total_seconds()
    if elapsed > CACHE_TTL_SECONDS:
        st.session_state.last_refresh = datetime.now()
        st.cache_data.clear()
        # 不自动 rerun 以避免无限循环；依赖用户交互或外部 ping 触发
        # 自动刷新由外部 uptime 服务每 30 分钟 ping 实现

# 清理过期预报（每次加载时静默执行）
try:
    clean_old_forecasts(7)
except Exception:
    pass

# 保存设置
if auto_refresh != (get_setting("auto_refresh", "true") == "true"):
    save_setting("auto_refresh", "true" if auto_refresh else "false")
save_setting("default_history_days", str(history_days))
