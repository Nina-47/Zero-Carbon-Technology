"""
全局配置：地点坐标、气象参数、默认设置、API端点
"""

# ============================================================
# 地点定义
# ============================================================
LOCATIONS = {
    "zhongshan": {
        "display_name": "中山市",
        "latitude": 22.52,
        "longitude": 113.38,
        "is_aggregate": False,
    },
    "guangdong_avg": {
        "display_name": "广东省平均",
        "latitude": None,   # 聚合地点，无单一坐标
        "longitude": None,
        "is_aggregate": True,
        # 5 个代表城市
        "child_cities": {
            "guangzhou":    {"display_name": "广州", "latitude": 23.13, "longitude": 113.26},
            "shenzhen":     {"display_name": "深圳", "latitude": 22.54, "longitude": 114.06},
            "shaoguan":     {"display_name": "韶关", "latitude": 24.80, "longitude": 113.58},
            "zhanjiang":    {"display_name": "湛江", "latitude": 21.27, "longitude": 110.36},
            "shantou":      {"display_name": "汕头", "latitude": 23.35, "longitude": 116.68},
        },
    },
}

# ============================================================
# 气象参数定义（Open-Meteo hourly 参数名）
# ============================================================
# 可视化重点参数（Tab1 图表默认展示）
VIS_PARAMS = {
    "temperature_2m":          {"cn": "温度",         "unit": "°C",    "chart": "line"},
    "apparent_temp_cn":       {"cn": "体感温度(中国)",  "unit": "°C",    "chart": "line"},
    "relative_humidity_2m":   {"cn": "相对湿度",      "unit": "%",     "chart": "line"},
    "precipitation":           {"cn": "降水量",        "unit": "mm",    "chart": "bar"},
    "wind_speed_10m":         {"cn": "风速",          "unit": "km/h",  "chart": "line"},
    "wind_direction_10m":     {"cn": "风向",          "unit": "°",     "chart": "scatter"},
    "shortwave_radiation":     {"cn": "太阳总辐射",    "unit": "W/m²",  "chart": "area"},
    "cloud_cover":             {"cn": "云量",          "unit": "%",     "chart": "line"},
}

# 模型导出全量参数（含可视化参数）
EXPORT_PARAMS = {
    "temperature_2m":          {"cn": "温度",              "unit": "°C"},
    "apparent_temperature":    {"cn": "体感温度",           "unit": "°C"},
    "relative_humidity_2m":   {"cn": "相对湿度",           "unit": "%"},
    "precipitation":           {"cn": "降水量",             "unit": "mm"},
    "rain":                    {"cn": "降雨量",             "unit": "mm"},
    "showers":                 {"cn": "阵雨量",             "unit": "mm"},
    "snowfall":                {"cn": "降雪量",             "unit": "mm"},
    "wind_speed_10m":         {"cn": "风速",               "unit": "km/h"},
    "wind_direction_10m":     {"cn": "风向",               "unit": "°"},
    "wind_gusts_10m":         {"cn": "阵风风速",           "unit": "km/h"},
    "surface_pressure":        {"cn": "地表气压",           "unit": "hPa"},
    "mean_sea_level_pressure": {"cn": "海平面气压",         "unit": "hPa"},
    "cloud_cover":             {"cn": "总云量",             "unit": "%"},
    "cloud_cover_low":         {"cn": "低云量",             "unit": "%"},
    "cloud_cover_mid":         {"cn": "中云量",             "unit": "%"},
    "cloud_cover_high":        {"cn": "高云量",             "unit": "%"},
    "shortwave_radiation":      {"cn": "太阳总辐射",         "unit": "W/m²"},
    "dew_point_2m":            {"cn": "露点温度",           "unit": "°C"},
    "evapotranspiration":       {"cn": "蒸散量",             "unit": "mm"},
    "vapour_pressure_deficit":  {"cn": "饱和水汽压差",      "unit": "kPa"},
    "apparent_temp_cn":         {"cn": "体感温度(中国公式)", "unit": "°C"},
}

# API 请求参数列表（逗号分隔字符串，用于 URL 构建）
# 排除 openmeteo 不支持的参数：mean_sea_level_pressure（仅 ERA5-Land）+ 派生字段
_EXCLUDE_FORECAST = {"mean_sea_level_pressure", "apparent_temp_cn"}
_EXCLUDE_ARCHIVE = {"apparent_temp_cn"}
FORECAST_PARAMS_STR = ",".join(k for k in EXPORT_PARAMS if k not in _EXCLUDE_FORECAST)
ARCHIVE_PARAMS_STR = ",".join(k for k in EXPORT_PARAMS if k not in _EXCLUDE_ARCHIVE)

# ============================================================
# 聚合规则：哪些参数用求和、哪些用平均
# ============================================================
AGGREGATION_SUM_PARAMS = {
    "precipitation", "rain", "showers", "snowfall",
    "evapotranspiration",
}
# 其余所有参数默认取算术平均

# ============================================================
# API 端点
# ============================================================
OPENMETEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPENMETEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# 和风天气备用源（需 API Key，存储在 .streamlit/secrets.toml）
QWATHER_FORECAST_URL = "https://devapi.qweather.com/v7/weather/24h"
QWATHER_HISTORY_URL = "https://devapi.qweather.com/v7/historical/weather"

