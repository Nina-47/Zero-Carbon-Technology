"""
核心预测算法：自适应窗口日总量预测 + KNN 模板匹配逐时分配
整合排班日历 + 天气预报修正
"""
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error
from . import (
    COMPANIES, DAY_TYPE_MAP,
    DEFAULT_KNN_K, DEFAULT_FORECAST_HORIZON,
    DEFAULT_MIN_WINDOW, WEATHER_CORRECTION_WINDOWS, REG_STRENGTHS,
    WEATHER_CORRECTION_PARAMS,
)
from .calendar import generate_calendar_from_rule


def prepare_load_data(df_load: pd.DataFrame, company: str) -> pd.DataFrame:
    """
    从 load_history 表数据中提取指定公司的逐时数据，构建可用于建模的 DataFrame。
    """
    if df_load.empty:
        return pd.DataFrame()

    df = df_load.copy()
    if "company" in df.columns:
        df = df[df["company"] == company]

    if df.empty:
        return df

    df["datetime"] = pd.to_datetime(df["datetime"])
    df["date"] = df["datetime"].dt.date
    df["hour"] = df["datetime"].dt.hour
    df["dow"] = df["datetime"].dt.dayofweek
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df = df.sort_values(["datetime"]).reset_index(drop=True)
    return df


def prepare_daily_series(df_hourly: pd.DataFrame) -> pd.Series:
    """从逐时数据计算日总量序列。"""
    if df_hourly.empty:
        return pd.Series(dtype=float)
    daily = df_hourly.groupby("date")["load_mw"].sum()
    daily.index = pd.to_datetime(daily.index)
    return daily.sort_index()


def forecast_daily_adaptive(
    daily_series: pd.Series,
    forecast_horizon: int = DEFAULT_FORECAST_HORIZON,
    weather_df: pd.DataFrame = None,
    calendar_df: pd.DataFrame = None,
) -> tuple:
    """
    日总量预测：自适应窗口均值 + 周季节性 + 均值回归 + 可选天气修正。

    参数
    ----
    daily_series : pd.Series
        历史日总量（index=date）。
    forecast_horizon : int
        预测天数。
    weather_df : pd.DataFrame | None
        目标日天气预报 [date, tmax, tmin, humidity_avg, precip_sum, rad_sum]。
    calendar_df : pd.DataFrame | None
        排班日历 [date, day_type, day_type_weight]。

    返回
    ----
    (forecast, lower, upper, info_dict)
    """
    y = daily_series.values.astype(float)
    n = len(y)
    dates = daily_series.index

    dow_idx = np.array([d.dayofweek for d in dates])
    overall_mean = y.mean()

    seasonal = np.zeros(7)
    for d in range(7):
        mask = dow_idx == d
        if mask.sum() > 0:
            seasonal[d] = y[mask].mean() - overall_mean

    deseasoned = y - np.array([seasonal[dow_idx[i]] for i in range(n)])

    windows = [w for w in WEATHER_CORRECTION_WINDOWS if w < n]
    if not windows:
        windows = [DEFAULT_MIN_WINDOW]

    best_window = windows[0]
    best_reg = 0.0
    best_mae = float("inf")

    val_start = min(max(DEFAULT_MIN_WINDOW, n - 30), n - 3)
    if val_start >= n:
        val_start = max(7, n - 14)

    for w in windows:
        for reg in REG_STRENGTHS:
            preds = []
            actuals = []
            for i in range(val_start, n):
                if i - w >= 0:
                    base = deseasoned[max(0, i - w):i].mean()
                    deviation = base - deseasoned.mean()
                    if reg > 0:
                        base = base - deviation * reg
                    pred = base + seasonal[dow_idx[i]]
                    pred = max(pred, 0)
                    preds.append(pred)
                    actuals.append(y[i])
            if len(preds) > 0:
                mae = mean_absolute_error(actuals, preds)
                if mae < best_mae:
                    best_mae = mae
                    best_window = w
                    best_reg = reg

    recent_deseasoned = deseasoned[-best_window:]
    base_forecast = recent_deseasoned.mean()

    all_mean = deseasoned.mean()
    deviation = base_forecast - all_mean
    if best_reg > 0:
        base_forecast = base_forecast - deviation * best_reg

    last_date = dates[-1]
    if hasattr(last_date, "to_pydatetime"):
        last_date = last_date.to_pydatetime()
    forecast_dates = pd.date_range(
        start=pd.Timestamp(last_date) + pd.Timedelta(days=1),
        periods=forecast_horizon, freq="D"
    )

    forecasts = []
    for i in range(forecast_horizon):
        pred_dow = forecast_dates[i].dayofweek
        pred = base_forecast + seasonal[pred_dow]
        pred = max(pred, 0)
        forecasts.append(pred)

    forecast = pd.Series(forecasts, index=forecast_dates, name="daily_pred")

    if calendar_df is not None and not calendar_df.empty:
        forecast = _apply_calendar_correction(forecast, calendar_df)

    if weather_df is not None and not weather_df.empty:
        forecast = _apply_weather_correction(forecast, weather_df, daily_series)

    fitted_deseasoned = np.array([
        deseasoned[max(0, i - best_window):i].mean()
        for i in range(max(1, val_start), n)
    ])
    fitted_seasonal = np.array([seasonal[dow_idx[i]] for i in range(max(1, val_start), n)])
    if len(fitted_deseasoned) > 0:
        residuals = y[-len(fitted_deseasoned):] - (fitted_deseasoned + fitted_seasonal)
        residual_std = float(residuals.std())
    else:
        residual_std = daily_series.std() * 0.3

    lower = pd.Series(
        [max(0, f - 1.28 * residual_std) for f in forecast.values],
        index=forecast.index
    )
    upper = pd.Series(
        [f + 1.28 * residual_std for f in forecast.values],
        index=forecast.index
    )

    return forecast, lower, upper, {
        "best_window": best_window,
        "best_reg": best_reg,
        "seasonal": seasonal,
        "base_forecast": base_forecast,
        "residual_std": residual_std,
        "overall_mean": overall_mean,
        "best_mae_val": best_mae,
    }


