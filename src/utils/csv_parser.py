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


# ============================================================
# 负荷历史文件解析（宽表 / 长表自适应）
# ============================================================

def parse_load_history_upload(
    file_content: bytes, filename: str
) -> tuple[pd.DataFrame, str | None]:
    """
    解析上传的负荷历史文件，自动检测宽表 / 长表格式，
    统一输出标准化长表 DataFrame [datetime, load_mw, weekday]。

    支持格式：
    - Excel (.xlsx / .xls)：宽表 [日期 + 24列逐时负荷（如 0时、1时...）]
    - CSV 宽表：日期列 + 24列逐时负荷
    - CSV 长表：datetime 列 + load_mw 列

    返回
    ----
    (df, error_msg) : 成功时 error_msg 为 None。
    """
    import io

    is_excel = filename.lower().endswith((".xlsx", ".xls"))

    # ---- 读取 ----
    if is_excel:
        try:
            xl = pd.ExcelFile(io.BytesIO(file_content))
            sheet_name = xl.sheet_names[0]
            df_raw = xl.parse(sheet_name)
        except Exception as e:
            return pd.DataFrame(), f"Excel 解析失败: {e}"
    else:
        text = None
        for enc in ["utf-8", "gbk", "gb2312", "latin-1"]:
            try:
                text = file_content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return pd.DataFrame(), "无法识别文件编码，请使用 UTF-8 或 GBK 编码"
        try:
            df_raw = pd.read_csv(io.StringIO(text))
        except Exception as e:
            return pd.DataFrame(), f"CSV 解析失败: {e}"

    if df_raw.empty:
        return pd.DataFrame(), "文件为空或无可读取的数据"

    # ---- 检测格式 ----
    fmt, date_col, hour_cols = _detect_load_format(df_raw)

    if fmt == "long":
        return _parse_long_format(df_raw)
    elif fmt == "wide":
        return _parse_wide_format(df_raw, date_col, hour_cols)
    else:
        return pd.DataFrame(), (
            "无法识别数据格式。\n"
            "支持格式：\n"
            "  宽表: 日期列 + 24列逐时负荷（如 0时、1时...23时）\n"
            "  长表: datetime列 + load_mw列\n"
            f"当前列名: {list(df_raw.columns)[:10]}..."
        )


def _detect_load_format(df: pd.DataFrame) -> tuple[str, str | None, list[str] | None]:
    """
    检测数据格式：'long'、'wide' 或 'unknown'。
    返回 (format, date_column, hour_columns)。
    """
    cols = list(df.columns)

    # 检测长表：有 datetime-like 列 + load/mw 列
    datetime_patterns = ["datetime", "date_time", "time", "时间", "ds", "dt"]
    has_dt_col = any(
        any(p == c.lower().strip() for p in datetime_patterns) for c in cols
    )

    load_patterns = ["load", "mw", "负荷", "功率", "电力"]
    has_load_col = any(
        any(p in c.lower().strip() for p in load_patterns) for c in cols
    )

    if has_dt_col and has_load_col:
        return ("long", None, None)

    # 检测宽表：小时列名可能为 '0时'、'1时'、'0'、'1'、'0h'、'1h' 等
    hour_cols = []
    for c in cols:
        c_str = str(c).strip()
        # 匹配 "0时", "1时", ..., "23时"
        match_shi = re.match(r"^(\d{1,2})时$", c_str)
        if match_shi:
            hour_cols.append(c)
            continue
        # 匹配纯数字 "0" ~ "23"
        match_num = re.match(r"^(\d{1,2})$", c_str)
        if match_num and 0 <= int(match_num.group(1)) <= 23:
            hour_cols.append(c)
            continue
        # 匹配 "0h", "1h", ..., "23h"
        match_h = re.match(r"^(\d{1,2})[hH]$", c_str)
        if match_h:
            hour_cols.append(c)
            continue

    if len(hour_cols) >= 4:
        # 扫描所有列找日期列（不假设第一列就是日期）
        date_col = _find_date_column(df, cols)
        if date_col is None:
            date_col = cols[0]
        return ("wide", date_col, hour_cols)

    # 兜底：有日期列 + 有很多数值列 → 可能是宽表
    date_col = _find_date_column(df, list(df.columns))
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if date_col and len(numeric_cols) >= 4:
        # 过滤：排除汇总列（合计、总计、sum、total 等）
        summary_patterns = ["合计", "总计", "sum", "total", "平均", "avg"]
        filtered = [
            c for c in numeric_cols
            if not any(p in str(c).lower() for p in summary_patterns)
        ]
        return ("wide", date_col, filtered if len(filtered) >= 4 else numeric_cols)

    return ("unknown", None, None)


