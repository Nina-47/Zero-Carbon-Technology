"""
SQLite 数据持久化：建表、CRUD、用户设置
"""

import sqlite3
import os
import pandas as pd
from config import EXPORT_PARAMS

# 数据库路径：优先源码 data/ 目录（本地）；若不可写（Streamlit Cloud 只读挂载），
# 回退到可写的临时目录，避免 PRAGMA journal_mode=WAL 因无法创建 wal 文件而 OperationalError。
_SRC_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_SRC_DB_PATH = os.path.join(_SRC_DB_DIR, "weather.db")


def _pick_writable_db_dir():
    """返回一个可写的数据库目录。"""
    # 优先尝试源码 data 目录
    try:
        os.makedirs(_SRC_DB_DIR, exist_ok=True)
        _probe = os.path.join(_SRC_DB_DIR, ".write_probe")
        with open(_probe, "w") as f:
            f.write("x")
        os.remove(_probe)
        return _SRC_DB_DIR
    except Exception:
        pass
    # 回退到环境变量 TMPDIR / /tmp / 当前目录
    for _cand in (os.environ.get("TMPDIR"), "/tmp", os.getcwd()):
        if _cand:
            try:
                os.makedirs(_cand, exist_ok=True)
                _probe = os.path.join(_cand, ".write_probe")
                with open(_probe, "w") as f:
                    f.write("x")
                os.remove(_probe)
                return _cand
            except Exception:
                continue
    return _SRC_DB_DIR


DB_DIR = _pick_writable_db_dir()
DB_PATH = os.path.join(DB_DIR, "weather.db")


def get_connection() -> sqlite3.Connection:
    """获取 SQLite 连接（WAL 模式，优化写入性能）。"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
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

    init_load_table()
    init_calendar_table()


def insert_weather_data(df: pd.DataFrame) -> int:
    """
    批量插入/替换天气数据（executemany 批量写入，兼容 Python 3.14）。

    返回
    ----
    int : 插入的行数。
    """
    if df.empty:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    db_columns = ["location_id", "datetime", "data_type", "source"] + list(EXPORT_PARAMS.keys())
    available_cols = [c for c in db_columns if c in df.columns]
    insert_df = df[available_cols].copy()

    if "datetime" in insert_df.columns and pd.api.types.is_datetime64_any_dtype(insert_df["datetime"]):
        insert_df["datetime"] = insert_df["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    col_names = ", ".join(available_cols)
    placeholders = ", ".join(["?"] * len(available_cols))
    sql = f"INSERT OR REPLACE INTO weather_hourly ({col_names}) VALUES ({placeholders})"

    rows = []
    for _, row in insert_df.iterrows():
        values = []
        for col in available_cols:
            val = row[col]
            try:
                if pd.isna(val):
                    val = None
            except (TypeError, ValueError):
                pass
            values.append(val)
        rows.append(tuple(values))

    cursor.executemany(sql, rows)
    inserted = cursor.rowcount

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
        try:
            df["datetime"] = pd.to_datetime(df["datetime"], format="mixed")
        except Exception:
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
            df = df.dropna(subset=["datetime"])
        # 统一去掉时区信息，避免 tz-aware vs tz-naive 排序冲突
        if df["datetime"].dt.tz is not None:
            df["datetime"] = df["datetime"].dt.tz_localize(None)

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


# ============================================================
# 负荷历史数据表
# ============================================================

def init_load_table():
    """初始化负荷历史表（逐小时长格式）。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS load_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        datetime TEXT NOT NULL,
        load_mw REAL NOT NULL,
        weekday TEXT,
        daily_total REAL,
        company TEXT,
        source_file TEXT,
        imported_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(datetime, company)
    )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_load_datetime ON load_history(datetime)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_load_company ON load_history(company)"
    )

    # 兼容旧表：如果缺少 company 列就添加
    try:
        cursor.execute("SELECT company FROM load_history LIMIT 1")
    except Exception:
        cursor.execute("ALTER TABLE load_history ADD COLUMN company TEXT")

    conn.commit()
    conn.close()


