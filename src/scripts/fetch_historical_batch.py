"""
批量拉取历史天气数据脚本。

从 Open-Meteo Archive API 拉取 2025-04 ~ 2026-08 所有城市的逐小时历史天气，
写入 SQLite，供负荷预测模型训练和校验使用。

用法:
    python -m src.scripts.fetch_historical_batch
    python -m src.scripts.fetch_historical_batch --dry-run

特性:
    - 幂等：INSERT OR REPLACE，重复运行不产生重复数据
    - 断点续传：跳过已完整月份
    - 容错：单批失败不中断全局，记录到 data/fetch_failures.jsonl
"""

import sys
import os
import json
import time
import calendar
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from config import LOCATIONS
from src.api.fallback import fetch_historical_safe, DataSourceStatus
from src.db.models import insert_weather_data, get_connection

ERA5_DELAY_DAYS = 5
BATCH_DELAY_SECONDS = 2
COMPLETENESS_THRESHOLD = 0.95


def _iter_physical_locations():
    """遍历所有物理地点（排除聚合地点）。"""
    locs = []
    for loc_id, loc_cfg in LOCATIONS.items():
        if loc_cfg.get("is_aggregate"):
            for child_id, child_cfg in loc_cfg.get("child_cities", {}).items():
                locs.append((child_id, child_cfg["display_name"], child_cfg["latitude"], child_cfg["longitude"]))
        else:
            locs.append((loc_id, loc_cfg["display_name"], loc_cfg["latitude"], loc_cfg["longitude"]))
    return locs


def _iter_months(start_year, start_month, end_year, end_month):
    """生成月份范围的 (year, month) 迭代器。"""
    yr, mo = start_year, start_month
    while (yr, mo) <= (end_year, end_month):
        yield yr, mo
        mo += 1
        if mo > 12:
            mo = 1
            yr += 1


def _month_boundaries(year, month, max_end):
    dt = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end_dt = min(date(year, month, last_day), max_end)
    return dt.isoformat(), end_dt.isoformat(), end_dt.day


def _expected_hours(year, month):
    """某月的预期小时数。"""
    ndays = calendar.monthrange(year, month)[1]
    return ndays * 24


def _count_existing(location_id, start_date, end_date):
    """查询数据库中已有数据行数。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM weather_hourly "
        "WHERE location_id = ? AND datetime >= ? AND datetime <= ? AND data_type = 'historical'",
        (location_id, start_date + "T00:00:00", end_date + "T23:59:59"),
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count


def main():
    dry_run = "--dry-run" in sys.argv

    locations = _iter_physical_locations()
    today = date.today()
    max_end_date = today - timedelta(days=ERA5_DELAY_DAYS)

    print(f"ERA5-Land 截止日期: {max_end_date.isoformat()}")
    print(f"地点数: {len(locations)}, 月份范围: 2025-04 ~ 2026-08")

    if dry_run:
        print("[DRY RUN] 不实际拉取数据\n")

    total = 0
    succeeded = 0
    skipped = 0
    failed = 0
    failures = []

    for yr, mo in _iter_months(2025, 4, 2026, 8):
        start_str, end_str, actual_days = _month_boundaries(yr, mo, max_end_date)
        expected = actual_days * 24

        if actual_days == 0:
            print(f"[跳过] {yr}-{mo:02d}: 全部为未来日期（ERA5-Land 尚未覆盖）")
            continue

        for loc_id, display_name, lat, lon in locations:
            total += 1
            batch_label = f"[{total:3d}] {display_name} {yr}-{mo:02d}"

            existing = _count_existing(loc_id, start_str, end_str)
            if existing >= int(expected * COMPLETENESS_THRESHOLD):
                print(f"{batch_label}: 跳过（已有 {existing}/{expected} 条）")
                skipped += 1
                continue

            if dry_run:
                print(f"{batch_label}: [DRY RUN]")
                succeeded += 1
                continue

            try:
                status = DataSourceStatus()
                df = fetch_historical_safe(lat, lon, loc_id, start_str, end_str, status=status)
                if df is None or df.empty:
                    raise ValueError(f"API 返回空数据（源状态: {status.status_text}）")

                n = insert_weather_data(df)
                src_label = "备用源" if status.fallback_used else "OK"
                print(f"{batch_label}: {n} 行 ({src_label})")

                if abs(n - expected) > 4:
                    print(f"  ⚠ 预期 {expected} 行，实际 {n} 行")

                succeeded += 1
            except Exception as e:
                print(f"{batch_label}: 失败 - {e}")
                failed += 1
                failures.append({
                    "location_id": loc_id,
                    "display_name": display_name,
                    "start_date": start_str,
                    "end_date": end_str,
                    "error": str(e),
                    "attempted_at": datetime.now().isoformat(),
                })

            time.sleep(BATCH_DELAY_SECONDS)

    _print_summary(total, succeeded, skipped, failed, failures)
    if failures:
        _save_failures(failures)


def _print_summary(total, succeeded, skipped, failed, failures):
    print(f"\n{'='*60}")
    print(f"总计: {total} 批 | 成功: {succeeded} | 跳过: {skipped} | 失败: {failed}")
    if failures:
        print(f"失败批次已记录到 data/fetch_failures.jsonl")
        print("重新运行本脚本可自动补拉失败批次。")
    print(f"{'='*60}")


def _save_failures(failures):
    os.makedirs("data", exist_ok=True)
    path = os.path.join("data", "fetch_failures.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        for item in failures:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