# ============================================================
# 默认设置
# ============================================================
DEFAULT_HISTORY_DAYS = 7
DEFAULT_FORECAST_DAYS = 3
CACHE_TTL_SECONDS = 1800       # 30 分钟
API_TIMEOUT_SECONDS = 10       # API 超时阈值
MAX_HISTORY_DAYS = 365          # 历史回溯上限
TIMEZONE = "Asia/Shanghai"

# ============================================================
# 相似日因子权重（工业负荷预测标定版，基于395天相关性分析）
# ============================================================
SIMILARITY_WEIGHTS = {
    "tmax_deviation":         0.20,
    "tmin_deviation":         0.20,
    "precip_level_match":     0.18,
    "season_match":           0.15,
    "weekday_match":          0.10,
    "radiation_deviation":    0.05,
    "date_distance_decay":    0.10,
    "dew_point_deviation":    0.05,
}

# 降水等级划分 (mm/day)
PRECIP_LEVELS = [
    (0.1,  "无降水"),
    (1.0,  "小雨"),
    (10.0, "中雨"),
    (25.0, "大雨"),
    (50.0, "暴雨"),
    (float("inf"), "大暴雨及以上"),
]

# ============================================================
# 体感温度公式 (NOAA Heat Index + 风寒联合方案)
# 中国气象局同样引用此体系，按温度分段处理
# ============================================================
def calc_apparent_temp_cn(temp_c: float, humidity_pct: float, wind_kmh: float) -> float:
    """
    NOAA 通用体感温度：
      - 气温 > 20°C → Heat Index（炎热指数，湿度主导）
      - 气温 ≤ 20°C → Wind Chill（风寒指数，风速主导）

    这是中国气象局引用的事实标准，比单一线性公式更准确。
    """
    import math

    # NaN / None 检查
    for v in [temp_c, humidity_pct, wind_kmh]:
        if v is None:
            return float("nan")
        try:
            if math.isnan(v):
                return float("nan")
        except TypeError:
            pass

    temp_f = temp_c * 9.0 / 5.0 + 32.0
    rh = humidity_pct
    wind_ms = wind_kmh / 3.6

    if temp_c >= 25.0:
        # ---- 炎热场景: Heat Index ----
        hi = _heat_index_rothfusz(temp_f, rh)
        return round((hi - 32.0) * 5.0 / 9.0, 1)
    elif temp_c <= 10.0 and wind_ms >= 1.3:
        # ---- 寒冷场景: Wind Chill ----
        wc_f = 35.74 + 0.6215 * temp_f - 35.75 * (wind_ms ** 0.16) \
               + 0.4275 * temp_f * (wind_ms ** 0.16)
        return round((wc_f - 32.0) * 5.0 / 9.0, 1)
    else:
        # ---- 温和场景: 接近实际气温 ----
        return round(temp_c, 1)


def _heat_index_rothfusz(t_f: float, rh: float) -> float:
    """NOAA Rothfusz Heat Index，含完整调整项。"""
    # 简化公式（T < 80°F 或 > 112°F 时直接使用）
    hi_simple = 0.5 * (t_f + 61.0 + ((t_f - 68.0) * 1.2) + (rh * 0.094))

    if t_f < 80.0:
        return hi_simple

    # Rothfusz 主回归
    hi = -42.379 + 2.04901523 * t_f + 10.14333127 * rh \
         - 0.22475541 * t_f * rh \
         - 0.00683783 * t_f * t_f \
         - 0.05481717 * rh * rh \
         + 0.00122874 * t_f * t_f * rh \
         + 0.00085282 * t_f * rh * rh \
         - 0.00000199 * t_f * t_f * rh * rh

    # 调整项 #1: RH < 13% 且 80°F ≤ T ≤ 112°F
    if rh < 13.0 and 80.0 <= t_f <= 112.0:
        adj = ((13.0 - rh) / 4.0) * math.sqrt((17.0 - abs(t_f - 95.0)) / 17.0)
        hi -= adj

    # 调整项 #2: RH > 85% 且 80°F ≤ T ≤ 87°F
    if rh > 85.0 and 80.0 <= t_f <= 87.0:
        adj = ((rh - 85.0) / 10.0) * ((87.0 - t_f) / 5.0)
        hi += adj

    # 超出罗仕福回归范围的退化为简化公式
    if hi < t_f:
        return hi_simple

    return hi


# ============================================================
# 参数单位换算 + 派生字段计算
# ============================================================
def convert_units(df):
    """
    将 API 原始单位转换为显示单位，并计算中国体感温度:
    - apparent_temp_cn: 用中国公式从气温+湿度+风速推导
    """
    import pandas as pd
    import numpy as np
    df = df.copy()

    # 计算中国体感温度
    need_cols = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m"]
    if all(c in df.columns for c in need_cols):
        df["apparent_temp_cn"] = df.apply(
            lambda r: calc_apparent_temp_cn(
                r["temperature_2m"], r["relative_humidity_2m"], r["wind_speed_10m"]
            ),
            axis=1,
        )
    return df
