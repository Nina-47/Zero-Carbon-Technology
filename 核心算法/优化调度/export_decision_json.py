# -*- coding: utf-8 -*-
"""
导出调度建议为 JSON，供静态 HTML 调度建议页读取渲染。

用法：python export_decision_json.py [目标日下标] [输出json路径]
默认：目标日最后一天，输出到脚本同目录 dispatch.json（与 dispatch.html 同目录）
"""

import sys
import os
import json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from decision_engine import run_daily_decision


def export(target_day_idx=-1, out_path=None):
    result = run_daily_decision(target_day_idx=target_day_idx, k=5, use_load_forecast=False)
    if "error" in result:
        print("导出失败:", result["error"])
        return

    res = result["res"]
    hourly = result["hourly"]
    summary = result["summary"]

    # 储能减碳统计项（res 里已算好，透传出去给前端展示储能真实价值）
    metrics = {
        "储能充电总量_kWh": round(res.get("chg_kwh", 0)),
        "储能放电总量_kWh": round(res.get("dis_kwh", 0)),
        "充自光伏_kWh": round(res.get("chg_pv_kwh", 0)),
        "放电替代购电_kWh": round(res.get("dis_replace_kwh", 0)),
        "净购电_kWh": round(res.get("net_grid_kwh", 0)),
        "余电上网_kWh": round(res.get("export_kwh", 0)),
    }

    # 组装前端需要的结构
    payload = {
        "summary": summary,
        "metrics": metrics,
        "hourly": hourly,
        # 便于 ECharts 直接用的数值数组
        "series": {
            "hours": [h["小时"] for h in hourly],
            "load": [h["预测负荷_kW"] for h in hourly],
            "pv": [h["预测光伏_kW"] for h in hourly],
            "grid_buy": [h["购电_kW"] for h in hourly],
            "flex_use": [round(v) for v in res["flex"]],
            "pbat": [round(p) for p in res["pbat"]],
            "flex_down": [h["曝气下调_kW"] for h in hourly],
            "soc": [h["SOC"] for h in hourly],
            "battery_action": [h["储能动作"] for h in hourly],
            "pv_action": [h["光伏去向"] for h in hourly],
        },
    }

    if out_path is None:
        # 默认生成"自包含 HTML"：把 JSON 内嵌进 dispatch.html 模板，双击即可打开，无需 HTTP 服务
        script_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(script_dir, "dispatch.html")
        out_path = os.path.join(script_dir, "dispatch_final.html")
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
        final_html = template.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(final_html)
        print(f"已生成自包含 HTML: {out_path}（双击即可打开，无需服务）")
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"已导出调度建议 JSON: {out_path}")
    return out_path


if __name__ == "__main__":
    target_idx = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    out = sys.argv[2] if len(sys.argv) > 2 else None
    export(target_idx, out)
