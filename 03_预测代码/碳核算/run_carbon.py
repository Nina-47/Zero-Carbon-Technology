"""模块三碳核算——主入口。

用法：
  python run_carbon.py                 # 读取模块二真实负荷+光伏，跑全年
  python run_carbon.py --mock          # 无真实文件时用占位数据自测
  python run_carbon.py --out out.json  # 指定结果输出路径
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from carbon_accounting import CarbonAccounting, mock_hourly_df
import data_loader


def to_tonnes(results: dict) -> dict:
    """把 kg 口径的结果统一换算为 tCO2e 展示层。"""
    return results


def run_real() -> dict:
    # 用模块二的真实储能调度曲线（最优低充高放）
    df = data_loader.build_schedule_from_module2()
    from emission_factors import price_to_carbon_intensity

    # 用逐时联动电价（中长期90%+现货10%）构造 EF_opt(t)，与调度省电费同源
    linked = data_loader.load_linked_price(df)
    ef_opt = price_to_carbon_intensity(linked)

    acct = CarbonAccounting(df, ef_opt=ef_opt)
    return acct.run_all()


def run_mock() -> dict:
    df = mock_hourly_df()
    acct = CarbonAccounting(df)
    return acct.run_all()


def summarize(r: dict) -> None:
    s1, s2 = r["scope1"], r["scope2"]
    pr, lc = r["project"], r["lca"]
    total = r["total_plant_kg"]
    print("=" * 56)
    print("模块三碳核算结果汇总（单位：吨 CO2e，范围一/二为 CO2）")
    print("=" * 56)
    print(f"[企业清单账] 厂区年度总排放       = {total * 1e-3:,.1f} t")
    print(f"  范围一 工艺过程(CH4+N2O)      = {s1['scope1_kg'] * 1e-3:,.1f} t")
    print(f"    其中 CH4   = {s1['ch4_co2e_kg'] * 1e-3:,.2f} t")
    print(f"    其中 N2O   = {s1['n2o_co2e_kg'] * 1e-3:,.2f} t")
    print(f"  范围二 外购电力               = {s2['scope2_kg'] * 1e-3:,.1f} t  "
          f"(购电 {s2['e_grid_kwh']/1e4:,.1f} 万kWh × {s2['ef_report']})")
    print("-" * 56)
    print(f"[项目减排账] 运行减排 ER = BE - PE - LE")
    print(f"  基准排放 BE   = {pr['BE_kg'] * 1e-3:,.1f} t")
    print(f"  项目排放 PE   = {pr['PE_kg'] * 1e-3:,.1f} t")
    print(f"  泄漏排放 LE   = {pr['LE_kg'] * 1e-3:,.2f} t")
    print(f"  运行减排 ER   = {pr['ER_t']:,.1f} t")
    print("-" * 56)
    print(f"[LCA账] 储能设备隐含碳")
    print(f"  隐含碳总量(扣回收) = {lc['embodied_net_kg'] * 1e-3:,.1f} t")
    print(f"  年分摊隐含碳        = {lc['embodied_annual_kg'] * 1e-3:,.1f} t")
    print(f"  净生命周期年减排    = {lc['er_net_yearly_kg'] * 1e-3:,.1f} t")
    print(f"  寿命可放电量        = {lc['e_life_kwh']/1e4:,.1f} 万kWh (寿命 {lc['life_years']:.0f}年)")
    print("=" * 56)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="用占位数据自测")
    ap.add_argument("--out", type=str, default=None, help="结果JSON输出路径")
    args = ap.parse_args()

    r = run_mock() if args.mock else run_real()
    summarize(r)

    if args.out:
        out_path = args.out
    else:
        out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "carbon_results.json")

    payload = {
        "metadata": {
            "module": "模块三-碳核算",
            "ef_report": 0.4419,
            "scope": "三账分离",
        },
        "results": r,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
