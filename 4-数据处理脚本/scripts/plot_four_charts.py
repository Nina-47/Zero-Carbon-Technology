# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Noto Sans SC']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.size'] = 11

# dataviz 验证配色
BLUE   = '#2a78d6'
ORANGE = '#eb6834'
AQUA   = '#1baf7a'
YELLOW = '#eda100'
MAGENTA= '#e87ba4'
VIOLET = '#4a3aa7'
RED    = '#e34948'
GRAY   = '#898781'
INK    = '#0b0b0b'
GRID   = '#e1e0d9'

OUT = '4-数据处理脚本/图输出'
df  = pd.read_excel('5-过程分析数据/合并数据集_负荷×天气.xlsx')
pv  = pd.read_excel('5-过程分析数据/光伏数据部分.xlsx')
wt  = pd.read_excel('5-过程分析数据/全要素天气表.xlsx')

hours = np.arange(24)

# ============ 图1：逐时负荷曲线（叠加工作/周末，含 inset 放大） ============
wd = df[df['是否周末'] == 0]
we = df[df['是否周末'] == 1]
avg_all = np.array([df[f'负荷_{h}h'].mean() for h in range(24)])
avg_wd  = np.array([wd[f'负荷_{h}h'].mean() for h in range(24)])
avg_we  = np.array([we[f'负荷_{h}h'].mean() for h in range(24)])
std_all = np.array([df[f'负荷_{h}h'].std() for h in range(24)])

fig, ax = plt.subplots(figsize=(9.5, 5.5))
ax.fill_between(hours, avg_all - std_all, avg_all + std_all,
                color=BLUE, alpha=0.12, label='±1 标准差')
ax.plot(hours, avg_wd, color=ORANGE, lw=2, marker='o', ms=3.5, label='工作日（283天）')
ax.plot(hours, avg_we, color=AQUA, lw=2, marker='s', ms=3.5, label='周末（112天）')
annot = [(4, '凌晨低谷\n~19 kW'), (7, '上午小高峰\n~25 kW'), (19, '下午主高峰\n~30 kW')]
for h, txt in annot:
    ax.annotate(txt, xy=(h, avg_all[h]), xytext=(h, avg_all[h] + 3.5),
                ha='center', fontsize=9, color=INK,
                arrowprops=dict(arrowstyle='->', color=GRAY, lw=1))
ax.set_xlabel('小时 (h)', fontsize=12)
ax.set_ylabel('负荷 (kW)', fontsize=12)
ax.set_title('污水厂逐时负荷曲线：工作日 vs 周末', fontsize=14, fontweight='bold')
ax.set_xticks(range(0, 24, 2))
ax.grid(True, linestyle='--', alpha=0.4, color=GRID)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.legend(frameon=False, loc='upper left')

# inset 放大 6-10h 差异（上午小高峰区）
axins = ax.inset_axes([0.55, 0.55, 0.4, 0.35])
axins.plot(hours, avg_wd, color=ORANGE, lw=2, marker='o', ms=3)
axins.plot(hours, avg_we, color=AQUA, lw=2, marker='s', ms=3)
axins.set_xlim(5.5, 10.5)
axins.set_ylim(21.5, 26.5)
axins.set_title('6–10h 局部放大', fontsize=8)
axins.tick_params(labelsize=7)
axins.grid(True, linestyle='--', alpha=0.4, color=GRID)
axins.spines['top'].set_visible(False)
axins.spines['right'].set_visible(False)
ax.indicate_inset_zoom(axins, edgecolor=GRAY)
fig.tight_layout()
fig.savefig(f'{OUT}/图1_逐时负荷曲线.png', dpi=300, bbox_inches='tight')
fig.savefig(f'{OUT}/图1_逐时负荷曲线.svg', bbox_inches='tight')
plt.close(fig)

# ============ 图2：逐时气温-负荷相关（U型，不变，重出） ============
corr_h = np.array([df[f'负荷_{h}h'].corr(df[f'气温_{h}h']) for h in range(24)])
fig, ax = plt.subplots(figsize=(9, 5))
ax.plot(hours, corr_h, color=ORANGE, lw=2.5, marker='s', ms=4, label='逐时相关系数 r')
ax.axhline(0, color=GRAY, lw=1, ls='--')
ax.axvspan(0, 5, color=BLUE, alpha=0.06)
ax.axvspan(22, 24, color=BLUE, alpha=0.06)
ax.axvspan(10, 15, color=YELLOW, alpha=0.10)
ax.text(2, 0.72, '夜间高相关\nr≈0.65', ha='center', fontsize=9, color=BLUE)
ax.text(12.5, 0.30, '午间低相关\nr≈0.40', ha='center', fontsize=9, color='#c98500')
ax.set_xlabel('小时 (h)', fontsize=12)
ax.set_ylabel('气温-负荷相关系数 r', fontsize=12)
ax.set_title('逐时气温-负荷相关性呈 U 型分布', fontsize=14, fontweight='bold')
ax.set_xticks(range(0, 24, 2))
ax.set_ylim(0.2, 0.8)
ax.grid(True, linestyle='--', alpha=0.4, color=GRID)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.legend(frameon=False, loc='upper right')
fig.tight_layout()
fig.savefig(f'{OUT}/图2_气温负荷相关性U型.png', dpi=300, bbox_inches='tight')
fig.savefig(f'{OUT}/图2_气温负荷相关性U型.svg', bbox_inches='tight')
plt.close(fig)

