"""
JSON 结构化导出
"""

import json
import pandas as pd
from datetime import datetime
from config import EXPORT_PARAMS, TIMEZONE


def export_json(
    df: pd.DataFrame,
    location_id: str = "",
    selected_columns: list[str] | None = None,
) -> str:
    """
    将天气数据导出为结构化 JSON。

    参数
    ----
    df : pd.DataFrame
        天气数据。
    location_id : str
        地点标识。
    selected_columns : list[str] | None
        用户选择的导出列，None 表示全部。

    返回
    ----
    str : JSON 字符串。
    """
    if df.empty:
        return json.dumps({"error": "no data"}, ensure_ascii=False)

    export_df = df.copy()

    if "datetime" in export_df.columns:
        export_df["datetime"] = export_df["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    if selected_columns:
        cols = ["datetime"] + [c for c in selected_columns if c in export_df.columns and c != "datetime"]
    else:
        cols = [c for c in export_df.columns if c != "location_id"]

    cols = [c for c in cols if c in export_df.columns]
    export_df = export_df[cols]

    result = {
        "location": location_id,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "record_count": len(export_df),
        "columns": {c: EXPORT_PARAMS.get(c, {}).get("cn", c) for c in cols if c != "datetime"},
        "data": export_df.to_dict(orient="records"),
    }

    return json.dumps(result, ensure_ascii=False, indent=2)


def export_json_download(df: pd.DataFrame, location_id: str = "") -> bytes:
    """便捷方法：导出 JSON 为 bytes。"""
    json_str = export_json(df, location_id)
    return json_str.encode("utf-8")
