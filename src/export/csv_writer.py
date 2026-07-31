"""
CSV 宽表导出
"""

import pandas as pd
from io import BytesIO
from config import EXPORT_PARAMS


def export_csv(
    df: pd.DataFrame,
    selected_columns: list[str] | None = None,
    include_location: bool = True,
) -> bytes:
    """
    将天气数据导出为 CSV 宽表格式。

    参数
    ----
    df : pd.DataFrame
        天气数据。
    selected_columns : list[str] | None
        用户选择的导出列，None 表示全部。
    include_location : bool
        是否包含 location 列。

    返回
    ----
    bytes : CSV 文件内容（UTF-8 BOM）。
    """
    if df.empty:
        return b""

    export_df = df.copy()

    # 确定导出列
    meta_cols = ["location_id", "datetime"]
    if include_location:
        base_cols = [c for c in meta_cols if c in export_df.columns]
    else:
        base_cols = ["datetime"] if "datetime" in export_df.columns else []

    if selected_columns:
        param_cols = [c for c in selected_columns if c in export_df.columns and c not in base_cols]
    else:
        param_cols = [c for c in EXPORT_PARAMS.keys() if c in export_df.columns]

    export_cols = base_cols + param_cols
    export_df = export_df[export_cols]

    # 格式化 datetime
    if "datetime" in export_df.columns:
        export_df["datetime"] = export_df["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    # 输出为 UTF-8 BOM（Excel 中文兼容）
    buffer = BytesIO()
    buffer.write(b"\xef\xbb\xbf")  # UTF-8 BOM
    export_df.to_csv(buffer, index=False, encoding="utf-8")
    return buffer.getvalue()


def export_csv_download(df: pd.DataFrame, filename: str = "weather_data.csv") -> bytes:
    """便捷方法：导出全量数据。"""
    return export_csv(df)
