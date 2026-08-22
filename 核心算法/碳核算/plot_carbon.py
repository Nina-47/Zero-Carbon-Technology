# -*- coding: utf-8 -*-
"""
碳核算结果可视化：排放结构 + 减排成果。

读 04_预测输出/V3_碳核算/carbon_results.json，输出两张图到 图表/ 子文件夹：
  图1 碳排放结构.png —— 企业年度排放（范围一工艺 vs 范围二电力）
  图2 光储年减排.png —— 运行减排 vs 净减排（扣储能隐含碳）

配色取自 dataviz 验证过的分类色（CVD 色盲安全）：
  范围一（工艺）= 橙 #eb6834，范围二（电力）= 蓝 #2a78d6，减排 = 绿系。

用法：python plot_carbon.py
"""

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---- 中文字体 ----
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 150
plt.rcParams["savefig.dpi"] = 150
plt.rcParams["savefig.bbox"] = "tight"

# ---- 路径 ----
BASE = os.path.dirname(os.path.abspath(__file__))            # 碳核算/
CODE_DIR = os.path.dirname(BASE)                             # 03_预测代码/
PROJECT = os.path.dirname(CODE_DIR)                          # 项目根
V3_DIR = os.path.join(PROJECT, "04_预测输出", "V3_碳核算")
JSON_PATH = os.path.join(V3_DIR, "carbon_results.json")
CHART_DIR = os.path.join(V3_DIR, "图表")

# ---- 配色（dataviz 分类色，light 模式）----
C_SCOPE1 = "#eb6834"   # 橙 —— 范围一 工艺
C_SCOPE2 = "#2a78d6"   # 蓝 —— 范围二 电力
C_ER = "#1baf7a"       # aqua —— 运行减排
C_ER_NET = "#008300"   # green —— 净减排
INK = "#52514e"        # 次级文字
MUTED = "#898781"      # 轴线/刻度


def main():
    with open(JSON_PATH, encoding="utf-8") as f:
        r = json.load(f)["results"]

    scope1_t = r["scope1"]["scope1_kg"] / 1e3        # 范围一 t
    scope2_t = r["scope2"]["scope2_kg"] / 1e3        # 范围二 t
    total_t = r["total_plant_kg"] / 1e3              # 总排放 t
    er_t = r["project"]["ER_t"]                      # 运行减排 t
    er_net_t = r["lca"]["er_net_yearly_kg"] / 1e3    # 净减排 t（扣隐含碳）
    embodied_annual_t = r["lca"]["embodied_annual_kg"] / 1e3  # 隐含碳年分摊 t

    os.makedirs(CHART_DIR, exist_ok=True)

    # ============================================================
    # 图1：年度排放结构（环形图）
    # ============================================================
    fig, ax = plt.subplots(figsize=(7, 6))
    sizes = [scope2_t, scope1_t]
    colors = [C_SCOPE2, C_SCOPE1]
    pct2 = scope2_t / total_t * 100
    pct1 = scope1_t / total_t * 100

    wedges, _ = ax.pie(
        sizes, colors=colors, startangle=90, counterclock=False,
        wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
    )
    # 中心标注总排放
    ax.text(0, 0, f"总排放\n{total_t:,.0f} t", ha="center", va="center",
            fontsize=15, fontweight="bold", color="#0b0b0b")
    ax.text(0, -0.32, "CO2e / 年", ha="center", va="center",
            fontsize=9, color=INK)

    # 图例（带占比）
    ax.legend(
        wedges,
        [f"范围二 电力  {scope2_t:,.0f} t（{pct2:.1f}%）",
         f"范围一 工艺  {scope1_t:,.0f} t（{pct1:.1f}%）"],
        loc="center left", bbox_to_anchor=(0.98, 0.5), fontsize=10, frameon=False,
    )
    ax.set_title("企业年度排放结构", fontsize=14, fontweight="bold", pad=16)
    fig.savefig(os.path.join(CHART_DIR, "碳排放结构.png"))
    plt.close(fig)
    print(f"图1 碳排放结构.png 已保存（范围二 {scope2_t:,.0f} t / 范围一 {scope1_t:,.0f} t）")

    # ============================================================
    # 图2：光储年减排（柱状图）
    # ============================================================
    fig, ax = plt.subplots(figsize=(7, 6))
    bars = [er_t, er_net_t]
    labels = ["运行减排\nER", "净减排\n（扣隐含碳）"]
    bar_colors = [C_ER, C_ER_NET]

    x = np.arange(len(bars))
    rects = ax.bar(x, bars, width=0.5, color=bar_colors,
                   edgecolor="white", linewidth=1)
    for rect, v in zip(rects, bars):
        ax.text(rect.get_x() + rect.get_width() / 2, v + er_t * 0.02,
                f"{v:,.0f} t", ha="center", va="bottom", fontsize=12, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("吨 CO2e / 年", fontsize=11)
    ax.set_ylim(0, er_t * 1.25)
    ax.set_title("光储系统年减排", fontsize=14, fontweight="bold", pad=16)

    # 隐含碳占比注释
    share = embodied_annual_t / er_t * 100
    ax.text(0.5, -0.18, f"储能隐含碳年分摊仅 {embodied_annual_t:,.0f} t，"
            f"占运行减排 {share:.0f}%，几乎不影响减排结论",
            ha="center", va="top", transform=ax.transAxes, fontsize=9, color=INK)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="both", colors=MUTED)
    ax.yaxis.grid(True, alpha=0.25, color="#e1e0d9")
    ax.set_axisbelow(True)

    fig.savefig(os.path.join(CHART_DIR, "光储年减排.png"))
    plt.close(fig)
    print(f"图2 光储年减排.png 已保存（运行减排 {er_t:,.0f} t / 净减排 {er_net_t:,.0f} t）")


if __name__ == "__main__":
    main()
