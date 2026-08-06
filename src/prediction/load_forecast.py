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
    连续天气修正：用历史数据拟合温度-负荷曲线，计算连续修正系数。

    - 高温段 (>28°C)：负荷随温度上升而增加（制冷负荷）
    - 常温段 (10-28°C)：基本不修正（舒适区）
    - 低温段 (<10°C)：负荷随温度下降而增加（取暖负荷）
    - 降水：对数衰减，降水量越大负荷越低
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
            "precip_sum": row.get("precip_sum", np.nan),
        }

    if historical_daily is None or len(historical_daily) < 30:
        return forecast

    overall_mean = historical_daily.mean()
    temp_load_curve = _fit_temp_load_curve(historical_daily, weather_df)

    corrected = forecast.copy()
    for dt in corrected.index:
        key = dt.date() if hasattr(dt, "date") else dt
        wx = weather_map.get(key)
        if wx is None or pd.isna(wx.get("tavg")):
            continue

        tavg = wx["tavg"]
        base_pred = corrected.loc[dt]

        if temp_load_curve is not None:
            temp_factor = _interp_temp_factor(tavg, temp_load_curve)
            base_pred *= temp_factor

        precip = wx.get("precip_sum", 0)
        if not pd.isna(precip) and precip > 0:
            base_pred *= 1.0 - 0.02 * np.log2(1 + precip)

        corrected.loc[dt] = base_pred

    return corrected


def _fit_temp_load_curve(daily_series: pd.Series, weather_df: pd.DataFrame) -> list | None:
    hist_weather = weather_df.copy()
    hist_weather["date"] = pd.to_datetime(hist_weather["date"]).dt.date
    wx_dates = set(hist_weather["date"])

    bins = []
    for d in daily_series.index:
        d_key = d.date() if hasattr(d, "date") else d
        if d_key in wx_dates:
            row = hist_weather[hist_weather["date"] == d_key].iloc[0]
            tavg = (row.get("tmax", np.nan) + row.get("tmin", np.nan)) / 2
            if not pd.isna(tavg):
                bins.append((tavg, daily_series[d]))

    if len(bins) < 30:
        return None

    bins.sort(key=lambda x: x[0])
    overall_mean = daily_series.mean()

    curve = []
    step = 2
    for lo in range(-10, 46, step):
        hi = lo + step
        vals = [v for t, v in bins if lo <= t < hi]
        if len(vals) >= 3:
            ratio = np.mean(vals) / overall_mean if overall_mean > 0 else 1.0
            ratio = max(0.85, min(ratio, 1.15))
        else:
            ratio = 1.0
        curve.append(((lo + hi) / 2, ratio))

    return curve


def _interp_temp_factor(tavg: float, curve: list) -> float:
    temps = np.array([c[0] for c in curve])
    ratios = np.array([c[1] for c in curve])
    return float(np.interp(tavg, temps, ratios))


def detect_and_fix_outliers(df_hourly: pd.DataFrame) -> pd.DataFrame:
    """
    IQR 异常值检测与修复。

    按小时分组，同一时刻的负荷值用 IQR 方法检测异常：
    - 异常阈值：Q1 - 1.5×IQR 和 Q3 + 1.5×IQR
    - 异常小时用该时刻前后 2 小时的中位数替换
    - 返回修复后的 DataFrame，新增 _outlier 列标记异常点
    """
    df = df_hourly.copy()
    df["_outlier"] = False

    hourly_groups = df.groupby("hour")["load_mw"]

    for hour, group in hourly_groups:
        vals = group.values
        q1, q3 = np.percentile(vals, [25, 75])
        iqr = q3 - q1
        if iqr < 1e-6:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr

        idxs = group.index
        for idx in idxs:
            if df.loc[idx, "load_mw"] < lo or df.loc[idx, "load_mw"] > hi:
                df.loc[idx, "_outlier"] = True

    outlier_idx = df[df["_outlier"]].index
    for idx in outlier_idx:
        neighbors = []
        for offset in [-24, -12, 12, 24]:
            ni = idx + offset
            if 0 <= ni < len(df):
                neighbors.append(df.loc[ni, "load_mw"])
        if neighbors:
            df.loc[idx, "load_mw"] = np.median(neighbors)

    return df


def _get_anomaly_dates(df_hourly: pd.DataFrame) -> set:
    """返回异常小时超过 6 个的日期集合（从模板库排除）。"""
    if "_outlier" not in df_hourly.columns:
        return set()
    anomaly_counts = df_hourly.groupby("date")["_outlier"].sum()
    return set(anomaly_counts[anomaly_counts > 6].index)