def _apply_calendar_correction(
    forecast: pd.Series, calendar_df: pd.DataFrame
) -> pd.Series:
    """根据排班权重修正日总量预测。"""
    cal_map = {}
    for _, row in calendar_df.iterrows():
        d = pd.Timestamp(row["date"])
        cal_map[d.date()] = row.get("day_type_weight", 1.0)

    corrected = forecast.copy()
    for dt in corrected.index:
        key = dt.date() if hasattr(dt, "date") else dt
        weight = cal_map.get(key, 1.0)
        corrected.loc[dt] *= weight

    return corrected


def _apply_weather_correction(
    forecast: pd.Series,
    weather_df: pd.DataFrame,
    historical_daily: pd.Series,
) -> pd.Series:
    """
    天气修正：温度偏离 → 负荷调整。

    修正逻辑（基于历史温度-负荷回归）：
    - 计算历史平均温度与日总量的关系
    - 目标日温度 vs 历史同期平均温度偏差 → 修正负荷
    """
    weather = weather_df.copy()
    weather["date"] = pd.to_datetime(weather["date"])
    weather_map = {}
    for _, row in weather.iterrows():
        d = row["date"]
        weather_map[d.date()] = {
            "tavg": (row.get("tmax", np.nan) + row.get("tmin", np.nan)) / 2
            if not pd.isna(row.get("tmax")) and not pd.isna(row.get("tmin"))
            else np.nan,
            "humidity_avg": row.get("humidity_avg", np.nan),
            "precip_sum": row.get("precip_sum", np.nan),
        }

    historical_mean = historical_daily.mean()

    corrected = forecast.copy()
    for dt in corrected.index:
        key = dt.date() if hasattr(dt, "date") else dt
        wx = weather_map.get(key)
        if wx is None or pd.isna(wx.get("tavg")):
            continue

        tavg = wx["tavg"]
        base_pred = corrected.loc[dt]

        p = WEATHER_CORRECTION_PARAMS
        if tavg > p["hot_temp_threshold"]:
            base_pred *= p["hot_temp_factor"]
        elif tavg < p["cold_temp_threshold"]:
            base_pred *= p["cold_temp_factor"]

        precip = wx.get("precip_sum", 0)
        if not pd.isna(precip) and precip > p["heavy_rain_threshold"]:
            base_pred *= p["heavy_rain_factor"]

        corrected.loc[dt] = base_pred

    return corrected


def build_template_library(df_hourly: pd.DataFrame, calendar_df: pd.DataFrame = None) -> list[dict]:
    """
    构建逐时分配模板库。每一条模板 = {date, daily_total, hourly_profile, day_type}。
    """
    templates = []
    cal_map = {}
    if calendar_df is not None and not calendar_df.empty:
        for _, row in calendar_df.iterrows():
            cal_map[pd.Timestamp(row["date"]).date()] = row.get("day_type", "production")

    for dt, group in df_hourly.groupby("date"):
        daily_total = group["load_mw"].sum()
        hourly = group.set_index("hour")["load_mw"].sort_index().values
        if len(hourly) != 24:
            continue
        profile = hourly / daily_total if daily_total > 0 else np.ones(24) / 24

        dt_date = dt if isinstance(dt, pd.Timestamp) else pd.Timestamp(dt)
        day_type = cal_map.get(dt_date.date(),
            "rest" if dt_date.dayofweek >= 5 else "production")

        templates.append({
            "date": dt_date,
            "daily_total": daily_total,
            "hourly_profile": profile,
            "day_type": day_type,
        })
    return templates


def match_templates(
    templates: list[dict],
    target_daily_total: float,
    target_day_type: str,
    k: int = DEFAULT_KNN_K,
) -> tuple:
    """
    在模板库中匹配 K 个日总量最接近、同 day_type 的历史天。
    """
    same_type = [t for t in templates if t["day_type"] == target_day_type]
    if len(same_type) < 3:
        same_type = [t for t in templates if t["day_type"] != "holiday"]
    if len(same_type) == 0:
        same_type = templates

    sorted_t = sorted(same_type, key=lambda t: abs(t["daily_total"] - target_daily_total))
    top_k = sorted_t[:min(k, len(sorted_t))]

    weights = np.array([
        1.0 / (abs(t["daily_total"] - target_daily_total) + 1e-3) for t in top_k
    ])
    weights = weights / weights.sum()

    profiles = np.array([t["hourly_profile"] for t in top_k])
    weighted_profile = np.average(profiles, axis=0, weights=weights)
    weighted_profile = weighted_profile / weighted_profile.sum()

    matched_dates = [t["date"] for t in top_k]
    return weighted_profile, matched_dates


