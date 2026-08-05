"""
天气负荷分析平台 — Streamlit 主入口
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from io import BytesIO

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
    PREDICTION_COMPANIES,
    DEFAULT_FORECAST_DAYS_LIMIT,
    DEFAULT_KNN_K,
    DEFAULT_PRODUCTION_DAYS,
    DAY_TYPE_MAP,
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
    plot_shortwave_radiation,
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
from src.utils.csv_parser import parse_load_csv, list_load_columns, parse_load_history_upload
from src.utils.time_utils import date_range_dates
from src.similarity.similar_day import find_similar_days, compute_daily_weather
from src.charts.similar_day import (
    plot_similar_day_overlay,
    render_similar_day_cards,
    render_target_weather_card,
    plot_similarity_breakdown,
)
from src.db.models import (
    init_db,
    insert_weather_data,
    query_weather_data,
    get_setting,
    save_setting,
    clean_old_forecasts,
    init_load_table,
    import_load_from_df,
    get_load_by_date,
    query_load_date_range,
    has_load_data,
    delete_load_data,
    query_load_all,
    get_load_companies,
    init_calendar_table,
    import_calendar_from_df,
    get_calendar,
    delete_calendar,
)
from src.prediction.load_forecast import (
    prepare_load_data,
    prepare_daily_series,
    run_forecast,
)
from src.prediction.calendar import generate_calendar_from_rule, parse_calendar_upload
from src.prediction.weather_forecast import parse_weather_forecast_upload
from src.charts.prediction_charts import (
    plot_daily_forecast,
    plot_hourly_profile,
    plot_weekday_vs_rest,
    plot_template_matches,
)
from src.db.models import (
    init_load_table,
    import_load_from_df,
    get_load_by_date,
    query_load_date_range,
    has_load_data,
    delete_load_data,
)

# ============================================================
# 初始化
# ============================================================
init_db()

# 数据库列兼容检测：shortwave_radiation
import sqlite3, os
_db_path = os.path.join(os.path.dirname(__file__), "data", "weather.db")
if os.path.exists(_db_path):
    try:
        _conn = sqlite3.connect(_db_path)
        _cols = [r[1] for r in _conn.execute("PRAGMA table_info(weather_hourly)").fetchall()]
        _conn.close()
        if "shortwave_radiation" not in _cols:
            st.warning(
                "⚠️ 数据库缺少 `shortwave_radiation` 列。"
                "请删除 `data/weather.db` 后刷新页面以重新拉取天气数据。"
            )
    except Exception:
        pass  # 表不存在等异常静默忽略

# 天气数据种子检查：如果数据库天数 < 100，自动从预置 Excel 导入
import hashlib
def _seed_weather_db():
    """如果 weather_hourly 表数据不足 100 天，从全要素天气表导入。"""
    try:
        _conn = sqlite3.connect(_db_path)
        _days = _conn.execute("SELECT COUNT(DISTINCT date(datetime)) FROM weather_hourly").fetchone()[0]
        _conn.close()
        if _days >= 100:
            return  # 数据充足，无需导入
    except Exception:
        _days = 0

    # 尝试导入
    seed_path = os.path.join(os.path.dirname(__file__), "data", "weather_seed.xlsx")
    if not os.path.exists(seed_path):
        return

    try:
        element_map = {
            "气温(℃)": "temperature_2m",
            "降水量(mm)": "precipitation",
            "风速(km/h)": "wind_speed_10m",
            "风向(°)": "wind_direction_10m",
            "云量(%)": "cloud_cover",
            "太阳总辐射(MJ/m²)": "shortwave_radiation",
        }
        df = pd.read_excel(seed_path, sheet_name="全要素天气表_长格式_v2")
        df.columns = ["date", "element"] + list(range(24))

        _conn = sqlite3.connect(_db_path)
        _conn.execute("DELETE FROM weather_hourly")

        # 用 melt 向量化替代 iterrows 逐行聚合
        df["element_en"] = df["element"].map(element_map)
        df = df.dropna(subset=["element_en"])
        df["date"] = df["date"].astype(str).str[:10]

        id_vars = ["date", "element_en"]
        value_vars = list(range(24))
        melted = df.melt(id_vars=id_vars, value_vars=value_vars, var_name="hour", value_name="value")
        melted = melted.dropna(subset=["value"])
        melted["datetime"] = melted["date"] + "T" + melted["hour"].astype(str).str.zfill(2) + ":00:00"

        pivoted = melted.pivot_table(
            index=["date", "hour", "datetime"],
            columns="element_en",
            values="value",
            aggfunc="first",
        ).reset_index()

        now = pd.Timestamp.now().isoformat()
        cols = ["location_id", "datetime", "data_type", "source",
                "temperature_2m", "precipitation", "wind_speed_10m",
                "wind_direction_10m", "cloud_cover", "shortwave_radiation", "fetched_at"]
        phs = ",".join(["?"] * len(cols))
        sql = f"INSERT OR REPLACE INTO weather_hourly ({','.join(cols)}) VALUES ({phs})"

        rows = []
        for _, r in pivoted.iterrows():
            rows.append((
                "zhongshan", r["datetime"], "historical", "seed",
                r.get("temperature_2m"),
                r.get("precipitation"),
                r.get("wind_speed_10m"),
                r.get("wind_direction_10m"),
                r.get("cloud_cover"),
                r.get("shortwave_radiation"),
                now,
            ))

        _conn.executemany(sql, rows)
        _conn.commit()
        _conn.close()
    except Exception:
        pass

_seed_weather_db()


def _build_hourly_export(company: str) -> BytesIO:
    """导出指定公司的全部历史逐时负荷为 Excel。"""
    from io import BytesIO
    df = query_load_all(company)
    if df.empty:
        df = pd.DataFrame({"提示": ["暂无数据"]})
    else:
        df = df.rename(columns={
            "datetime": "时间", "load_mw": "负荷_MW",
            "weekday": "星期", "daily_total": "日总_MWh",
        })
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="逐时负荷", index=False)
    output.seek(0)
    return output


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
if "similar_days" not in st.session_state:
    st.session_state.similar_days = []
if "target_date_str" not in st.session_state:
    st.session_state.target_date_str = ""
if "similar_search_done" not in st.session_state:
    st.session_state.similar_search_done = False
if "target_summary" not in st.session_state:
    st.session_state.target_summary = {}
if "target_weather" not in st.session_state:
    st.session_state.target_weather = None
if "prediction_result" not in st.session_state:
    st.session_state.prediction_result = None
if "prediction_company" not in st.session_state:
    st.session_state.prediction_company = ""
if "calendar_df" not in st.session_state:
    st.session_state.calendar_df = None
if "weather_forecast_df" not in st.session_state:
    st.session_state.weather_forecast_df = None

# ============================================================
# 数据获取（SQLite 优先，缺失时拉取 API + Streamlit 内存缓存）
# ============================================================
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_cached_or_fetch(location_key: str, history_days: int, forecast_days: int) -> dict:
    """优先从 SQLite 读取缓存，缺失时才拉取 API。"""
    loc = LOCATIONS[location_key]
    status = DataSourceStatus()

    now = datetime.now()
    hist_start = (now - timedelta(days=history_days)).strftime("%Y-%m-%d")
    hist_end = now.strftime("%Y-%m-%d")
    forecast_end = (now + timedelta(days=forecast_days)).strftime("%Y-%m-%d")
    forecast_start = now.strftime("%Y-%m-%d")

    if loc.get("is_aggregate"):
        from src.aggregation.province_avg import fetch_guangdong_average
        historical = fetch_guangdong_average("historical", status, history_days, forecast_days)
        forecast = fetch_guangdong_average("forecast", status, history_days, forecast_days)
    else:
        historical = query_weather_data([location_key], hist_start, hist_end, ["historical"])
        forecast = query_weather_data([location_key], forecast_start, forecast_end, ["forecast"])

        expected_hist_hours = history_days * 24
        expected_forecast_hours = forecast_days * 24

        if len(historical) < expected_hist_hours * 0.8:
            historical = fetch_historical_safe(
                loc["latitude"], loc["longitude"], location_key, hist_start, hist_end, status,
            )
            if not historical.empty:
                insert_weather_data(historical)

        if len(forecast) < expected_forecast_hours * 0.8:
            forecast = fetch_forecast_safe(
                loc["latitude"], loc["longitude"], location_key, forecast_days, status,
            )
            if not forecast.empty:
                insert_weather_data(forecast)

        if not historical.empty:
            historical = convert_units(historical)
        if not forecast.empty:
            forecast = convert_units(forecast)

    return {"historical": historical, "forecast": forecast, "status": status}


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
            "precipitation", "wind_speed_10m", "shortwave_radiation",
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
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 天气总览",
    "🔗 负荷叠加分析",
    "📋 数据表格与导出",
    "🔮 相似日分析",
    "🔌 负荷预测",
])

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

        # 太阳总辐射
        if vis_selection.get("shortwave_radiation", True):
            st.plotly_chart(
                plot_shortwave_radiation(primary_data, primary_label),
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
            default=["temperature_2m", "precipitation", "wind_speed_10m", "shortwave_radiation"][:4],
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
with tab4:
    st.subheader("🔮 相似日分析")

    # 负荷数据模板下载
    template_path = os.path.join(os.path.dirname(__file__), "data", "负荷数据模板.xlsx")
    with open(template_path, "rb") as tf:
        st.download_button(
            label="📥 下载负荷数据模板",
            data=tf,
            file_name="负荷数据模板.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            help="下载后按模板格式填入负荷数据，再上传到本页面",
            use_container_width=True,
        )

    load_available = has_load_data()
    load_start, load_end = query_load_date_range()

    import json as _json

    @st.cache_data(ttl=86400, show_spinner=False)
    def _load_similarity_db():
        sim_path = os.path.join(os.path.dirname(__file__), "data", "similarity_results.json")
        if not os.path.exists(sim_path):
            return {}, {}
        with open(sim_path, "r", encoding="utf-8") as f:
            raw = _json.load(f)
        return raw.get("results", {}), raw.get("features", {})

    similarity_db, similarity_features = _load_similarity_db()
    sim_dates = sorted(similarity_db.keys())
    sim_min = sim_dates[0] if sim_dates else "2025-01-01"
    sim_max = sim_dates[-1] if sim_dates else "2026-07-29"

    if not load_available:
        st.info(
            "💡 **尚未导入历史负荷数据。**\n\n"
            "请先导入历史负荷数据（支持 CSV / Excel 格式）。\n"
            "**支持格式**: Excel (.xlsx) / CSV 宽表(日期+24时) / CSV 长表(datetime+load_mw)"
        )
        uploaded_load = st.file_uploader(
            "📤 上传历史负荷文件",
            type=["csv", "xlsx", "xls"],
            key="similar_day_load_uploader",
        )
        if uploaded_load is not None:
            file_bytes = uploaded_load.getvalue()
            load_hist_df, error_msg = parse_load_history_upload(file_bytes, uploaded_load.name)
            if error_msg:
                st.error(error_msg)
            elif load_hist_df is not None and not load_hist_df.empty:
                n_imported = import_load_from_df(load_hist_df, uploaded_load.name)
                st.success(f"✅ 已导入 {n_imported} 条负荷记录")
                st.rerun()
    else:
        with st.expander(f"📂 历史负荷数据 — {load_start} ~ {load_end}", expanded=False):
            col_a, col_b = st.columns([2, 1])
            with col_a:
                st.caption(f"数据范围: **{load_start}** ~ **{load_end}**")
            with col_b:
                if st.button("🗑️ 清空", key="clear_load_history"):
                    delete_load_data()
                    st.rerun()

        st.divider()
        st.subheader("🎯 选择目标日")

        today = datetime.now().date()
        min_date = max(datetime.strptime(sim_min, "%Y-%m-%d").date(), today - timedelta(days=30))
        sim_max_date = datetime.strptime(sim_max, "%Y-%m-%d").date()
        max_date = max(sim_max_date, today + timedelta(days=7))  # 允许选未来，超出 JSON 的用实时算

        col_t1, col_t2 = st.columns([2, 1])
        with col_t1:
            target_date = st.date_input(
                "选择要分析的目标日期",
                value=min(today + timedelta(days=1), max_date),
                min_value=min_date,
                max_value=max_date,
                key="similar_day_target_date",
            )
        with col_t2:
            st.caption(f"可用范围: {sim_min} ~ {sim_max}")
            st.caption(f"共 {len(sim_dates)} 天预计算数据")
            search_btn = st.button("🔍 查找相似日", type="primary",
                                   use_container_width=True, key="similar_day_search")

        if search_btn:
            target_date_str = target_date.strftime("%Y-%m-%d")

            if target_date_str not in similarity_db:
                # 未来日期：从侧边栏预报数据提取天气，在 JSON 历史特征中找相似
                if not primary_data.empty and "datetime" in primary_data.columns:
                    target_wx = primary_data[
                        primary_data["datetime"].apply(lambda x: str(x)[:10]) == target_date_str
                    ].copy()
                else:
                    target_wx = pd.DataFrame()

                if target_wx.empty or len(target_wx) < 6:
                    target_wx = pd.DataFrame()  # 走下面的降级

                if not target_wx.empty and len(target_wx) >= 6:
                    st.info(f"目标日 {target_date_str} 超出预计算范围，使用预报天气实时匹配。")
                    # 聚合目标日天气
                    td = compute_daily_weather(target_wx)
                    if td.empty:
                        st.warning("无法计算目标日天气特征。")
                    else:
                        tr = td.iloc[0]
                        t_tmax = tr.get("tmax", 0) or 0
                        t_tmin = tr.get("tmin", 0) or 0
                        t_precip = tr.get("precip_sum", 0) or 0
                        t_rainy = t_precip >= 0.5
                        t_m = target_date.month
                        t_s = 0 if t_m in [12,1,2] else 1 if t_m in [3,4,5] else 2 if t_m in [6,7,8] else 3

                        season_names = ["冬", "春", "夏", "秋"]
                        weekday_names = ["一", "二", "三", "四", "五", "六", "日"]

                        def precip_level(p):
                            if p < 0.1: return 0
                            if p < 1: return 1
                            if p < 10: return 2
                            if p < 25: return 3
                            if p < 50: return 4
                            return 5

                        # 同季节 + 同晴雨 + 温度最接近
                        scored = []
                        for d_str in sim_dates:
                            d_dt = datetime.strptime(d_str, "%Y-%m-%d")
                            dm = d_dt.month
                            ds = 0 if dm in [12,1,2] else 1 if dm in [3,4,5] else 2 if dm in [6,7,8] else 3
                            if ds != t_s:
                                continue
                            f = similarity_features.get(d_str, {})
                            if not f:
                                continue
                            f_rainy = f.get("precip_sum", 0) >= 0.5
                            if t_rainy != f_rainy:
                                continue
                            tmax_d = abs(t_tmax - f.get("tmax", t_tmax)) ** 2
                            tmin_d = abs(t_tmin - f.get("tmin", t_tmin)) ** 2
                            score = tmax_d + tmin_d  # 温度差的平方和
                            scored.append((d_str, score, f))

                        scored.sort(key=lambda x: x[1])
                        similar_days = []
                        for rank, (d_str, score, f) in enumerate(scored[:3]):
                            dd = datetime.strptime(d_str, "%Y-%m-%d")
                            dm = dd.month
                            ds = 0 if dm in [12,1,2] else 1 if dm in [3,4,5] else 2 if dm in [6,7,8] else 3
                            dp = f.get("precip_sum", 0)
                            pl = precip_level(dp)
                            # 相似度：第一名 95%, 第二 85%, 第三 75%（简单分层）
                            sim = [95, 85, 75][rank] if rank < 3 else 70
                            similar_days.append({
                                "date": dd,
                                "similarity_score": round(score, 2),
                                "similarity_pct": sim,
                                "tmax": f.get("tmax"),
                                "tmin": f.get("tmin"),
                                "precip_sum": dp,
                                "precip_level": pl,
                                "rad_daily_sum": f.get("rad_sum"),
                                "dew_point_avg": None,
                                "season_label": season_names[ds],
                                "weekday_label": weekday_names[dd.weekday()],
                                "distance_components": {},
                            })

                        if not similar_days:
                            st.warning("未找到匹配的相似日。")
                        else:
                            st.session_state.similar_days = similar_days
                            st.session_state.target_date_str = target_date_str
                            st.session_state.similar_search_done = True
                            st.session_state.target_weather = target_wx

                else:
                    # 降级：无预报数据，同季节选日期最近的 3 天
                    st.info(f"目标日 {target_date_str} 暂无预报数据，降级为同季节最近相似日。")
                    t_m = target_date.month
                    t_s = 0 if t_m in [12,1,2] else 1 if t_m in [3,4,5] else 2 if t_m in [6,7,8] else 3
                    season_names = ["冬", "春", "夏", "秋"]
                    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
                    fallback = []
                    for d_str in sim_dates:
                        d_dt = datetime.strptime(d_str, "%Y-%m-%d")
                        dm = d_dt.month
                        ds = 0 if dm in [12,1,2] else 1 if dm in [3,4,5] else 2 if dm in [6,7,8] else 3
                        if ds != t_s:
                            continue
                        c = similarity_features.get(d_str, {})
                        delta = abs((target_date - d_dt.date()).days)
                        fallback.append((d_str, delta, c))
                    fallback.sort(key=lambda x: x[1])
                    similar_days = []
                    for d_str, delta, c in fallback[:3]:
                        dd = datetime.strptime(d_str, "%Y-%m-%d")
                        dp = c.get("precip_sum", 0)
                        pl = 0 if dp < 0.1 else 1 if dp < 1 else 2 if dp < 10 else 3 if dp < 25 else 4 if dp < 50 else 5
                        sim = max(50.0, round(100.0 - delta / 3.65, 1))
                        similar_days.append({
                            "date": dd,
                            "similarity_score": delta,
                            "similarity_pct": sim,
                            "tmax": c.get("tmax"),
                            "tmin": c.get("tmin"),
                            "precip_sum": dp,
                            "precip_level": pl,
                            "rad_daily_sum": c.get("rad_sum"),
                            "dew_point_avg": None,
                            "season_label": season_names[ds],
                            "weekday_label": weekday_names[dd.weekday()],
                            "distance_components": {},
                        })
                    if similar_days:
                        st.session_state.similar_days = similar_days
                        st.session_state.target_date_str = target_date_str
                        st.session_state.similar_search_done = True
                        st.session_state.target_weather = None
            else:
                precomputed = similarity_db[target_date_str]
                if not precomputed:
                    st.warning("未找到相似日。")
                else:
                    season_names = ["冬", "春", "夏", "秋"]
                    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]

                    similar_days = []
                    for item in precomputed[:3]:
                        d = datetime.strptime(item["date"], "%Y-%m-%d")
                        similar_days.append({
                            "date": d,
                            "similarity_score": item["distance"],
                            "similarity_pct": item["similarity_pct"],
                            "tmax": item["tmax"],
                            "tmin": item["tmin"],
                            "precip_sum": item["precip_sum"],
                            "precip_level": item.get("precip_level", 0),
                            "rad_daily_sum": item["rad_sum"],
                            "dew_point_avg": None,
                            "season_label": season_names[item["season"]],
                            "weekday_label": weekday_names[item["weekday"]],
                            "distance_components": {},
                        })

                    st.session_state.similar_days = similar_days
                    st.session_state.target_date_str = target_date_str
                    st.session_state.similar_search_done = True
                    st.session_state.target_weather = None

        if st.session_state.get("similar_search_done"):
            similar_days = st.session_state.get("similar_days", [])
            target_date_str = st.session_state.get("target_date_str", "")

            st.divider()
            st.caption(f"相似日数据已预计算（{len(sim_dates)} 天，算法 v2），查表响应 < 1 秒。")

            if similar_days:
                render_similar_day_cards(similar_days)
                st.divider()

                load_data_map = {}
                for day in similar_days:
                    ds = day["date"].strftime("%Y-%m-%d") if hasattr(day["date"], "strftime") else str(day["date"])
                    ldf = get_load_by_date(ds)
                    if not ldf.empty:
                        load_data_map[ds] = ldf

                st.subheader("📈 负荷曲线叠加对比")
                st.plotly_chart(
                    plot_similar_day_overlay(target_date_str, similar_days, load_data_map,
                                             target_weather=None, location_label=primary_label),
                    use_container_width=True,
                )

                # --- 导出 Excel ---
                st.divider()
                st.subheader("📥 导出 24h 负荷数据")

                # 构建导出数据
                export_rows = []
                # 相似日实际负荷
                for day in similar_days:
                    ds = day["date"].strftime("%Y-%m-%d") if hasattr(day["date"], "strftime") else str(day["date"])
                    ldf = load_data_map.get(ds)
                    if ldf is not None and not ldf.empty:
                        vals = ldf["load_mw"].values[:24] if "load_mw" in ldf.columns else []
                        if len(vals) == 24:
                            export_rows.append({
                                "类型": f"相似日_{ds}",
                                "相似度": f"{day.get('similarity_pct', 0):.1f}%",
                                **{f"{h:02d}h": round(vals[h], 2) for h in range(24)},
                            })

                # 预测负荷
                all_loads = []
                for day in similar_days:
                    ds = day["date"].strftime("%Y-%m-%d") if hasattr(day["date"], "strftime") else str(day["date"])
                    ldf = load_data_map.get(ds)
                    if ldf is not None and not ldf.empty:
                        vals = list(ldf["load_mw"].values[:24]) if "load_mw" in ldf.columns else []
                        if len(vals) == 24:
                            w = day.get("similarity_pct", 0) / 100.0
                            all_loads.append((w, vals))

                if all_loads:
                    total_w = sum(w for w, _ in all_loads)
                    if total_w > 0:
                        pred = [round(sum(w * lv[h] for w, lv in all_loads) / total_w, 2) for h in range(24)]
                        export_rows.append({
                            "类型": f"预测_{target_date_str}",
                            "相似度": "加权平均",
                            **{f"{h:02d}h": pred[h] for h in range(24)},
                        })

                if export_rows:
                    export_df = pd.DataFrame(export_rows)
                    # 转置：行=小时，列=日期
                    export_df_t = export_df.set_index("类型").T
                    export_df_t.index.name = "小时"

                    from io import BytesIO
                    col_a, col_b = st.columns(2)
                    with col_a:
                        output1 = BytesIO()
                        with pd.ExcelWriter(output1, engine="openpyxl") as writer:
                            export_df_t.to_excel(writer, sheet_name="24h负荷", index=True)
                        output1.seek(0)
                        st.download_button(
                            label=f"⬇️ 横表导出 ({target_date_str})",
                            data=output1,
                            file_name=f"相似日负荷_{target_date_str}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )

                    with col_b:
                        long_rows = []
                        for _, row in export_df.iterrows():
                            typ = row["类型"]
                            sim = row["相似度"]
                            for h in range(24):
                                long_rows.append({
                                    "类型": typ, "相似度": sim,
                                    "小时": h, "负荷_MW": row[f"{h:02d}h"],
                                })
                        long_df = pd.DataFrame(long_rows)
                        output2 = BytesIO()
                        with pd.ExcelWriter(output2, engine="openpyxl") as writer:
                            long_df.to_excel(writer, sheet_name="逐时数据", index=False)
                        output2.seek(0)
                        st.download_button(
                            label=f"⬇️ 逐时数据导出 ({target_date_str})",
                            data=output2,
                            file_name=f"相似日逐时数据_{target_date_str}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                else:
                    st.caption("暂无负荷数据可导出。")

# ============================================================
# Tab 5: 负荷预测
# ============================================================
with tab5:
    st.subheader("🔌 污水厂负荷预测")
    st.caption("基于历史负荷 + 排班日历 + 天气预报，预测未来逐时负荷")

    # ---- 顶部操作栏 ----
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    with c1:
        pred_company = st.selectbox("选择公司", options=PREDICTION_COMPANIES, key="pred_company_select")
    with c2:
        load_has = has_load_data(pred_company)
        load_start, load_end = query_load_date_range(pred_company)
        if load_has:
            st.success(f"✅ {pred_company}: {load_start} ~ {load_end}")
        else:
            st.info(f"💡 {pred_company} 暂无数据")
    with c3:
        st.write("")
        st.write("")
        if st.button("📂 导入数据", use_container_width=True, key="toggle_import"):
            st.session_state._show_import = not st.session_state.get("_show_import", False)
    with c4:
        if load_has:
            st.write("")
            st.write("")
            st.download_button(
                label="📥 导出", data=_build_hourly_export(pred_company),
                file_name=f"{pred_company}_逐时负荷_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # ---- 导入面板 ----
    if st.session_state.get("_show_import", False) or not load_has:
        with st.expander("📂 数据导入", expanded=not load_has):
            uploaded_load = st.file_uploader(
                f"上传 {pred_company} 负荷文件 (Excel/CSV)", type=["csv", "xlsx", "xls"],
                key="pred_load_uploader",
            )
            if uploaded_load is not None:
                from src.utils.csv_parser import parse_load_history_upload
                file_bytes = uploaded_load.getvalue()
                load_hist_df, error_msg = parse_load_history_upload(file_bytes, uploaded_load.name)
                if error_msg:
                    st.error(error_msg)
                elif load_hist_df is not None and not load_hist_df.empty:
                    load_hist_df["company"] = pred_company
                    n = import_load_from_df(load_hist_df, uploaded_load.name, pred_company)
                    st.success(f"✅ 已导入 {pred_company} {n} 条负荷记录")
                    st.session_state._show_import = False
                    st.rerun()

            st.divider()
            st.caption("或分别上传各公司数据：")
            batch_cols = st.columns(3)
            for i, company in enumerate(PREDICTION_COMPANIES):
                with batch_cols[i]:
                    co_has = has_load_data(company)
                    icon = "✅" if co_has else "⬜"
                    st.caption(f"{icon} {company}")
                    co_file = st.file_uploader(
                        company, type=["csv", "xlsx", "xls"],
                        key=f"batch_load_{company}", label_visibility="collapsed",
                    )
                    if co_file is not None:
                        co_bytes = co_file.getvalue()
                        co_df, co_err = parse_load_history_upload(co_bytes, co_file.name)
                        if co_err:
                            st.error(co_err)
                        elif co_df is not None and not co_df.empty:
                            co_df["company"] = company
                            import_load_from_df(co_df, co_file.name, company)
                            st.success(f"✅ {company}")
                            st.rerun()

        if not load_has:
            st.info("👆 请先导入历史负荷数据")
            st.stop()

    # ---- 排班 + 天气 ----
    existing_cal = get_calendar(pred_company)
    if not existing_cal.empty:
        st.session_state.calendar_df = existing_cal

    with st.expander("📅 排班日历", expanded=False):
        cal_mode = st.radio(
            "排班模式", options=["weekly_rule", "upload"],
            format_func=lambda x: "周规律" if x == "weekly_rule" else "上传排班表",
            horizontal=True, key="cal_mode",
        )
        if cal_mode == "weekly_rule":
            prod_days = st.multiselect(
                "每周生产日",
                options=[(0, "周一"), (1, "周二"), (2, "周三"), (3, "周四"), (4, "周五"), (5, "周六"), (6, "周日")],
                default=DEFAULT_PRODUCTION_DAYS, format_func=lambda x: x[1], key="prod_days_select",
            )
            special_dates_input = st.text_area(
                "特殊日（YYYY-MM-DD,类型）", placeholder="2026-10-01,holiday",
                height=68, key="special_dates_input",
            )
            if st.button("🔄 生成排班日历", key="gen_calendar"):
                prod_day_nums = [d[0] for d in prod_days]
                special_dates = {}
                if special_dates_input.strip():
                    for line in special_dates_input.strip().split("\n"):
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 2:
                            special_dates[parts[0]] = parts[1]
                if load_start and load_end:
                    cal_df = generate_calendar_from_rule(load_start, load_end, prod_day_nums, special_dates)
                    forecast_end_dt = datetime.strptime(load_end, "%Y-%m-%d") + timedelta(days=DEFAULT_FORECAST_DAYS_LIMIT)
                    cal_ext = generate_calendar_from_rule(load_end, forecast_end_dt.strftime("%Y-%m-%d"), prod_day_nums, special_dates)
                    cal_df = pd.concat([cal_df, cal_ext[cal_ext["date"] > cal_df["date"].max()]], ignore_index=True)
                    delete_calendar(pred_company)
                    import_calendar_from_df(cal_df, pred_company, "weekly_rule")
                    st.session_state.calendar_df = cal_df
                    st.success(f"✅ 已生成 {len(cal_df)} 天排班日历")
                    st.rerun()
        else:
            uploaded_cal = st.file_uploader("上传排班表", type=["csv", "xlsx"], key="cal_uploader")
            if uploaded_cal is not None:
                cal_raw = pd.read_csv(uploaded_cal) if uploaded_cal.name.endswith(".csv") else pd.read_excel(uploaded_cal)
                cal_df = parse_calendar_upload(cal_raw)
                if cal_df.empty:
                    st.error("无法解析排班表")
                else:
                    delete_calendar(pred_company)
                    import_calendar_from_df(cal_df, pred_company, "upload")
                    st.session_state.calendar_df = cal_df
                    st.success(f"✅ 已导入 {len(cal_df)} 天排班数据")
                    st.rerun()
        if not existing_cal.empty:
            st.caption(f"当前排班: {len(existing_cal)} 天")

    with st.expander("🌤️ 天气预报", expanded=False):
        st.caption("在表格中直接填写天气预报数据：")
        wx_has = False
        if "weather_editor_df" not in st.session_state:
            dates = pd.date_range(datetime.now(), periods=7, freq="D")
            st.session_state.weather_editor_df = pd.DataFrame({
                "date": dates.strftime("%Y-%m-%d"),
                "tmax": [32.0] * 7,
                "tmin": [25.0] * 7,
                "humidity_avg": [75.0] * 7,
                "precip_sum": [0.0] * 7,
                "rad_sum": [5000.0] * 7,
            })
        wx_days = st.slider("预报天数", 1, 31, 7, 1, key="wx_days")
        current_df = st.session_state.weather_editor_df
        if len(current_df) < wx_days:
            extra = wx_days - len(current_df)
            last_date = pd.Timestamp(current_df["date"].iloc[-1])
            new_rows = pd.DataFrame({
                "date": pd.date_range(last_date + pd.Timedelta(days=1), periods=extra, freq="D").strftime("%Y-%m-%d"),
                "tmax": [current_df["tmax"].iloc[-1]] * extra,
                "tmin": [current_df["tmin"].iloc[-1]] * extra,
                "humidity_avg": [current_df["humidity_avg"].iloc[-1]] * extra,
                "precip_sum": [0.0] * extra,
                "rad_sum": [current_df["rad_sum"].iloc[-1]] * extra,
            })
            current_df = pd.concat([current_df, new_rows], ignore_index=True)
        elif len(current_df) > wx_days:
            current_df = current_df.head(wx_days)

        edited = st.data_editor(
            current_df,
            column_config={
                "date": st.column_config.TextColumn("日期", disabled=True),
                "tmax": st.column_config.NumberColumn("最高温 °C", min_value=-20.0, max_value=50.0, step=0.5, format="%.1f"),
                "tmin": st.column_config.NumberColumn("最低温 °C", min_value=-20.0, max_value=50.0, step=0.5, format="%.1f"),
                "humidity_avg": st.column_config.NumberColumn("湿度 %", min_value=0.0, max_value=100.0, step=1.0, format="%.0f"),
                "precip_sum": st.column_config.NumberColumn("降水 mm", min_value=0.0, max_value=500.0, step=1.0, format="%.1f"),
                "rad_sum": st.column_config.NumberColumn("辐射 W/m²·d", min_value=0.0, max_value=15000.0, step=100.0, format="%.0f"),
            },
            use_container_width=True,
            num_rows="fixed",
            height=250,
            key="weather_editor",
        )
        st.session_state.weather_editor_df = edited

        if st.button("✅ 确认天气数据", use_container_width=True, key="confirm_wx"):
            st.session_state.weather_forecast_df = edited.rename(columns={"date": "date"})
            st.success(f"✅ 已保存 {len(edited)} 天天气预报")
            st.rerun()

        wx_has = st.session_state.weather_forecast_df is not None and not st.session_state.weather_forecast_df.empty
        st.caption(f"已保存: {len(st.session_state.weather_forecast_df)} 天" if wx_has else "✏️ 填完点「确认天气数据」即可生效")

    # ---- 预测参数 + 运行 ----
    col_p1, col_p2, col_p3 = st.columns([1, 1, 2])
    with col_p1:
        forecast_horizon = st.slider("预测天数", 1, DEFAULT_FORECAST_DAYS_LIMIT, 31, 1)
    with col_p2:
        knn_k = st.slider("KNN 匹配数", 1, 10, DEFAULT_KNN_K, 1)
    with col_p3:
        st.write("")
        if st.button("🚀 运行预测", type="primary", use_container_width=True, key="run_forecast_btn"):
            with st.spinner(f"预测 {pred_company} 未来 {forecast_horizon} 天..."):
                df_load = query_load_all(pred_company)
                df_hourly = prepare_load_data(df_load, pred_company)
                cal_df = st.session_state.calendar_df
                wx_df = st.session_state.weather_forecast_df
                result = run_forecast(
                    company=pred_company, df_hourly=df_hourly,
                    forecast_horizon=forecast_horizon,
                    calendar_df=cal_df if cal_df is not None and not cal_df.empty else None,
                    weather_df=wx_df if wx_df is not None and not wx_df.empty else None,
                    k=knn_k,
                )
                st.session_state.prediction_result = result
                st.session_state.prediction_company = pred_company
                st.session_state._df_load = df_load
            st.success("✅ 预测完成")

    st.divider()

    # ---- 预测结果 ----
    result = st.session_state.prediction_result
    if result is not None and st.session_state.prediction_company == pred_company:
        if "error" in result:
            st.error(result["error"])
        else:
            df_load = st.session_state.get("_df_load")
            if df_load is None:
                df_load = query_load_all(pred_company)
            df_hourly = prepare_load_data(df_load, pred_company)
            daily_series = prepare_daily_series(df_hourly)

            forecast = result["daily_forecast"]
            hourly_df = pd.DataFrame(result["hourly_results"])
            info = result.get("info", {})
            cal_df = st.session_state.calendar_df

            # 回测 MAPE
            hist_dates = set(str(d) for d in daily_series.index)
            overlap = hourly_df[hourly_df["date"].apply(lambda d: str(d) in hist_dates)]
            mape_val = None
            if len(overlap) >= 24 * 7:
                daily_pred = overlap.groupby("date")["load_mw"].sum()
                daily_actual = {}
                for d in daily_pred.index:
                    key = pd.Timestamp(d).strftime("%Y-%m-%d")
                    if key in daily_series.index:
                        daily_actual[d] = daily_series[key]
                if daily_actual:
                    a = np.array(list(daily_actual.values()))
                    p = np.array([daily_pred[d] for d in daily_actual.keys()])
                    mape_val = float(np.mean(np.abs((a - p) / (a + 1e-6))) * 100)

            # KPI 卡片
            metrics = [
                ("预测日均", f"{forecast.mean():.1f} MWh"),
                ("历史日均", f"{daily_series.mean():.1f} MWh"),
                ("最优窗口", f"{info.get('best_window', '-')} 天"),
            ]
            if mape_val is not None:
                delta = "normal" if mape_val < 10 else "off" if mape_val < 20 else "inverse"
                metrics.append((f"回测 MAPE", f"{mape_val:.1f}%"))
            else:
                rs = info.get('residual_std')
                metrics.append(("回测残差", f"{rs:.1f} MWh" if isinstance(rs, (int, float)) else "-"))

            mcols = st.columns(len(metrics))
            for i, (label, value) in enumerate(metrics):
                with mcols[i]:
                    st.metric(label, value)

            # 图表
            st.plotly_chart(
                plot_daily_forecast(daily_series, forecast, result["daily_lower"], result["daily_upper"], pred_company),
                use_container_width=True,
            )

            c_l, c_r = st.columns(2)
            with c_l:
                st.plotly_chart(plot_hourly_profile(result["hourly_results"], company=pred_company), use_container_width=True)
            with c_r:
                st.plotly_chart(
                    plot_weekday_vs_rest(result["hourly_results"],
                        cal_df if cal_df is not None and not cal_df.empty else None, pred_company),
                    use_container_width=True,
                )

            st.plotly_chart(
                plot_template_matches(result["hourly_results"], df_hourly, pred_company),
                use_container_width=True,
            )

            # 数据表 + 导出
            daily_report = hourly_df.groupby("date").agg(
                日均负荷_MW=("load_mw", "mean"), 日峰荷_MW=("load_mw", "max"),
                日谷荷_MW=("load_mw", "min"), 日总用电量_MWh=("load_mw", "sum"),
                峰谷差_MW=("load_mw", lambda x: x.max() - x.min()),
            ).reset_index()
            daily_report.columns = ["日期", "日均负荷_MW", "日峰荷_MW", "日谷荷_MW", "日总用电量_MWh", "峰谷差_MW"]
            daily_report["日期"] = daily_report["日期"].astype(str)

            # 只导出预测日（历史最后一天之后）
            last_hist_date = pd.Timestamp(daily_series.index[-1])
            forecast_hourly = hourly_df[
                hourly_df["datetime"] > last_hist_date
            ][["datetime", "load_mw", "daily_total_mwh", "profile_std_mw"]]

            with st.expander("📋 预测数据表 + 导出", expanded=False):
                st.dataframe(daily_report, use_container_width=True, height=250, hide_index=True)
                from io import BytesIO
                output = BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    daily_report.to_excel(writer, sheet_name="日汇总", index=False)
                    forecast_hourly.to_excel(writer, sheet_name="逐时数据", index=False)
                output.seek(0)
                st.download_button(
                    f"⬇️ 下载 {pred_company} 预测日逐时负荷 Excel", data=output,
                    file_name=f"{pred_company}_预测日逐时负荷_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

# ============================================================
# 自动刷新逻辑
# ============================================================
if auto_refresh:
    import time

    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = datetime.now()

    elapsed = (datetime.now() - st.session_state.last_refresh).total_seconds()
    if elapsed > CACHE_TTL_SECONDS:
        st.session_state.last_refresh = datetime.now()
        st.cache_data.clear()

try:
    clean_old_forecasts(7)
except Exception:
    pass

if auto_refresh != (get_setting("auto_refresh", "true") == "true"):
    save_setting("auto_refresh", "true" if auto_refresh else "false")
save_setting("default_history_days", str(history_days))