# ============ 图3：光伏-辐射关系（真实辐射数据） ============
rad = wt[wt['要素'] == '太阳总辐射(MJ/m²)'].copy()
hcols = [c for c in rad.columns if c not in ['日期', '要素']]
rad['日总辐射'] = rad[hcols].sum(axis=1)
rad = rad[['日期', '日总辐射']].copy()
rad['日期'] = pd.to_datetime(rad['日期'])
pv['日期'] = pd.to_datetime(pv['对应时间'])
pv = pv[['日期', '总发电量(kWh)']].copy()
m = pd.merge(pv, rad, on='日期', how='inner')
m = m[m['总发电量(kWh)'] > 0]

x = m['日总辐射'].values
y = m['总发电量(kWh)'].values
k_val, b_val = np.polyfit(x, y, 1)
r_val = np.corrcoef(x, y)[0, 1]
ss_res = np.sum((y - (k_val*x + b_val))**2)
ss_tot = np.sum((y - y.mean())**2)
r2_val = 1 - ss_res/ss_tot

fig, ax = plt.subplots(figsize=(8.5, 5.5))
ax.scatter(x, y, s=20, color=BLUE, alpha=0.55, edgecolors='none', label='逐日观测（n=360）')
x_fit = np.linspace(x.min(), x.max(), 100)
ax.plot(x_fit, k_val*x_fit + b_val, color=RED, lw=2.2,
        label=f'线性拟合 y={k_val:.1f}x{b_val:+.0f}')
ax.text(0.03, 0.95,
        f'Pearson r = {r_val:.3f}（极强相关）\nR² = {r2_val:.3f}（解释 71% 发电方差）\n斜率 {k_val:.1f} kWh/单位辐射',
        transform=ax.transAxes, va='top', fontsize=10,
        bbox=dict(boxstyle='round,pad=0.4', fc='#fcfcfb', ec=GRID, alpha=0.9))
ax.set_xlabel('日总辐射 (MJ/m²)', fontsize=12)
ax.set_ylabel('日发电量 (kWh)', fontsize=12)
ax.set_title('日总辐射与光伏发电量关系（真实辐射数据）', fontsize=13, fontweight='bold')
ax.grid(True, linestyle='--', alpha=0.4, color=GRID)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.legend(frameon=False, loc='lower right')
fig.tight_layout()
fig.savefig(f'{OUT}/图3_光伏辐射关系.png', dpi=300, bbox_inches='tight')
fig.savefig(f'{OUT}/图3_光伏辐射关系.svg', bbox_inches='tight')
plt.close(fig)

# ============ 图4：模型精度对比（MAPE 柱状） ============
# 四个模型均有真实 MAPE（相似日基线已实测）
models = ['相似日\n(基线)', 'Holt-Winters\n+KNN (V2)', 'LightGBM\n(V3主力)', 'BiLSTM+Attention\n(修复中)']
mape_val = [10.72, 9.08, 4.22, 43.0]
notes = ['无参数下界', '已验证，午间偏差', '当前主力，已超验收', '归一化修复中']
x = np.arange(len(models))
bar_colors = [GRAY, ORANGE, BLUE, RED]

fig, ax = plt.subplots(figsize=(8, 5.5))
bars = ax.bar(x, mape_val, width=0.55, color=bar_colors, alpha=0.85, edgecolor='none')
for i, (v, note) in enumerate(zip(mape_val, notes)):
    ax.text(i, v + 1.5, f'{v:.1f}%', ha='center', fontsize=12, fontweight='bold',
            color=INK if v < 15 else RED)
    ax.text(i, v + 4.5, note, ha='center', fontsize=8.5, color=GRAY)

ax.axhline(15, color=RED, lw=1.5, ls='--')
ax.text(3.42, 16.5, '验收线 MAPE < 15%', fontsize=9, color=RED, ha='right')

ax.set_xticks(x)
ax.set_xticklabels(models, fontsize=10)
ax.set_ylabel('MAPE (%)', fontsize=12)
ax.set_title('模型精度对比（MAPE，越低越好）', fontsize=14, fontweight='bold')
ax.set_ylim(0, 48)
ax.grid(True, axis='y', linestyle='--', alpha=0.4, color=GRID)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)

# 图注
fig.text(0.5, -0.02,
         '相似日基线为无参数方法，其 MAPE=10.72% 为实测值（2026-04 测试集，KNN=3）；与 LightGBM 相比精度提升明显。',
         ha='center', fontsize=8.5, color=GRAY)
fig.text(0.5, -0.06,
         'LightGBM R² = 0.933（决定系数，越接近 1 越好）',
         ha='center', fontsize=8.5, color=VIOLET)

fig.tight_layout()
fig.savefig(f'{OUT}/图4_模型精度对比.png', dpi=300, bbox_inches='tight')
fig.savefig(f'{OUT}/图4_模型精度对比.svg', bbox_inches='tight')
plt.close(fig)

print('4 张增强版图片已重新生成')
print('图3 真实数据拟合: r=%.4f, R2=%.4f, y=%.1fx %+.0f' % (r_val, r2_val, k_val, b_val))
