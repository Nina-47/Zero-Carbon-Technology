"""
天气预报数据解析
"""
import pandas as pd
import numpy as np
from datetime import datetime


def parse_weather_forecast_upload(df: pd.DataFrame) -> pd.DataFrame | None:
    """
    解析上传的天气预报文件。

    支持两种格式：
    - 逐日格式: 日期 + tmax + tmin + humidity_avg + precip_sum (+ rad_sum)
    - 逐时格式: datetime + temperature_2m + humidity + precipitation (+ radiation)

    返回标准逐日 DataFrame: [date, tmax, tmin, humidity_avg, precip_sum, rad_sum]
    若无 rad_sum 列则填充 NaN。
    """
    df = df.copy()

    fmt, date_col = _detect_format(df)

    if fmt == "hourly":
        return _hourly_to_daily(df, date_col)
    elif fmt == "daily":
        return _parse_daily_format(df, date_col)
    else:
        return None


def _detect_format(df: pd.DataFrame) -> tuple[str, str]:
    """检测是逐时还是逐日格式。"""
    date_col = _find_date_col(df)
    if date_col is None:
        date_col = df.columns[0]

    datetime_patterns = ["datetime", "date_time", "时间", "timestamp"]
    has_dt = date_col and any(p in str(date_col).lower() for p in datetime_patterns)

    hour_patterns = ["hour", "小时", "h", "时"]
    has_hour = any(any(p in str(c).lower() for p in hour_patterns) for c in df.columns)

    if has_dt and has_hour:
        return ("hourly", date_col)

    return ("daily", date_col)


def _hourly_to_daily(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """逐时数据聚合成逐日。"""
    df["_dt"] = pd.to_datetime(df[date_col], errors="coerce")
    df["_date"] = df["_dt"].dt.date

    temp_col = _find_col(df, ["temperature", "temp", "温度", "气温"])
    humid_col = _find_col(df, ["humidity", "湿度", "rh"])
    precip_col = _find_col(df, ["precipitation", "precip", "降水", "降雨"])
    rad_col = _find_col(df, ["radiation", "rad", "辐照", "辐射", "shortwave"])

    agg = {"_date": "first"}
    if temp_col:
        agg["tmax"] = (temp_col, "max")
        agg["tmin"] = (temp_col, "min")
    if humid_col:
        agg["humidity_avg"] = (humid_col, "mean")
    if precip_col:
        agg["precip_sum"] = (precip_col, "sum")
    if rad_col:
        agg["rad_sum"] = (rad_col, "sum")

    if len(agg) <= 1:
        return None

    daily = df.groupby("_date", as_index=False).agg(**{
        k: v for k, v in agg.items() if k != "_date"
    })
    daily["date"] = pd.to_datetime(daily["_date"]).dt.strftime("%Y-%m-%d")
    daily = daily.drop(columns=["_date"])

    for col in ["tmax", "tmin", "humidity_avg", "precip_sum", "rad_sum"]:
        if col not in daily.columns:
            daily[col] = np.nan

    return daily[["date", "tmax", "tmin", "humidity_avg", "precip_sum", "rad_sum"]]


def _parse_daily_format(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """解析逐日格式。"""
    result = pd.DataFrame()
    result["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")

    tmax_col = _find_col(df, ["tmax", "max_temp", "最高温", "最高温度", "最高气温", "max temp"])
    tmin_col = _find_col(df, ["tmin", "min_temp", "最低温", "最低温度", "最低气温", "min temp"])
    humid_col = _find_col(df, ["humidity", "湿度", "rh", "相对湿度"])
    precip_col = _find_col(df, ["precipitation", "precip", "降水", "降雨", "降水量"])
    rad_col = _find_col(df, ["radiation", "rad", "辐照", "辐射", "shortwave", "太阳辐射"])

    result["tmax"] = pd.to_numeric(df[tmax_col], errors="coerce") if tmax_col else np.nan
    result["tmin"] = pd.to_numeric(df[tmin_col], errors="coerce") if tmin_col else np.nan
    result["humidity_avg"] = pd.to_numeric(df[humid_col], errors="coerce") if humid_col else np.nan
    result["precip_sum"] = pd.to_numeric(df[precip_col], errors="coerce") if precip_col else np.nan
    result["rad_sum"] = pd.to_numeric(df[rad_col], errors="coerce") if rad_col else np.nan

    result = result.dropna(subset=["date"])
    if result.empty:
        return None
    return result


def _find_date_col(df: pd.DataFrame) -> str | None:
    candidates = ["date", "日期", "datetime", "时间", "time", "ds", "dt"]
    for col in df.columns:
        col_lower = str(col).lower().strip()
        for cand in candidates:
            if cand in col_lower:
                return col
    return df.columns[0] if len(df.columns) > 0 else None


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in df.columns:
        col_lower = str(col).lower().strip()
        for cand in candidates:
            if cand in col_lower:
                return col
    return None
