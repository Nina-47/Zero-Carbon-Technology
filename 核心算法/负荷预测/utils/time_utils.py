"""
时间处理工具：时区转换、日期范围生成、格式化
"""

from datetime import datetime, timedelta
import pandas as pd
from config import TIMEZONE


def now_cn() -> datetime:
    """返回中国时区当前时间。"""
    return datetime.now()


def date_range(days_back: int, days_forward: int = 0) -> tuple[str, str]:
    """
    生成查询时间范围。

    返回
    ----
    (start_iso, end_iso) : ISO 8601 格式的起止时间字符串。
    """
    end = now_cn() + timedelta(days=days_forward)
    start = end - timedelta(days=days_back)
    return start.strftime("%Y-%m-%dT%H:%M:%S"), end.strftime("%Y-%m-%dT%H:%M:%S")


def date_range_dates(days_back: int, days_forward: int = 0) -> tuple[str, str]:
    """生成日期范围 ('YYYY-MM-DD' 格式)，用于 API 请求。"""
    today = now_cn().date()
    start = today - timedelta(days=days_back)
    end = today + timedelta(days=days_forward)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def format_dt_cn(dt: datetime) -> str:
    """格式化为中文可读时间。"""
    return dt.strftime("%Y-%m-%d %H:%M")


def hour_round(dt: datetime) -> datetime:
    """将 datetime 对齐到整点。"""
    return dt.replace(minute=0, second=0, microsecond=0)


def hours_between(start: datetime, end: datetime) -> int:
    """计算两个时间之间的小时数。"""
    return int((end - start).total_seconds() / 3600)