def _is_date_column(df: pd.DataFrame, col: str) -> bool:
    """检测列是否为日期格式。"""
    try:
        vals = df[col].dropna().head(5)
        if len(vals) == 0:
            return False
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
            try:
                converted = pd.to_datetime(vals, format=fmt)
                if converted.notna().all():
                    return True
            except Exception:
                continue
        # 自动推断
        converted = pd.to_datetime(vals, infer_datetime_format=True)
        return converted.notna().all()
    except Exception:
        return False


def _find_date_column(df: pd.DataFrame, cols: list[str]) -> str | None:
    """扫描所有列，返回第一个可解析为日期的列名。"""
    # 优先匹配常见日期列名
    date_names = ["日期", "date", "datetime", "时间", "time", "ds", "dt"]
    for c in cols:
        c_lower = str(c).lower().strip()
        for name in date_names:
            if name in c_lower:
                if _is_date_column(df, c):
                    return c

    # 扫描所有列
    for c in cols:
        if c not in df.columns:
            continue
        # 跳过明显不是日期的列（数值列、小时列等）
        c_str = str(c).strip()
        if re.match(r"^\d{1,2}[时hH]?$", c_str):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            continue
        if _is_date_column(df, c):
            return c

    return None


def _parse_long_format(df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    """解析长表格式。"""
    result = pd.DataFrame()

    time_col = _detect_datetime_column(df)
    if time_col is None:
        return pd.DataFrame(), "未检测到时间列"

    result["datetime"] = _parse_datetime_column(df[time_col])

    load_col = _detect_load_column(df)
    if load_col is None:
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        load_col = numeric_cols[0] if numeric_cols else None

    if load_col is None:
        return pd.DataFrame(), "未检测到负荷列"

    result["load_mw"] = pd.to_numeric(df[load_col], errors="coerce")
    result["weekday"] = result["datetime"].dt.day_name()
    result = result.dropna(subset=["datetime", "load_mw"])

    return result, None


def _parse_wide_format(
    df: pd.DataFrame, date_col: str, hour_cols: list[str]
) -> tuple[pd.DataFrame, str | None]:
    """
    宽表 → 长表转换。
    输入: 日期列 + N 列逐时负荷
    输出: [datetime, load_mw, weekday]
    """
    df = df.copy()

    # 解析日期
    date_series = _parse_datetime_column(df[date_col])
    df["_date"] = date_series.dt.date

    # 确保 hour_cols 中所有列都存在
    hour_cols = [c for c in hour_cols if c in df.columns]
    if not hour_cols:
        return pd.DataFrame(), "未找到逐时负荷列"

    # 宽→长
    melted = df.melt(
        id_vars=["_date"],
        value_vars=hour_cols,
        var_name="_hour",
        value_name="load_mw",
    )

    # 小时列 → 整数（处理 "0时" → 0, "1h" → 1, "0" → 0 等）
    def _parse_hour(val):
        s = str(val).strip()
        # "0时" / "1时"
        m = re.match(r"^(\d{1,2})时$", s)
        if m:
            return int(m.group(1))
        # "0h" / "1H"
        m = re.match(r"^(\d{1,2})[hH]$", s)
        if m:
            return int(m.group(1))
        # "0" ~ "23"
        try:
            return int(s)
        except ValueError:
            return None

    melted["_hour"] = melted["_hour"].apply(_parse_hour)
    melted = melted.dropna(subset=["_hour"])
    melted["_hour"] = melted["_hour"].astype(int)

    # 组合 datetime
    melted["datetime"] = pd.to_datetime(
        melted["_date"].astype(str) + " " + melted["_hour"].astype(str) + ":00:00"
    )

    melted["load_mw"] = pd.to_numeric(melted["load_mw"], errors="coerce")
    melted["weekday"] = melted["datetime"].dt.day_name()
    melted = melted.dropna(subset=["datetime", "load_mw"])
    melted = melted.sort_values("datetime")

    result = melted[["datetime", "load_mw", "weekday"]].reset_index(drop=True)
    return result, None
