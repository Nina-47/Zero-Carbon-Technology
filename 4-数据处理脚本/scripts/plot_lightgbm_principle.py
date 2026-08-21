# -*- coding: utf-8 -*-
"""
LightGBM 原理图（学术风格：白底黑线）
三张独立图：GBDT加法模型 / 单棵树分裂 / 预测前向流程
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Ellipse
import numpy as np

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Noto Sans SC']
plt.rcParams['axes.unicode_minus'] = False

OUT = 'C:/Users/mu\'yan\'shi\'qi/Desktop/零碳2/公用/公用/4-数据处理脚本/图输出'

# 学术风颜色：白底、黑线、浅灰填充
BOX_EDGE = '#000000'
BOX_FACE = '#ffffff'
GRAY_FACE = '#f2f2f2'
HIGHLIGHT = '#d9e8f5'   # 浅蓝，仅用于强调最终结果
ARROW = '#000000'

def box(ax, x, y, w, h, text, face=BOX_FACE, fontsize=9, weight='normal',
        sub='', sub_fs=8):
    """画一个带标文本的矩形框，返回中心坐标"""
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle="round,pad=0.02,rounding_size=0.05",
                       linewidth=1.2, edgecolor=BOX_EDGE, facecolor=face)
    ax.add_patch(p)
    if sub:
        ax.text(x + w/2, y + h*0.62, text, ha='center', va='center',
                fontsize=fontsize, weight=weight)
        ax.text(x + w/2, y + h*0.28, sub, ha='center', va='center',
                fontsize=sub_fs, color='#333333')
    else:
        ax.text(x + w/2, y + h/2, text, ha='center', va='center',
                fontsize=fontsize, weight=weight)
    return (x + w/2, y + h/2)

def arrow(ax, p1, p2, style='-|>', color=ARROW, lw=1.3, ls='-'):
    a = FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=12,
                        linewidth=lw, color=color, linestyle=ls)
    ax.add_patch(a)


# ================= 图1：GBDT 加法模型 =================
fig, ax = plt.subplots(figsize=(10, 6))
ax.set_xlim(0, 10); ax.set_ylim(0, 6)
ax.axis('off')

# 标题
ax.text(5, 5.7, 'GBDT 加法模型：多棵决策树顺序拟合残差', ha='center',
        fontsize=13, weight='bold')

# 树
tree_y = 3.8
trees = [(0.8, '树 #1', '拟合原始 y', '输出 f1(x)'),
         (3.6, '树 #2', '拟合残差 r1', '输出 f2(x)'),
         (6.9, '树 #N', '拟合残差 r(N-1)', '输出 fN(x)')]
centers = []
for tx, name, m1, m2 in trees:
    c = box(ax, tx, tree_y, 1.6, 1.1, name, sub=m1 + '\n' + m2, fontsize=10, weight='bold')
    centers.append(c)

# 残差箭头
arrow(ax, (centers[0][0]+0.8, tree_y+0.55), (centers[1][0]-0.8, tree_y+0.55))
ax.text((centers[0][0]+centers[1][0])/2, tree_y+0.75, '残差 r1', ha='center', fontsize=9, color='#c00000')
# 省略号
ax.text((centers[1][0]+centers[2][0])/2, tree_y+0.55, '… 拟合上一步残差 …', ha='center', fontsize=10, color='#555555')
arrow(ax, (centers[1][0]+0.8, tree_y+0.55), (centers[2][0]-0.8, tree_y+0.55))

# 向下汇聚箭头
for c in centers:
    arrow(ax, (c[0], tree_y-0.55), (c[0], 1.9), color=ARROW, lw=1.2)

# 求和符号
ax.text(5, 1.35, 'Σ', ha='center', va='center', fontsize=26, weight='bold')

# 最终预测
c = box(ax, 3.9, 0.15, 2.2, 0.8, '最终预测 y_pred', sub='y_pred = f1(x)+…+fN(x) · η',
        face=HIGHLIGHT, fontsize=11, weight='bold')
arrow(ax, (5, 1.0), (5, 0.95), style='-|>', color=ARROW, lw=1.5)

# 公式说明
ax.text(0.2, 5.3, '核心：每棵树拟合上一步残差（负梯度方向），逐步逼近真实值',
        fontsize=9.5, color='#333333')
ax.text(0.2, 5.0, 'η（学习率）控制每棵树的贡献幅度；Leaf-wise 生长使残差快速下降',
        fontsize=9, color='#555555')

plt.tight_layout()
plt.savefig(f'{OUT}/LightGBM原理图1_GBDT加法模型.png', dpi=300, bbox_inches='tight')
plt.savefig(f'{OUT}/LightGBM原理图1_GBDT加法模型.svg', bbox_inches='tight')
plt.close(fig)


# ================= 图2：单棵树分裂机制 =================
fig, ax = plt.subplots(figsize=(10, 7))
ax.set_xlim(0, 10); ax.set_ylim(0, 7)
ax.axis('off')

ax.text(5, 6.7, '单棵树分裂：直方图分桶 + 增益最大分裂', ha='center',
        fontsize=13, weight='bold')

# 直方图分桶
box(ax, 0.5, 5.9, 2.2, 0.7, '直方图分桶', sub='连续特征→离散桶', fontsize=10, weight='bold')
ax.text(2.9, 6.2, '气温 25.3°C → 桶「25°C档」', fontsize=9, color='#555555', va='center')

arrow(ax, (1.6, 5.9), (5, 4.9), color=ARROW, lw=1.3)

# 根节点
box(ax, 3.9, 4.3, 2.2, 0.8, '根节点：全部样本', sub='增益=分裂后-前损失', fontsize=10, weight='bold')

# 分裂判断
arrow(ax, (5, 4.3), (5, 3.7))
ax.text(5.15, 3.95, 'lag-1h > 25 kW ?', fontsize=10, va='center', weight='bold')

# 左分支 是
arrow(ax, (5, 3.4), (2.2, 2.9))
ax.text(3.4, 3.35, '是', fontsize=9.5, color='#1f4e79')
box(ax, 0.5, 2.0, 1.8, 0.8, '叶子 A', sub='权重 w_A=29.3', face=GRAY_FACE, fontsize=10, weight='bold')

# 右分支 否
arrow(ax, (5, 3.4), (8.2, 2.9))
ax.text(6.8, 3.35, '否', fontsize=9.5, color='#1f4e79')
box(ax, 7.1, 2.0, 1.8, 0.8, '叶子 B', sub='权重 w_B=20.1', face=GRAY_FACE, fontsize=10, weight='bold')

# 继续分裂
ax.text(1.4, 1.75, '再按增益分裂', fontsize=8, color='#777777', ha='center')
ax.text(8.0, 1.75, '再按增益分裂', fontsize=8, color='#777777', ha='center')
arrow(ax, (1.4, 2.0), (1.4, 1.55), color='#999999', lw=0.8, ls=':')
arrow(ax, (8.0, 2.0), (8.0, 1.55), color='#999999', lw=0.8, ls=':')

# 停止条件
box(ax, 3.3, 0.8, 3.4, 1.3, '', face='#ffffff')
ax.text(5, 1.9, '停止分裂条件', ha='center', fontsize=9, weight='bold')
ax.text(3.5, 1.5, '· 叶子样本数 < min_data', fontsize=8.5, color='#333333')
ax.text(3.5, 1.25, '· 深度达 max_depth / 增益 < min_gain', fontsize=8.5, color='#333333')

# 右边说明
ax.text(5, 0.45, '叶子权重 ≈ 该桶残差均值 × 学习率，落入叶子的样本取该权重为预测值',
        ha='center', fontsize=9, color='#555555')

plt.tight_layout()
plt.savefig(f'{OUT}/LightGBM原理图2_单棵树分裂.png', dpi=300, bbox_inches='tight')
plt.savefig(f'{OUT}/LightGBM原理图2_单棵树分裂.svg', bbox_inches='tight')
plt.close(fig)


# ================= 图3：预测前向流程 =================
fig, ax = plt.subplots(figsize=(10, 6))
ax.set_xlim(0, 10); ax.set_ylim(0, 6)
ax.axis('off')

ax.text(5, 5.7, 'LightGBM 负荷预测前向流程', ha='center', fontsize=13, weight='bold')

# 输入特征
box(ax, 0.6, 4.3, 2.4, 1.0, '输入特征向量 x', sub='滞后+光伏+气象+时间+日历', fontsize=10, weight='bold')

# 箭头
arrow(ax, (3.0, 4.8), (4.5, 4.8), lw=1.4)

# 训练好的模型
box(ax, 4.5, 4.15, 2.4, 1.3, '训练好的 LightGBM', sub='N 棵决策树集成', face=HIGHLIGHT, fontsize=10, weight='bold')
ax.text(5.7, 4.35, 'MAE 0.81kW · R² 0.933', ha='center', fontsize=8, color='#1f4e79')

# 箭头
arrow(ax, (6.9, 4.8), (8.4, 4.8), lw=1.4)

# 输出
box(ax, 8.4, 4.3, 1.2, 1.0, '24h 负荷\n预测值', fontsize=9.5, weight='bold')

# 特征重要性
box(ax, 0.6, 2.3, 3.0, 1.4, '', face='#ffffff')
ax.text(2.1, 3.5, '特征重要性Top5', ha='center', fontsize=9, weight='bold')
ax.text(0.8, 3.15, 'lag-1h（惯性）｜lag-24h（日周期）', fontsize=8.5, color='#333333')
ax.text(0.8, 2.85, 'hour_sin ｜ hour_cos ｜ lag-168h', fontsize=8.5, color='#333333')
ax.text(0.8, 2.55, '→ 近期历史负荷是最强信号', fontsize=8, color='#777777')

# 底部：为何选LightGBM
box(ax, 4.2, 2.3, 5.2, 1.9, '', face='#ffffff')
ax.text(6.8, 3.9, '为何选 LightGBM', ha='center', fontsize=9, weight='bold')
ax.text(4.4, 3.55, '· 小数据集(10944)更稳、不易过拟合', fontsize=8.5, color='#333333')
ax.text(4.4, 3.25, '· 天然捕捉高温+高湿+强辐射非线性交互', fontsize=8.5, color='#333333')
ax.text(4.4, 2.95, '· 特征重要性(Gain/Split)可解释，评审友好', fontsize=8.5, color='#333333')
ax.text(4.4, 2.65, '· 训练快、无需 GPU', fontsize=8.5, color='#333333')

plt.tight_layout()
plt.savefig(f'{OUT}/LightGBM原理图3_预测前向流程.png', dpi=300, bbox_inches='tight')
plt.savefig(f'{OUT}/LightGBM原理图3_预测前向流程.svg', bbox_inches='tight')
plt.close(fig)

print('LightGBM 原理图 3 张（学术白底风格）已生成到', OUT)
