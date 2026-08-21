# -*- coding: utf-8 -*-
"""
日/月/年粒度结果 → 月度趋势图（调度 + 碳核算）。

读 granular_report 生成的 JSON，画月度趋势图，按版本铁律放：
  - 调度图 → 04_预测输出/V4_优化调度/图表/
  - 碳核算图 → 04_预测输出/V3_碳核算/图表/

用法：python plot_granular.py
"""

import io
import os
import sys
import json

import matplotlib
matplotlib.use("Agg")   # 无界面后端，直接存文件
import matplotlib.pyplot as plt

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# 中文字体
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

# ---- 路径 ----
BASE = os.path.dirname(os.path.abspath(__file__))          # 主流程/
CODE_DIR = os.path.dirname(BASE)                            # 03_预测代码/
PROJECT = os.path.dirname(CODE_DIR)
DISPATCH_OUT = os.path.join(PROJECT, "04_预测输出", "V4_优化调度")
CARBON_OUT = os.path.join(PROJECT, "04_预测输出", "V3_碳核算")
DISPATCH_CHART = os.path.join(DISPATCH_OUT, "图表")
CARBON_CHART = os.path.join(CARBON_OUT, "图表")
os.makedirs(DISPATCH_CHART, exist_ok=True)
os.makedirs(CARBON_CHART, exist_ok=True)

# ---- 读数据 ----
with open(os.path.join(DISPATCH_OUT, "调度_粒度报告.json"), encoding="utf-8") as f:
    dm = json.load(f)["dispatch"]["monthly"]
with open(os.path.join(CARBON_OUT, "碳核算_粒度报告.json"), encoding="utf-8") as f:
    cm = json.load(f)["carbon"]["monthly"]

# 分类色（固定顺序，不随系列增减重涂）
C_LOAD, C_PV, C_BUY = "#4C72B0", "#55A868", "#C44E52"
C_CHG, C_DIS = "#DD8452", "#8172B2"
C_S1, C_S2 = "#C44E52", "#4C72B0"
C_ER = "#55A868"


def style_ax(ax, months, x):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(months, rotation=45, ha="right", fontsize=8)


# ============================================================
# 调度图（3 张）
# ============================================================
dmonths = [m["month"] for m in dm]
dx = range(len(dmonths))
w = 0.26

# 1. 月度用电 / 购电 / 光伏
fig, ax = plt.subplots(figsize=(11, 5))
ax.bar([i - w for i in dx], [m["load_kWh"] / 1e4 for m in dm], w, label="用电量", color=C_LOAD)
ax.bar(dx, [m["buy_kWh"] / 1e4 for m in dm], w, label="购电量", color=C_BUY)
ax.bar([i + w for i in dx], [m["pv_kWh"] / 1e4 for m in dm], w, label="光伏发电", color=C_PV)
ax.set_ylabel("万 kWh")
ax.set_title("A 公司月度用电 / 购电 / 光伏")
ax.legend(ncol=3, fontsize=9)
style_ax(ax, dmonths, dx)
fig.tight_layout()
fig.savefig(os.path.join(DISPATCH_CHART, "调度_月度用电购电光伏.png"), dpi=150)
plt.close(fig)

# 2. 月度储能充放电
fig, ax = plt.subplots(figsize=(11, 5))
ax.bar([i - w / 2 for i in dx], [m["chg_kWh"] / 1e4 for m in dm], w, label="储能充电", color=C_CHG)
ax.bar([i + w / 2 for i in dx], [m["dis_kWh"] / 1e4 for m in dm], w, label="储能放电", color=C_DIS)
ax.set_ylabel("万 kWh")
ax.set_title("A 公司月度储能充放电")
ax.legend(ncol=2, fontsize=9)
style_ax(ax, dmonths, dx)
fig.tight_layout()
fig.savefig(os.path.join(DISPATCH_CHART, "调度_月度储能充放电.png"), dpi=150)
plt.close(fig)

# 3. 月度绿电占比（折线）
fig, ax = plt.subplots(figsize=(11, 5))
gr = [m["green_ratio_pct"] for m in dm]
ax.plot(dx, gr, marker="o", color=C_PV, linewidth=2)
for i, v in enumerate(gr):
    ax.annotate(f"{v:.1f}", (i, v), textcoords="offset points", xytext=(0, 6),
                ha="center", fontsize=8)
ax.set_ylabel("绿电占比 (%)")
ax.set_title("A 公司月度绿电占比（光伏自用 / 总用电）")
ax.set_ylim(0, max(gr) * 1.3)
style_ax(ax, dmonths, dx)
fig.tight_layout()
fig.savefig(os.path.join(DISPATCH_CHART, "调度_月度绿电占比.png"), dpi=150)
plt.close(fig)

# ============================================================
# 碳核算图（2 张）
# ============================================================
cmonths = [m["month"] for m in cm]
cx = range(len(cmonths))

# 4. 月度范围一 + 范围二（堆叠柱）
fig, ax = plt.subplots(figsize=(11, 5))
s1 = [m["scope1_t"] for m in cm]
s2 = [m["scope2_t"] for m in cm]
ax.bar(cx, s1, label="范围一（工艺）", color=C_S1)
ax.bar(cx, s2, bottom=s1, label="范围二（购电）", color=C_S2)
ax.set_ylabel("tCO2e")
ax.set_title("A 公司月度碳排放（范围一 + 范围二）")
ax.legend(ncol=2, fontsize=9)
style_ax(ax, cmonths, cx)
fig.tight_layout()
fig.savefig(os.path.join(CARBON_CHART, "碳核算_月度范围一二排放.png"), dpi=150)
plt.close(fig)

# 5. 月度减排量
fig, ax = plt.subplots(figsize=(11, 5))
er = [m["ER_t"] for m in cm]
bars = ax.bar(cx, er, color=C_ER, label="减排量")
for b, v in zip(bars, er):
    ax.annotate(f"{v:.0f}", (b.get_x() + b.get_width() / 2, v),
                textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8)
ax.set_ylabel("tCO2e")
ax.set_title("A 公司月度减排量（储能削峰填谷）")
ax.legend(fontsize=9)
style_ax(ax, cmonths, cx)
fig.tight_layout()
fig.savefig(os.path.join(CARBON_CHART, "碳核算_月度减排量.png"), dpi=150)
plt.close(fig)

print("调度图 →", DISPATCH_CHART)
print("碳核算图 →", CARBON_CHART)