def build_template_library(
    df_hourly: pd.DataFrame,
    calendar_df: pd.DataFrame = None,
    weather_df: pd.DataFrame = None,
    anomaly_dates: set = None,
) -> list[dict]:
    """
    构建逐时分配模板库。每一条模板 = {date, daily_total, hourly_profile, day_type, avg_temp}。
    """
    templates = []
    cal_map = {}
    if calendar_df is not None and not calendar_df.empty:
        for _, row in calendar_df.iterrows():
            cal_map[pd.Timestamp(row["date"]).date()] = row.get("day_type", "production")

    temp_map = {}
    if weather_df is not None and not weather_df.empty:
        wx = weather_df.copy()
        if "date" in wx.columns:
            wx["date"] = pd.to_datetime(wx["date"]).dt.date
        for _, row in wx.iterrows():
            d = row["date"]
            tavg = None
            if not pd.isna(row.get("tmax")) and not pd.isna(row.get("tmin")):
                tavg = (row["tmax"] + row["tmin"]) / 2
            elif "temperature_2m" in wx.columns:
                tavg = row.get("temperature_2m")
            temp_map[d] = tavg

    if anomaly_dates is None:
        anomaly_dates = set()

    for dt, group in df_hourly.groupby("date"):
        dt_date = dt if isinstance(dt, pd.Timestamp) else pd.Timestamp(dt)
        if dt_date.date() in anomaly_dates:
            continue
        daily_total = group["load_mw"].sum()
        hourly = group.set_index("hour")["load_mw"].sort_index().values
        if len(hourly) != 24:
            continue
        profile = hourly / daily_total if daily_total > 0 else np.ones(24) / 24

        day_type = cal_map.get(dt_date.date(),
            "rest" if dt_date.dayofweek >= 5 else "production")

        templates.append({
            "date": dt_date,
            "daily_total": daily_total,
            "hourly_profile": profile,
            "day_type": day_type,
            "avg_temp": temp_map.get(dt_date.date()),
        })
    return templates


def match_templates(
    templates: list[dict],
    target_daily_total: float,
    target_day_type: str,
    k: int = DEFAULT_KNN_K,
    target_avg_temp: float = None,
) -> tuple:
    """
    综合距离 KNN 模板匹配：

    综合距离 = 日总量距离(50%) + 温度相似度(30%) + 星期类型(20%)
    """
    same_type = [t for t in templates if t["day_type"] == target_day_type]
    if len(same_type) < 3:
        same_type = [t for t in templates if t["day_type"] != "holiday"]
    if len(same_type) == 0:
        same_type = templates

    totals = np.array([t["daily_total"] for t in same_type])
    mean_total = totals.mean() if len(totals) > 0 else target_daily_total + 1e-6
    if mean_total < 1e-6:
        mean_total = target_daily_total + 1e-6

    temps = np.array([t["avg_temp"] for t in same_type if t["avg_temp"] is not None])
    temp_std = temps.std() if len(temps) > 1 else 5.0
    if temp_std < 1e-6:
        temp_std = 5.0

    def composite_distance(t):
        d_total = abs(t["daily_total"] - target_daily_total) / mean_total
        if target_avg_temp is not None and t["avg_temp"] is not None:
            d_temp = abs(t["avg_temp"] - target_avg_temp) / temp_std
        else:
            d_temp = 0
        d_dow = 0 if t["day_type"] == target_day_type else 1
        return 0.5 * d_total + 0.3 * d_temp + 0.2 * d_dow

    sorted_t = sorted(same_type, key=composite_distance)
    top_k = sorted_t[:min(k, len(sorted_t))]

    weights = np.array([1.0 / (composite_distance(t) + 0.01) for t in top_k])
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
    temp_map = {}
    if weather_df is not None and not weather_df.empty:
        for _, row in weather_df.iterrows():
            d = pd.Timestamp(row["date"])
            rad_val = row.get("rad_sum", np.nan)
            if not pd.isna(rad_val):
                rad_map[d.date()] = float(rad_val)
            tmax_val = row.get("tmax", np.nan)
            tmin_val = row.get("tmin", np.nan)
            if not pd.isna(tmax_val) and not pd.isna(tmin_val):
                temp_map[d.date()] = (float(tmax_val) + float(tmin_val)) / 2

    results = []
    for pred_date, daily_total in daily_forecast.items():
        key = pred_date.date() if hasattr(pred_date, "date") else pred_date
        target_day_type = cal_map.get(key, "rest" if pred_date.dayofweek >= 5 else "production")
        target_temp = temp_map.get(key)

        profile, matched = match_templates(
            templates, daily_total, target_day_type, k=k, target_avg_temp=target_temp
        )

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

    df_clean = detect_and_fix_outliers(df_hourly)
    anomaly_dates = _get_anomaly_dates(df_clean)
    n_outliers = df_clean["_outlier"].sum()
    outlier_info = {
        "n_outlier_hours": int(n_outliers),
        "n_anomaly_dates": len(anomaly_dates),
    }

    forecast, lower, upper, info = forecast_daily_adaptive(
        daily_series, forecast_horizon, weather_df, calendar_df
    )
    info.update(outlier_info)

    templates = build_template_library(df_clean, calendar_df, weather_df, anomaly_dates)

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
