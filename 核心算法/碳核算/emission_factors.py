"""EF_opt(t) 时变碳因子构造——节点电价代理法（方法二）。

原理：广东电力现货市场中，高价时段多为火电顶出→碳强度高；
低价时段多为新能源大发/水电→碳强度低。将节点电价归一化后
映射到碳强度区间 [EF_OPT_LOW, EF_OPT_HIGH]，再整体缩放到
年均值等于 EF_REPORT（省级固定因子），保证年度总量与正式报告
口径自洽。标注为“研究用近似值”，仅作调度/减排决策信号。
"""

import math
import numpy as np
import pandas as pd

from config import EF_OPT_LOW, EF_OPT_HIGH, EF_OPT_ANNUAL_TARGET


def price_to_carbon_intensity(price_series: pd.Series) -> pd.Series:
    """逐时节点电价 → 逐时碳强度。

    归一化基于 min-max，再用等比缩放把加权年均校准到 EF_REPORT。
    """
    p = price_series.astype(float)
    if p.notna().sum() == 0 or p.std() == 0:
        raise ValueError("节点电价数据无效（空或恒定），无法构造时变碳因子")

    p_min, p_max = p.min(), p.max()
    norm = (p - p_min) / (p_max - p_min) if p_max > p_min else np.zeros_like(p)
    ef = EF_OPT_LOW + norm * (EF_OPT_HIGH - EF_OPT_LOW)

    # 年均校准：等比缩放因子使均值等于目标因子，保留峰谷形态
    scale = EF_OPT_ANNUAL_TARGET / ef.mean()
    ef_cal = ef * scale
    return ef_cal.round(4)


def ensure_annual_scale(ef: np.ndarray, target: float = EF_OPT_ANNUAL_TARGET) -> np.ndarray:
    """将碳强度序列等比缩放到指定年均值（用于代理曲线与固定因子对齐）。"""
    mean = float(np.mean(ef))
    if mean == 0:
        return ef
    return ef * (target / mean)


def build_ef_opt(price_df: pd.DataFrame, price_col: str = "price",
                 time_col: str = "timestamp") -> pd.DataFrame:
    """从节点电价数据构造逐时碳因子。返回含 timestamp 与 ef_opt 两列。"""
    df = price_df.copy()
    if time_col in df.columns:
        df[time_col] = pd.to_datetime(df[time_col])
    ef = price_to_carbon_intensity(df[price_col])
    out = pd.DataFrame({
        "timestamp": df[time_col] if time_col in df.columns else df.index,
        "ef_opt": ef.values,
    })
    return out


def mock_price_curve(hour: np.ndarray) -> np.ndarray:
    """生成用于测试的近似分时电价代理曲线（元/kWh）。

    广东峰谷特征：低谷 0-8 点价低、高峰 10-12 / 14-19 点价高。
    仅用于无真实电价文件时占位，真实数据到位后以文件为准。
    """
    h = np.asarray(hour, dtype=float)
    base = 0.45
    valley = np.where((h >= 0) & (h <= 8), -0.20, 0.0)
    peak = np.where(((h >= 10) & (h <= 12)) | ((h >= 14) & (h <= 19)), 0.55, 0.0)
    return base + valley + peak
