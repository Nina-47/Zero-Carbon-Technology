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
        _conn.execute("UPDATE weather_hourly SET datetime = REPLACE(datetime, '+08:00', '') WHERE datetime LIKE '%+08:00'")

        # 聚合: (date, hour) → {temperature_2m, precipitation, ...}
        from collections import defaultdict
        records = defaultdict(dict)
        for _, row in df.iterrows():
            date_val = str(row["date"])[:10]
            element = str(row["element"])
            col_name = element_map.get(element)
            if col_name is None:
                continue
            for h in range(24):
                val = row[h]
                if pd.isna(val):
                    continue
                dt = f"{date_val}T{h:02d}:00:00"
                records[dt][col_name] = float(val)

        cols = ["location_id", "datetime", "data_type", "source",
                "temperature_2m", "precipitation", "wind_speed_10m",
                "wind_direction_10m", "cloud_cover", "shortwave_radiation", "fetched_at"]
        phs = ",".join(["?"] * len(cols))
        sql = f"INSERT OR REPLACE INTO weather_hourly ({','.join(cols)}) VALUES ({phs})"
        now = pd.Timestamp.now().isoformat()
        inserted = 0
        for dt, vals in records.items():
            row = [
                "zhongshan", dt, "historical", "seed",
                vals.get("temperature_2m"),
                vals.get("precipitation"),
                vals.get("wind_speed_10m"),
                vals.get("wind_direction_10m"),
                vals.get("cloud_cover"),
                vals.get("shortwave_radiation"),
                now,
            ]
            try:
                _conn.execute(sql, row)
                inserted += 1
            except Exception:
                pass
        _conn.commit()
        _conn.close()
    except Exception:
        pass

_seed_weather_db()

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
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 天气总览",
    "🔗 负荷叠加分析",
    "📋 数据表格与导出",
    "🔮 相似日分析",
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

    load_available = has_load_data()
    load_start, load_end = query_load_date_range()

    import json as _json

    @st.cache_data(ttl=86400, show_spinner=False)
    def _load_similarity_db():
        sim_path = os.path.join(os.path.dirname(__file__), "data", "similarity_results.json")
        if not os.path.exists(sim_path):
            return {}
        with open(sim_path, "r", encoding="utf-8") as f:
            return _json.load(f).get("results", {})

    similarity_db = _load_similarity_db()
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
        max_date = today + timedelta(days=7)

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
                # 不在预计算库中：用侧边栏已有的天气数据实时匹配
                if not primary_data.empty and "datetime" in primary_data.columns:
                    # 调试：显示 primary_data 覆盖的日期范围
                    pd_dates = sorted(set(str(d)[:10] for d in primary_data["datetime"]))
                    target_wx = primary_data[
                        primary_data["datetime"].apply(lambda x: str(x)[:10]) == target_date_str
                    ].copy()
                    if target_wx.empty:
                        st.warning(
                            f"目标日 {target_date_str} 暂无天气数据。\n\n"
                            f"当前天气数据覆盖: {pd_dates[0]} ~ {pd_dates[-1]} "
                            f"(共 {len(pd_dates)} 天)。"
                            f"请调整侧边栏「历史回溯」或「预报天数」后刷新。"
                        )
                    else:
                        st.info("目标日不在预计算库中，使用实时天气数据匹配。")
                        target_daily = compute_daily_weather(target_wx)
                        if not target_daily.empty:
                            tr = target_daily.iloc[0]
                            target = {
                                "tmax": tr.get("tmax", 0), "tmin": tr.get("tmin", 0),
                                "precip_sum": tr.get("precip_sum", 0),
                                "precip_level": int(tr.get("precip_level", 0)),
                            }
                            target_m = target_date.month
                            target_s = 0 if target_m in [12,1,2] else 1 if target_m in [3,4,5] else 2 if target_m in [6,7,8] else 3
                            target_rainy = target["precip_sum"] >= 0.5
                            season_names = ["冬", "春", "夏", "秋"]
                            weekday_names = ["一", "二", "三", "四", "五", "六", "日"]

                            scored = []
                            for d_str in sim_dates:
                                d_dt = datetime.strptime(d_str, "%Y-%m-%d")
                                dm = d_dt.month
                                ds = 0 if dm in [12,1,2] else 1 if dm in [3,4,5] else 2 if dm in [6,7,8] else 3
                                if ds != target_s:
                                    continue
                                pre = similarity_db.get(d_str, [])
                                if not pre:
                                    continue
                                c = pre[0]
                                cand_rainy = c["precip_sum"] >= 0.5
                                if target_rainy != cand_rainy:
                                    continue
                                tmax_d = abs(target["tmax"] - c["tmax"]) if target["tmax"] and c["tmax"] else 0
                                tmin_d = abs(target["tmin"] - c["tmin"]) if target["tmin"] and c["tmin"] else 0
                                delta = (target_date - d_dt.date()).days
                                decay = min(abs(delta) / 365.0, 1.0)
                                score = 0.35 * tmax_d + 0.35 * tmin_d + 0.3 * decay
                                scored.append((d_str, score, c))

                            scored.sort(key=lambda x: x[1])
                            similar_days = []
                            for d_str, score, c in scored[:3]:
                                dd = datetime.strptime(d_str, "%Y-%m-%d")
                                sim = max(50.0, round(100.0 - score * 15, 1))
                                similar_days.append({
                                    "date": dd,
                                    "similarity_score": round(score, 4),
                                    "similarity_pct": sim,
                                    "tmax": c["tmax"],
                                    "tmin": c["tmin"],
                                    "precip_sum": c["precip_sum"],
                                    "precip_level": c.get("precip_level", 0),
                                    "rad_daily_sum": c["rad_sum"],
                                    "dew_point_avg": None,
                                    "season_label": season_names[c["season"]],
                                    "weekday_label": weekday_names[c["weekday"]],
                                    "distance_components": {},
                                })

                            st.session_state.similar_days = similar_days
                            st.session_state.target_date_str = target_date_str
                            st.session_state.similar_search_done = True
                            st.session_state.target_weather = target_wx
                else:
                    st.warning("天气数据加载中，请稍候再试。")
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