def generate_hourly_forecast(
    daily_forecast: pd.Series,
    templates: list[dict],
    calendar_df: pd.DataFrame = None,
    weather_df: pd.DataFrame = None,
    k: int = DEFAULT_KNN_K,
) -> list[dict]:
    """
    对每一天的日总量预测，匹配模板生成逐时负荷。
    """
    cal_map = {}
    if calendar_df is not None and not calendar_df.empty:
        for _, row in calendar_df.iterrows():
            d = pd.Timestamp(row["date"])
            cal_map[d.date()] = row.get("day_type", "production")

    rad_map = {}
    if weather_df is not None and not weather_df.empty:
        for _, row in weather_df.iterrows():
            d = pd.Timestamp(row["date"])
            rad_val = row.get("rad_sum", np.nan)
            if not pd.isna(rad_val):
                rad_map[d.date()] = float(rad_val)

    results = []
    for pred_date, daily_total in daily_forecast.items():
        key = pred_date.date() if hasattr(pred_date, "date") else pred_date
        target_day_type = cal_map.get(key, "rest" if pred_date.dayofweek >= 5 else "production")

        profile, matched = match_templates(templates, daily_total, target_day_type, k=k)

        rad = rad_map.get(key)
        if rad is not None and rad > 0:
            profile = _adjust_for_solar(profile, rad)

        matched_data = []
        for t in templates:
            if t["date"] in matched:
                matched_data.append(t["hourly_profile"] * daily_total)
        profile_std = np.std(matched_data, axis=0) if len(matched_data) > 1 else np.zeros(24)

        for h in range(24):
            pred_dt = pd.Timestamp(pred_date) + pd.Timedelta(hours=h)
            results.append({
                "datetime": pred_dt,
                "date": pred_date,
                "hour": h,
                "load_mw": daily_total * profile[h],
                "daily_total_mwh": daily_total,
                "profile_std_mw": float(profile_std[h]),
                "matched_dates": [str(d.date()) for d in matched],
            })

    return results


def _adjust_for_solar(profile: np.ndarray, rad_sum: float) -> np.ndarray:
    """
    辐照修正：高辐照日中午负荷略下调（光伏替代效应）。

    修正幅度与辐射量成正比，最大下调 5%。
    """
    if rad_sum <= 0:
        return profile

    p = WEATHER_CORRECTION_PARAMS
    intensity = min(rad_sum / p["solar_reference_rad"], 1.0)
    solar_reduction = p["solar_max_reduction"] * intensity

    adjusted = profile.copy()
    midday_hours = [11, 12, 13, 14]
    for h in midday_hours:
        if h < len(adjusted):
            adjusted[h] *= (1.0 - solar_reduction * 0.5)
    edge_hours = [10, 15]
    for h in edge_hours:
        if h < len(adjusted):
            adjusted[h] *= (1.0 - solar_reduction * 0.25)

    adjusted = adjusted / adjusted.sum()
    return adjusted


def run_forecast(
    company: str,
    df_hourly: pd.DataFrame,
    forecast_horizon: int = DEFAULT_FORECAST_HORIZON,
    calendar_df: pd.DataFrame = None,
    weather_df: pd.DataFrame = None,
    k: int = DEFAULT_KNN_K,
) -> dict:
    """
    一站式预测入口。

    参数
    ----
    company : str
        公司名（A公司/B公司/C公司）。
    df_hourly : pd.DataFrame
        逐时负荷历史数据（含 datetime, load_mw, company）。
    forecast_horizon : int
        预测天数。
    calendar_df : pd.DataFrame | None
        排班日历。
    weather_df : pd.DataFrame | None
        天气预报逐日数据。
    k : int
        KNN 匹配数。

    返回
    ----
    dict: {
        "daily_forecast": pd.Series,
        "daily_lower": pd.Series,
        "daily_upper": pd.Series,
        "hourly_results": list[dict],
        "info": dict,
    }
    """
    daily_series = prepare_daily_series(df_hourly)

    if daily_series.empty or len(daily_series) < 14:
        return {"error": f"{company} 历史数据不足（需至少14天）"}

    forecast, lower, upper, info = forecast_daily_adaptive(
        daily_series, forecast_horizon, weather_df, calendar_df
    )

    templates = build_template_library(df_hourly, calendar_df)

    hourly = generate_hourly_forecast(
        forecast, templates, calendar_df, weather_df, k=k
    )
    for p in hourly:
        p["company"] = company

    return {
        "daily_forecast": forecast,
        "daily_lower": lower,
        "daily_upper": upper,
        "hourly_results": hourly,
        "info": info,
    }
