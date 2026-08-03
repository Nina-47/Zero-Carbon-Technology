"""
排班日历处理：周规律 + 特殊日叠加
"""
import pandas as pd
from datetime import datetime, timedelta
from . import DEFAULT_PRODUCTION_DAYS, DAY_TYPE_MAP


def generate_calendar_from_rule(
    start_date: str,
    end_date: str,
    production_days: list[int] = None,
    special_dates: dict = None,
) -> pd.DataFrame:
    """
    根据周规律 + 特殊日生成排班日历。

    参数
    ----
    start_date, end_date : str
        日期范围 "YYYY-MM-DD"。
    production_days : list[int]
        每周生产日（0=周一...6=周日），默认周一至周五。
    special_dates : dict
        {"2026-07-01": "holiday", "2026-07-05": "rest", ...} 特殊日覆盖。

    返回
    ----
    pd.DataFrame: [date, day_type, day_type_weight]
    """
    if production_days is None:
        production_days = DEFAULT_PRODUCTION_DAYS
    if special_dates is None:
        special_dates = {}

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    rows = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        if date_str in special_dates:
            day_type = special_dates[date_str]
        elif current.weekday() in production_days:
            day_type = "production"
        else:
            day_type = "rest"

        weight = DAY_TYPE_MAP.get(day_type, {}).get("weight", 1.0)
        rows.append({"date": date_str, "day_type": day_type, "day_type_weight": weight})
        current += timedelta(days=1)

    return pd.DataFrame(rows)


def parse_calendar_upload(df: pd.DataFrame) -> pd.DataFrame:
    """
    解析上传的排班 Excel/CSV。

    支持的列名（模糊匹配）：
    - 日期列: date, 日期
    - 类型列: type, 类型, day_type, 排班
    - 权重列（可选）: weight, 权重

    类型值映射: 生产日/production→production, 休息日/rest→rest, 节假日/holiday→holiday
    """
    result = pd.DataFrame()

    date_col = _find_col(df, ["日期", "date", "datetime", "时间"])
    type_col = _find_col(df, ["类型", "type", "day_type", "排班", "日程"])
    weight_col = _find_col(df, ["weight", "权重"])

    if date_col is None or type_col is None:
        return pd.DataFrame()

    result["date"] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")

    type_map = {
        "生产日": "production", "production": "production",
        "休息日": "rest", "rest": "rest",
        "节假日": "holiday", "holiday": "holiday",
        "节日": "holiday",
        "工作日": "production", "周末": "rest",
    }
    result["day_type"] = df[type_col].astype(str).str.strip().map(
        lambda x: type_map.get(x, "production")
    )

    if weight_col:
        result["day_type_weight"] = pd.to_numeric(df[weight_col], errors="coerce").fillna(1.0)
    else:
        result["day_type_weight"] = result["day_type"].map(
            lambda x: DAY_TYPE_MAP.get(x, {}).get("weight", 1.0)
        )

    return result.dropna(subset=["date"])


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """模糊列名匹配。"""
    for col in df.columns:
        col_lower = str(col).lower().strip()
        for cand in candidates:
            if cand in col_lower:
                return col
    return None