def import_load_from_df(df: pd.DataFrame, source_file: str = "", company: str = "") -> int:
    """
    批量导入负荷数据（executemany 批量写入）。

    返回: 插入的行数。
    """
    if df.empty:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    df = df.copy()
    if "datetime" in df.columns and pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    if "weekday" not in df.columns:
        df["weekday"] = pd.to_datetime(df["datetime"]).dt.day_name()
    if "daily_total" not in df.columns:
        df_date = pd.to_datetime(df["datetime"]).dt.date
        daily_totals = df.groupby(df_date)["load_mw"].transform("sum")
        df["daily_total"] = daily_totals

    if "company" not in df.columns and company:
        df["company"] = company

    rows = []
    for _, row in df.iterrows():
        load_val = row.get("load_mw", None)
        daily_val = row.get("daily_total", None)
        rows.append((
            str(row["datetime"]),
            float(load_val) if load_val is not None and not pd.isna(load_val) else None,
            str(row.get("weekday", "")),
            float(daily_val) if daily_val is not None and not pd.isna(daily_val) else None,
            str(row.get("company", company)),
            source_file,
        ))

    cursor.executemany(
        "INSERT OR REPLACE INTO load_history "
        "(datetime, load_mw, weekday, daily_total, company, source_file) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )

    inserted = cursor.rowcount
    conn.commit()
    conn.close()
    return inserted


def get_load_by_date(date_str: str, company: str = None) -> pd.DataFrame:
    """获取指定日期完整的 24 小时负荷曲线。"""
    conn = get_connection()
    if company:
        df = pd.read_sql_query(
            "SELECT datetime, load_mw, weekday, daily_total, company "
            "FROM load_history WHERE date(datetime) = ? AND company = ? "
            "ORDER BY datetime ASC",
            conn, params=(date_str, company),
        )
    else:
        df = pd.read_sql_query(
            "SELECT datetime, load_mw, weekday, daily_total, company "
            "FROM load_history WHERE date(datetime) = ? "
            "ORDER BY datetime ASC",
            conn, params=(date_str,),
        )
    conn.close()
    if not df.empty:
        try:
            df["datetime"] = pd.to_datetime(df["datetime"], format="mixed")
        except Exception:
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
            df = df.dropna(subset=["datetime"])
        if df["datetime"].dt.tz is not None:
            df["datetime"] = df["datetime"].dt.tz_localize(None)
    return df


def query_load_date_range(company: str = None) -> tuple[str | None, str | None]:
    """获取负荷数据的可用日期范围。"""
    conn = get_connection()
    cursor = conn.cursor()
    if company:
        cursor.execute(
            "SELECT MIN(date(datetime)), MAX(date(datetime)) FROM load_history WHERE company = ?",
            (company,),
        )
    else:
        cursor.execute(
            "SELECT MIN(date(datetime)), MAX(date(datetime)) FROM load_history"
        )
    row = cursor.fetchone()
    conn.close()
    return (row[0], row[1]) if row else (None, None)


def has_load_data(company: str = None) -> bool:
    """检查是否已有负荷数据。"""
    conn = get_connection()
    cursor = conn.cursor()
    if company:
        cursor.execute("SELECT COUNT(*) FROM load_history WHERE company = ?", (company,))
    else:
        cursor.execute("SELECT COUNT(*) FROM load_history")
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


def delete_load_data(company: str = None):
    """清空负荷历史数据。"""
    conn = get_connection()
    cursor = conn.cursor()
    if company:
        cursor.execute("DELETE FROM load_history WHERE company = ?", (company,))
    else:
        cursor.execute("DELETE FROM load_history")
    conn.commit()
    conn.close()


def query_load_all(company: str = None) -> pd.DataFrame:
    """获取全部负荷历史数据（用于预测）。"""
    conn = get_connection()
    if company:
        df = pd.read_sql_query(
            "SELECT datetime, load_mw, weekday, daily_total, company "
            "FROM load_history WHERE company = ? ORDER BY datetime ASC",
            conn, params=(company,),
        )
    else:
        df = pd.read_sql_query(
            "SELECT datetime, load_mw, weekday, daily_total, company "
            "FROM load_history ORDER BY datetime ASC",
            conn,
        )
    conn.close()
    if not df.empty:
        df["datetime"] = pd.to_datetime(df["datetime"], format="mixed", errors="coerce")
        if df["datetime"].dt.tz is not None:
            df["datetime"] = df["datetime"].dt.tz_localize(None)
    return df


def get_load_companies() -> list[str]:
    """获取已导入的负荷数据公司列表。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT company FROM load_history WHERE company IS NOT NULL AND company != ''")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


# ============================================================
# 排班日历表
# ============================================================

def init_calendar_table():
    """初始化排班日历表。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS production_calendar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company TEXT NOT NULL,
        date TEXT NOT NULL,
        day_type TEXT NOT NULL DEFAULT 'production',
        day_type_weight REAL DEFAULT 1.0,
        source TEXT DEFAULT 'weekly_rule',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(company, date)
    )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_calendar_company_date "
        "ON production_calendar(company, date)"
    )
    conn.commit()
    conn.close()


def import_calendar_from_df(df: pd.DataFrame, company: str, source: str = "upload") -> int:
    """批量导入排班日历数据。"""
    if df.empty:
        return 0
    conn = get_connection()
    cursor = conn.cursor()

    rows = []
    for _, row in df.iterrows():
        rows.append((
            company,
            str(row["date"]),
            str(row.get("day_type", "production")),
            float(row.get("day_type_weight", 1.0)),
            source,
        ))

    cursor.executemany(
        "INSERT OR REPLACE INTO production_calendar "
        "(company, date, day_type, day_type_weight, source) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )

    inserted = cursor.rowcount
    conn.commit()
    conn.close()
    return inserted


def get_calendar(company: str) -> pd.DataFrame:
    """获取指定公司的排班日历。"""
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT date, day_type, day_type_weight, source "
        "FROM production_calendar WHERE company = ? ORDER BY date ASC",
        conn, params=(company,),
    )
    conn.close()
    return df


def delete_calendar(company: str = None):
    """清空排班日历。"""
    conn = get_connection()
    cursor = conn.cursor()
    if company:
        cursor.execute("DELETE FROM production_calendar WHERE company = ?", (company,))
    else:
        cursor.execute("DELETE FROM production_calendar")
    conn.commit()
    conn.close()
