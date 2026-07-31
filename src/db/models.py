"""
SQLite 数据持久化：建表、CRUD、用户设置
"""

import sqlite3
import os
import pandas as pd
from config import EXPORT_PARAMS

DB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
DB_PATH = os.path.join(DB_DIR, "weather.db")


def get_connection() -> sqlite3.Connection:
    """获取 SQLite 连接（WAL 模式，避免锁冲突）。"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表结构（幂等）。"""
    conn = get_connection()
    cursor = conn.cursor()

    # 天气数据表
    columns_def = [
        "id INTEGER PRIMARY KEY AUTOINCREMENT",
        "location_id TEXT NOT NULL",
        "datetime TEXT NOT NULL",
        "data_type TEXT NOT NULL",
        "source TEXT NOT NULL DEFAULT 'openmeteo'",
    ]
    for param in EXPORT_PARAMS:
        columns_def.append(f"{param} REAL")

    columns_def.append("fetched_at TEXT NOT NULL DEFAULT (datetime('now'))")

    create_weather_sql = f"""
    CREATE TABLE IF NOT EXISTS weather_hourly (
        {', '.join(columns_def)},
        UNIQUE(location_id, datetime, data_type)
    )
    """
    cursor.execute(create_weather_sql)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_weather_loc_time "
        "ON weather_hourly(location_id, datetime)"
    )

    # 地点元数据表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS location_meta (
        location_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        latitude REAL,
        longitude REAL,
        is_aggregate INTEGER DEFAULT 0,
        parent_ids TEXT
    )
    """)

    # 用户设置表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)

    # 初始化默认设置（不存在时插入）
    defaults = {
        "default_history_days": "7",
        "auto_refresh": "true",
    }
    for k, v in defaults.items():
        cursor.execute(
            "INSERT OR IGNORE INTO user_settings (key, value) VALUES (?, ?)",
            (k, v),
        )

    conn.commit()
    conn.close()


def insert_weather_data(df: pd.DataFrame) -> int:
    """
    批量插入/替换天气数据（逐行 INSERT OR REPLACE，兼容 Python 3.14）。

    返回
    ----
    int : 插入的行数。
    """
    if df.empty:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    # 只保留数据库表中存在的列
    db_columns = ["location_id", "datetime", "data_type", "source"] + list(EXPORT_PARAMS.keys())
    available_cols = [c for c in db_columns if c in df.columns]
    insert_df = df[available_cols].copy()

    # datetime 转字符串
    if "datetime" in insert_df.columns and pd.api.types.is_datetime64_any_dtype(insert_df["datetime"]):
        insert_df["datetime"] = insert_df["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    col_names = ", ".join(available_cols)
    placeholders = ", ".join(["?"] * len(available_cols))

    sql = f"INSERT OR REPLACE INTO weather_hourly ({col_names}) VALUES ({placeholders})"

    inserted = 0
    for _, row in insert_df.iterrows():
        values = []
        for col in available_cols:
            val = row[col]
            # NaN → None (SQLite NULL)
            try:
                if pd.isna(val):
                    val = None
            except (TypeError, ValueError):
                pass
            values.append(val)
        try:
            cursor.execute(sql, tuple(values))
            inserted += 1
        except Exception:
            pass  # 跳过单行插入失败，不影响整体

    conn.commit()
    conn.close()
    return inserted


def query_weather_data(
    location_ids: list[str],
    start_dt: str,
    end_dt: str,
    data_types: list[str] | None = None,
) -> pd.DataFrame:
    """
    查询天气数据。

    参数
    ----
    location_ids : list[str]
        地点 ID 列表。
    start_dt, end_dt : str
        时间范围 ISO 8601。
    data_types : list[str] | None
        'historical' / 'forecast' / None（全部）。

    返回
    ----
    pd.DataFrame
    """
    conn = get_connection()
    cols = ["location_id", "datetime", "data_type", "source"] + list(EXPORT_PARAMS.keys())

    placeholders_loc = ", ".join(["?"] * len(location_ids))
    sql = f"""
    SELECT {', '.join(cols)}
    FROM weather_hourly
    WHERE location_id IN ({placeholders_loc})
      AND datetime >= ? AND datetime <= ?
    """

    params = [*location_ids, start_dt, end_dt]

    if data_types:
        placeholders_type = ", ".join(["?"] * len(data_types))
        sql += f" AND data_type IN ({placeholders_type})"
        params.extend(data_types)

    sql += " ORDER BY datetime ASC"

    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()

    if not df.empty:
        df["datetime"] = pd.to_datetime(df["datetime"])

    return df


def get_last_fetch_time(location_id: str, data_type: str) -> str | None:
    """获取指定地点和数据类型的最后更新时间。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT MAX(fetched_at) FROM weather_hourly WHERE location_id=? AND data_type=?",
        (location_id, data_type),
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def get_setting(key: str, default: str = "") -> str:
    """读取用户设置。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM user_settings WHERE key=?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default


def save_setting(key: str, value: str):
    """保存用户设置。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()
    conn.close()


def clean_old_forecasts(days: int = 7):
    """清理超过指定天数的过期预报数据。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM weather_hourly WHERE data_type='forecast' "
        "AND datetime < datetime('now', ?)",
        (f"-{days} days",),
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted
