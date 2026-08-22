"""
预测配置：公司列表、默认参数、天气修正系数
"""
COMPANIES = ["A公司", "B公司", "C公司"]

DAY_TYPE_MAP = {
    "production": {"label": "生产日", "weight": 1.0},
    "rest": {"label": "休息日", "weight": 0.7},
    "holiday": {"label": "节假日", "weight": 0.4},
}

DEFAULT_PRODUCTION_DAYS = [(0, "周一"), (1, "周二"), (2, "周三"), (3, "周四"), (4, "周五")]

DEFAULT_KNN_K = 5
DEFAULT_FORECAST_HORIZON = 31
DEFAULT_MIN_WINDOW = 14

WEATHER_CORRECTION_WINDOWS = [14, 21, 28, 42, 56]
REG_STRENGTHS = [0.0, 0.2, 0.4, 0.6]

WEATHER_CORRECTION_PARAMS = {
    "hot_temp_threshold": 35,
    "hot_temp_factor": 1.03,
    "cold_temp_threshold": 5,
    "cold_temp_factor": 1.02,
    "heavy_rain_threshold": 10,
    "heavy_rain_factor": 0.98,
    "solar_max_reduction": 0.05,
    "solar_reference_rad": 5000.0,
}
