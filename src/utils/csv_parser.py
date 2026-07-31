"""
负荷 CSV 解析器：编码检测、时间格式识别、列名模糊匹配
"""

import pandas as pd
import re
from io import StringIO


# 用于识别负荷列的模糊关键词
LOAD_KEYWORDS = ["load", "mw", "负荷", "功率", "电力"]


def parse_load_csv(file_content: bytes, filename: str = "") -> tuple[pd.DataFrame, str | None]:
    """
    解析上传的负荷 CSV 文件。

    参数
    ----
    file_content : bytes
        文件原始字节。
    filename : str
        文件名（用于日志）。

    返回
    ----
    (df, error_msg) : DataFrame 与错误信息（成功时 error_msg 为 None）。
    """
    # 尝试 UTF-8，失败则尝试 GBK
    text = None
    encoding = None
    for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            text = file_content.decode(enc)
            encoding = enc
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        return pd.DataFrame(), "无法识别文件编码，请使用 UTF-8 或 GBK 编码"

    # 尝试读取 CSV
    try:
        df = pd.read_csv(StringIO(text))
    except Exception as e:
        return pd.DataFrame(), f"CSV 解析失败: {e}"

    if df.empty:
        return pd.DataFrame(), "文件为空或无可读取的数据"

    # 识别时间列
    time_col = _detect_datetime_column(df)
    if time_col is None:
        return pd.DataFrame(), (
            "未检测到时间列。支持的列名: datetime, time, 时间, date, timestamp。\n"
            f"当前列名: {list(df.columns)}"
        )

    # 解析时间列
    df["_datetime"] = _parse_datetime_column(df[time_col])
    if df["_datetime"].isna().all():
        return pd.DataFrame(), (
            f"无法解析时间列 '{time_col}' 的值。\n"
            "支持的格式: 2026-07-31T14:00, 2026-07-31 14:00, 2026/07/31 14:00\n"
            f"样本值: {df[time_col].head(3).tolist()}"
        )

    # 识别负荷列
    load_col = _detect_load_column(df)
    if load_col is None:
        return pd.DataFrame(), None  # 未检测到但不报错，留给用户手动选择

    # 构建标准输出
    result = pd.DataFrame()
    result["datetime"] = df["_datetime"]
    result["load_mw"] = pd.to_numeric(df[load_col], errors="coerce")

    # 保留原始元信息
    result.attrs["original_columns"] = list(df.columns)
    result.attrs["time_column"] = time_col
    result.attrs["load_column"] = load_col
    result.attrs["encoding"] = encoding

    return result, None


def _detect_datetime_column(df: pd.DataFrame) -> str | None:
    """检测时间列。"""
    datetime_patterns = [
        r"^date.*time$", r"^datetime$", r"^time$",
        r"^时间$", r"^日期$", r"^date$", r"^timestamp$",
        r"^ds$", r"^dt$",
    ]
    for col in df.columns:
        col_lower = col.lower().strip()
        for pattern in datetime_patterns:
            if re.match(pattern, col_lower):
                return col
    # 如果没有匹配，检查第一列的列名是否带有时间含义
    if df.columns[0].lower() in ["时间", "date", "datetime", "time"]:
        return df.columns[0]
    # 最后尝试第一列
    return df.columns[0]


def _detect_load_column(df: pd.DataFrame) -> str | None:
    """检测负荷列（模糊匹配）。"""
    for col in df.columns:
        col_lower = col.lower().strip()
        for keyword in LOAD_KEYWORDS:
            if keyword in col_lower:
                return col
    return None


def _parse_datetime_column(series: pd.Series) -> pd.Series:
    """尝试多种格式解析时间列。"""
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M",
    ]

    for fmt in formats:
        try:
            result = pd.to_datetime(series, format=fmt)
            if result.notna().sum() > len(series) * 0.5:
                return result
        except (ValueError, TypeError):
            continue

    # 最后尝试自动推断
    try:
        return pd.to_datetime(series, infer_datetime_format=True)
    except Exception:
        return pd.to_datetime(series, errors="coerce")


def list_load_columns(df: pd.DataFrame) -> list[str]:
    """返回可选的负荷候选列名（供手动映射）。"""
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    # 排除已识别的时间列
    return [c for c in numeric_cols if c not in ("_datetime",)]
