"""
预测配置：公司列表、默认参数、天气修正系数
"""
COMPANIES = ["A公司", "B公司", "C公司"]

DAY_TYPE_MAP = {
    "production": {"label": "生产日", "weight": 1.0},
    "rest": {"label": "休息日", "weight": 0.7},
    "holiday": {"label": "节假日", "weight": 0.4},
}

DEFAULT_PRODUCTION_DAYS = [0, 1, 2, 3, 4]  # 周一至周五

DEFAULT_KNN_K = 5
DEFAULT_FORECAST_HORIZON = 31
DEFAULT_MIN_WINDOW = 14

WEATHER_CORRECTION_WINDOWS = [14, 21, 28, 42, 56]
REG_STRENGTHS = [0.0, 0.2, 0.4, 0.6]
