# 污水处理厂负荷预测 V2 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Holt-Winters(日总量) + KNN模板匹配(逐时分配) 两阶段方法替代现有递归逐时预测，降低 A公司日总 MAPE 从 13.84% 到 <8%。

**Architecture:** 阶段一用 statsmodels Holt-Winters（damped trend + 7天季节性）预测每日总负荷；阶段二在历史中按日总量相似度匹配 K=5 天，取加权平均逐时分配曲线，按预测日总量缩放。工作日/周末分开建库。保留原有模型输出做对比。

**Tech Stack:** Python 3, pandas, numpy, statsmodels, openpyxl, matplotlib, scikit-learn

## Global Constraints

- 只用现有 4-6月逐时负荷数据（91天），不引入外部天气/光伏/调度数据
- 输出 Excel 格式与现有 `预测输出/*_7月预测.xlsx` 保持一致（日汇总 + 月汇总 + 逐时数据三 sheet）
- 新脚本独立于 `负荷预测.py`，命名为 `负荷预测_v2.py`
- 输出目录 `预测输出_v2/`
- 用 A公司_7月预测 文件夹中的实际 7月数据做最终评估
- 在输出报告中标注误差来源（午间=天气/光伏，异常波动=人工调度）

---

### Task 1: 数据加载与预处理模块

**Files:**
- Create: `负荷预测_v2.py`（数据加载部分）

**Interfaces:**
- Produces: `df_raw: pd.DataFrame`（日总量表，列: date, company, daily_total, hourly[list]）
- Produces: `df_hourly: pd.DataFrame`（逐时表，列: datetime, date, hour, company, load_mw, daily_total, dow, is_weekend）

- [ ] **Step 1: 加载 4-6月原始数据**

```python
# -*- coding: utf-8 -*-
"""
污水处理厂7月负荷预测 V2 — Holt-Winters + KNN模板匹配
改进点: 两阶段解耦预测，解决递归模型趋势外推过度问题
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import warnings
warnings.filterwarnings('ignore')

# 中文字体
import platform
if platform.system() == 'Windows':
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
else:
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 150
plt.rcParams['savefig.dpi'] = 150
plt.rcParams['savefig.bbox'] = 'tight'

# ============================================================
# 1. 数据加载
# ============================================================
import openpyxl

path = r'数据\污水处理厂4、5、6月数据.xlsx'
wb = openpyxl.load_workbook(path, data_only=True)
ws = wb['Sheet1']

records = []
for row in ws.iter_rows(min_row=2, values_only=True):
    date_val, company, daily_total = row[0], row[1], row[2]
    if date_val is None or company is None:
        continue
    date_str = str(date_val)[:10] if len(str(date_val)) >= 10 else str(date_val)
    hourly = list(row[3:27])

    # 处理缺失小时值: 前向+后向填充
    if any(v is None for v in hourly):
        known = [(i, float(v)) for i, v in enumerate(hourly) if v is not None]
        if len(known) >= 20:
            filled = []
            last_val = known[0][1]
            for h in range(24):
                v = hourly[h]
                if v is not None:
                    filled.append(float(v))
                    last_val = float(v)
                else:
                    next_val = last_val
                    for nh in range(h + 1, 24):
                        if hourly[nh] is not None:
                            next_val = float(hourly[nh])
                            break
                    filled.append((last_val + next_val) / 2)
            hourly = filled
        else:
            continue

    records.append({
        'date': pd.to_datetime(date_str),
        'company': str(company),
        'daily_total': float(daily_total),
        'hourly': [float(v) for v in hourly]
    })

df_raw = pd.DataFrame(records)
print(f"总记录数: {len(df_raw)}")
print(f"公司: {df_raw['company'].unique()}")
print(f"日期范围: {df_raw['date'].min()} ~ {df_raw['date'].max()}")
```

- [ ] **Step 2: 构建逐时表**

```python
# 构建逐时 DataFrame
rows = []
for _, rec in df_raw.iterrows():
    dt = rec['date']
    for h, val in enumerate(rec['hourly']):
        rows.append({
            'datetime': dt + pd.Timedelta(hours=h),
            'date': dt,
            'hour': h,
            'company': rec['company'],
            'load_mw': val,
            'daily_total': rec['daily_total']
        })

df_hourly = pd.DataFrame(rows)
df_hourly = df_hourly.sort_values(['company', 'datetime']).reset_index(drop=True)
df_hourly['dow'] = df_hourly['datetime'].dt.dayofweek  # 0=Mon
df_hourly['is_weekend'] = (df_hourly['dow'] >= 5).astype(int)

print(f"逐时记录: {len(df_hourly):,}")
```

- [ ] **Step 3: 运行并验证数据加载正确**

```bash
python 负荷预测_v2.py
```
预期输出：总记录数 273-277，逐时记录 ~6552，日期范围 2026-04-01 ~ 2026-06-30

---

### Task 2: 阶段一 — Holt-Winters 日总量预测

**Files:**
- Modify: `负荷预测_v2.py`（追加代码）

**Interfaces:**
- Consumes: `df_raw` from Task 1
- Produces: `hw_results: dict[company] -> {forecast: pd.Series, fitted: HW model, params: dict}`
- Produces: `df_daily_pred: pd.DataFrame` (列: company, date, daily_pred, daily_lower, daily_upper)

- [ ] **Step 1: 实现 Holt-Winters 预测函数**

```python
# ============================================================
# 2. 阶段一: Holt-Winters 日总量预测 (damped trend + 7天季节性)
# ============================================================
from statsmodels.tsa.holtwinters import ExponentialSmoothing

def fit_hw_and_forecast(daily_series, forecast_horizon=31, seasonal_periods=7):
    """
    用 Holt-Winters (damped trend, additive seasonality) 拟合日总量序列并预测
    
    Args:
        daily_series: pd.Series with datetime index, daily total MWh
        forecast_horizon: 预测天数
        seasonal_periods: 季节周期（7=周）
    
    Returns:
        forecast: pd.Series (预测值, index=未来日期)
        fitted_model: 拟合的模型对象
    """
    # Holt-Winters with damped trend
    model = ExponentialSmoothing(
        daily_series.astype(float),
        trend='add',
        damped_trend=True,
        seasonal='add',
        seasonal_periods=seasonal_periods,
    )
    fitted = model.fit(optimized=True, use_boxcox=False, remove_bias=True)
    
    # 预测
    forecast_result = fitted.forecast(forecast_horizon)
    
    # 构建预测日期索引
    last_date = daily_series.index[-1]
    forecast_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=forecast_horizon, freq='D')
    forecast = pd.Series(forecast_result.values, index=forecast_dates, name='daily_pred')
    
    # 模拟预测区间: 基于历史残差的 bootstrap
    residuals = daily_series - fitted.fittedvalues
    residual_std = residuals.std()
    lower = forecast - 1.28 * residual_std  # 80% CI
    upper = forecast + 1.28 * residual_std
    
    return forecast, lower, upper, fitted

hw_results = {}

for comp in ['A公司', 'B公司', 'C公司']:
    print(f"\n{'='*50}")
    print(f"训练 {comp} Holt-Winters 模型...")
    comp_daily = df_raw[df_raw['company'] == comp].set_index('date')['daily_total'].sort_index()
    
    forecast, lower, upper, fitted = fit_hw_and_forecast(comp_daily, forecast_horizon=31)
    
    hw_results[comp] = {
        'forecast': forecast,
        'lower': lower,
        'upper': upper,
        'fitted': fitted,
        'daily_series': comp_daily
    }
    
    # 6月回测
    train = comp_daily[comp_daily.index < pd.Timestamp('2026-06-01')]
    test = comp_daily[comp_daily.index >= pd.Timestamp('2026-06-01')]
    _, _, _, fitted_backtest = fit_hw_and_forecast(train, forecast_horizon=30)
    
    bt_forecast = fitted_backtest.forecast(30)
    bt_actual = test.values[:30]
    from sklearn.metrics import mean_absolute_error
    bt_mae = mean_absolute_error(bt_actual, bt_forecast)
    bt_mape = np.mean(np.abs((bt_actual - bt_forecast) / bt_actual)) * 100
    print(f"  6月回测 MAE: {bt_mae:.2f} MWh, MAPE: {bt_mape:.2f}%")
    print(f"  平滑参数: alpha={fitted.params['smoothing_level']:.3f}, "
          f"beta={fitted.params['smoothing_trend']:.3f}, "
          f"gamma={fitted.params['smoothing_seasonal']:.3f}, "
          f"phi={fitted.params['damping_trend']:.3f}")
    print(f"  7月预测日均: {forecast.mean():.1f} MWh")
```

- [ ] **Step 2: 运行验证 HW 回测精度**

```bash
python 负荷预测_v2.py
```
检查 6月回测 MAPE 和 damped trend 的 phi 参数（应 < 1，表示趋势在衰减）

---

### Task 3: 阶段二 — KNN 模板匹配逐时分配

**Files:**
- Modify: `负荷预测_v2.py`（追加代码）

**Interfaces:**
- Consumes: `df_hourly` from Task 1, `hw_results` from Task 2
- Produces: `df_hourly_pred: pd.DataFrame` (列: datetime, company, hour, load_pred, daily_pred_mwh, template_days)

- [ ] **Step 1: 构建历史模板库**

```python
# ============================================================
# 3. 阶段二: KNN 模板匹配 — 逐时分配
# ============================================================

def build_template_library(df_hourly, company):
    """
    构建逐时分配模板库。
    对每一天，存储: 日总量 + 归一化逐时分配曲线 + 是否周末
    
    Returns:
        list of dict: [{daily_total, hourly_profile(24,), is_weekend, date}]
    """
    comp_data = df_hourly[df_hourly['company'] == company]
    templates = []
    for dt, group in comp_data.groupby('date'):
        daily_total = group['load_mw'].sum()
        hourly = group.set_index('hour')['load_mw'].sort_index().values
        if len(hourly) != 24:
            continue
        # 归一化: 每小时占日总量比例
        profile = hourly / daily_total
        is_weekend = group['is_weekend'].iloc[0]
        templates.append({
            'date': dt,
            'daily_total': daily_total,
            'hourly_profile': profile,
            'is_weekend': is_weekend
        })
    return templates

def match_templates(templates, target_daily_total, is_weekend, k=5):
    """
    在模板库中匹配 K 个日总量最接近的历史天。
    只在同类（工作日/周末）中搜索。
    
    Returns:
        hourly_profile: np.array(24,) — 归一化分配曲线
        matched_dates: list — 匹配到的历史日期（用于可解释性）
    """
    same_type = [t for t in templates if t['is_weekend'] == is_weekend]
    if len(same_type) < k:
        # 不够 K 个，用全部同类
        same_type = [t for t in templates if t['is_weekend'] == is_weekend]
    
    # 按日总量距离排序
    same_type_sorted = sorted(same_type, key=lambda t: abs(t['daily_total'] - target_daily_total))
    top_k = same_type_sorted[:k]
    
    # 加权平均 (权重 = 1 / (|日总量差| + epsilon))
    weights = np.array([1.0 / (abs(t['daily_total'] - target_daily_total) + 1e-3) for t in top_k])
    weights = weights / weights.sum()
    
    profiles = np.array([t['hourly_profile'] for t in top_k])
    weighted_profile = np.average(profiles, axis=0, weights=weights)
    
    # 确保归一化
    weighted_profile = weighted_profile / weighted_profile.sum()
    
    matched_dates = [t['date'] for t in top_k]
    return weighted_profile, matched_dates

def generate_hourly_forecast(daily_forecast, templates, is_weekend_map, k=5):
    """
    对每一天的日总量预测，匹配模板并生成逐时负荷
    
    Args:
        daily_forecast: pd.Series (index=date, values=daily MWh)
        templates: from build_template_library
        is_weekend_map: dict date->is_weekend
    
    Returns:
        list of dict: [{datetime, hour, load_mw, daily_total, matched_dates, profile_std}]
    """
    results = []
    for pred_date, daily_total in daily_forecast.items():
        is_we = is_weekend_map.get(pred_date, 0)
        profile, matched = match_templates(templates, daily_total, is_we, k=k)
        
        # 计算模板波动 (用于不确定性评估)
        matched_data = []
        for t in templates:
            if t['date'] in matched:
                matched_data.append(t['hourly_profile'] * daily_total)
        profile_std = np.std(matched_data, axis=0) if len(matched_data) > 1 else np.zeros(24)
        
        for h in range(24):
            pred_dt = pd.Timestamp(pred_date) + pd.Timedelta(hours=h)
            results.append({
                'datetime': pred_dt,
                'date': pred_date,
                'company': None,  # 后面填充
                'hour': h,
                'load_mw': daily_total * profile[h],
                'daily_total_mwh': daily_total,
                'profile_std_mw': profile_std[h],
                'matched_dates': [str(d.date()) for d in matched]
            })
    return results
```

- [ ] **Step 2: 对三家公司生成逐时预测**

```python
# 生成逐时预测
all_hourly_preds = []
july_dates = pd.date_range('2026-07-01', '2026-07-31', freq='D')
is_weekend_map = {d: (1 if d.dayofweek >= 5 else 0) for d in july_dates}

for comp in ['A公司', 'B公司', 'C公司']:
    print(f"\n生成 {comp} 逐时预测...")
    templates = build_template_library(df_hourly, comp)
    forecast = hw_results[comp]['forecast']
    
    hourly_preds = generate_hourly_forecast(forecast, templates, is_weekend_map, k=5)
    for p in hourly_preds:
        p['company'] = comp
    all_hourly_preds.extend(hourly_preds)
    
    print(f"  模板库大小: {len(templates)} 天")
    print(f"  生成 {len(hourly_preds)} 条逐时预测")

df_hourly_pred = pd.DataFrame(all_hourly_preds)
print(f"\n逐时预测总计: {len(df_hourly_pred)} 条")
```

- [ ] **Step 3: 运行验证逐时预测合理性**

检查：所有负荷值 > 0，日总量加总 ≈ HW 预测值，逐时曲线符合典型污水厂模式（早晚高、午间低）

---

### Task 4: 模型评估 — 新旧方法对比

**Files:**
- Modify: `负荷预测_v2.py`（追加评估代码）

**Interfaces:**
- Consumes: `df_hourly_pred` from Task 3, `A公司_7月预测/*.xlsx` actual data
- Produces: `df_comparison: pd.DataFrame`（新旧方法逐时/日总精度对比表）

- [ ] **Step 1: 加载 7月实际数据并评估**

```python
# ============================================================
# 4. 模型评估 — 新旧方法对比
# ============================================================
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

def load_actual_july(comp):
    """加载 7月实际逐时数据"""
    folder = 'A公司_7月预测'
    fname = f'{comp}公司_7月预测.xlsx'
    xls = pd.ExcelFile(f'{folder}/{fname}')
    # 第3个sheet是逐时数据（名称可能有尾部空格）
    sheet_name = [s for s in xls.sheet_names if '逐时' in s][0]
    df = pd.read_excel(f'{folder}/{fname}', sheet_name=sheet_name)
    
    # 确定实际值列名
    if '实际' in df.columns:
        actual_col = '实际'
    else:
        # B公司列名可能是 Unnamed: 7
        unnamed_cols = [c for c in df.columns if 'Unnamed' in str(c)]
        actual_col = unnamed_cols[0] if unnamed_cols else None
    
    if actual_col is None:
        return None
    
    df['actual'] = df[actual_col]
    df['日期'] = pd.to_datetime(df['日期'])
    return df.dropna(subset=['actual'])

print("\n" + "="*60)
print("模型评估 — 7月实际数据验证")
print("="*60)

comparison_rows = []

for comp in ['A公司', 'B公司', 'C公司']:
    print(f"\n{'='*40}")
    print(f"{comp} 新旧方法对比")
    
    actual = load_actual_july(comp)
    if actual is None or len(actual) == 0:
        print(f"  {comp}: 无实际数据，跳过")
        continue
    
    # 合并新方法预测
    pred_new = df_hourly_pred[df_hourly_pred['company'] == comp].copy()
    pred_new['date'] = pd.to_datetime(pred_new['date'])
    pred_new['hour'] = pred_new['hour'].astype(int)
    
    merged = actual.merge(
        pred_new[['date', 'hour', 'load_mw', 'daily_total_mwh']],
        left_on=['日期', '小时'],
        right_on=['date', 'hour'],
        how='inner'
    )
    
    # 新方法 (Holt-Winters + KNN)
    mae_new = mean_absolute_error(merged['actual'], merged['load_mw'])
    rmse_new = np.sqrt(mean_squared_error(merged['actual'], merged['load_mw']))
    r2_new = r2_score(merged['actual'], merged['load_mw'])
    
    # 旧方法 (XGBoost + Prophet 集成)
    mae_old = mean_absolute_error(merged['actual'], merged['集成预测_MW'])
    rmse_old = np.sqrt(mean_squared_error(merged['actual'], merged['集成预测_MW']))
    r2_old = r2_score(merged['actual'], merged['集成预测_MW'])
    
    # 日总评估
    daily_new = merged.groupby('日期').agg({'actual': 'sum', 'load_mw': 'sum', '集成预测_MW': 'sum'})
    mape_new = (abs(daily_new['actual'] - daily_new['load_mw']) / daily_new['actual'] * 100).mean()
    mape_old = (abs(daily_new['actual'] - daily_new['集成预测_MW']) / daily_new['actual'] * 100).mean()
    
    print(f"  {'':>12} {'旧方法':>12} {'新方法':>12} {'提升':>10}")
    print(f"  {'逐时MAE':>12} {mae_old:>10.4f} MW {mae_new:>10.4f} MW {((mae_old-mae_new)/mae_old*100):>+9.1f}%")
    print(f"  {'逐时RMSE':>12} {rmse_old:>10.4f} MW {rmse_new:>10.4f} MW")
    print(f"  {'逐时R2':>12} {r2_old:>10.4f}    {r2_new:>10.4f}")
    print(f"  {'日总MAPE':>12} {mape_old:>10.2f}%     {mape_new:>10.2f}%")
    
    for metric, old_val, new_val in [
        ('逐时MAE_MW', mae_old, mae_new),
        ('逐时RMSE_MW', rmse_old, rmse_new),
        ('逐时R2', r2_old, r2_new),
        ('日总MAPE_%', mape_old, mape_new)
    ]:
        comparison_rows.append({'公司': comp, '指标': metric, '旧方法': old_val, '新方法': new_val})

df_comparison = pd.DataFrame(comparison_rows)
print("\n\n=== 汇总对比 ===")
print(df_comparison.to_string(index=False))
df_comparison.to_csv('预测输出_v2/模型对比_v2.csv', index=False, encoding='utf-8-sig')
```

- [ ] **Step 2: 午间误差专项分析**

```python
# 午间误差专项分析 (标注光伏/天气影响)
print("\n\n=== 午间时段(10-15h)误差分析 ===")
for comp in ['A公司', 'B公司', 'C公司']:
    actual = load_actual_july(comp)
    if actual is None: continue
    pred_new = df_hourly_pred[df_hourly_pred['company'] == comp].copy()
    pred_new['date'] = pd.to_datetime(pred_new['date'])
    
    merged = actual.merge(
        pred_new[['date', 'hour', 'load_mw']],
        left_on=['日期', '小时'], right_on=['date', 'hour'], how='inner'
    )
    
    midday = merged[merged['小时'].between(10, 15)]
    other = merged[~merged['小时'].between(10, 15)]
    
    midday_mae = mean_absolute_error(midday['actual'], midday['load_mw'])
    other_mae = mean_absolute_error(other['actual'], other['load_mw'])
    
    print(f"  {comp}: 午间 MAE={midday_mae:.4f} MW, 其他时段 MAE={other_mae:.4f} MW, "
          f"午间/其他={midday_mae/other_mae:.2f}x")
    print(f"    提示: 午间误差偏大可能与光伏出力、气温变化有关，需天气数据验证")
```

- [ ] **Step 3: 运行评估，确认新方法优于旧方法**

```bash
python 负荷预测_v2.py
```
目标：A公司日总 MAPE < 8%（从 13.84% 下降），逐时 MAE < 0.55 MW（从 0.79 下降）

---

### Task 5: 可视化 — 预测结果与对比图

**Files:**
- Modify: `负荷预测_v2.py`（追加可视化代码）

- [ ] **Step 1: 日总量预测 vs 实际对比图**

```python
# ============================================================
# 5. 可视化
# ============================================================
import os
os.makedirs('预测输出_v2', exist_ok=True)

colors = {'A公司': '#2563eb', 'B公司': '#059669', 'C公司': '#d97706'}

# 5.1 日总量预测对比
fig, axes = plt.subplots(3, 1, figsize=(16, 10))
for i, comp in enumerate(['A公司', 'B公司', 'C公司']):
    # 历史日总量
    hist = df_raw[df_raw['company']==comp].set_index('date')['daily_total'].sort_index()
    axes[i].plot(hist.index, hist.values, color=colors[comp], linewidth=0.8, alpha=0.7, label='4-6月实际')
    
    # HW 预测
    forecast = hw_results[comp]['forecast']
    lower = hw_results[comp]['lower']
    upper = hw_results[comp]['upper']
    axes[i].plot(forecast.index, forecast.values, color='red', linewidth=1.8, label='HW预测')
    axes[i].fill_between(forecast.index, lower.values, upper.values, alpha=0.15, color='red', label='80% CI')
    
    # 7月实际（如果有）
    actual = load_actual_july(comp)
    if actual is not None:
        daily_actual = actual.groupby('日期')['actual'].sum()
        axes[i].scatter(daily_actual.index, daily_actual.values, color='green', s=20, alpha=0.8, label='7月实际')
    
    axes[i].axvline(x=pd.Timestamp('2026-07-01'), color='black', linestyle='--', alpha=0.4)
    axes[i].set_ylabel('日总 MWh')
    axes[i].set_title(f'{comp} — Holt-Winters Damped Trend', fontweight='bold')
    axes[i].legend(fontsize=8, loc='upper left')
    axes[i].grid(True, alpha=0.3)

axes[-1].set_xlabel('日期')
plt.suptitle('日总量预测: Holt-Winters (Damped Trend + 周季节性)', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig('预测输出_v2/daily_forecast_comparison.png')
plt.close()
print("图1: 日总量预测对比 — 已保存")
```

- [ ] **Step 2: 典型日逐时对比图**

```python
# 5.2 典型日逐时负荷对比
fig, axes = plt.subplots(1, 3, figsize=(16, 5))
# 选7月前7天的平均
for i, comp in enumerate(['A公司', 'B公司', 'C公司']):
    actual = load_actual_july(comp)
    pred_new = df_hourly_pred[df_hourly_pred['company'] == comp]
    
    if actual is not None:
        # 7月前7天
        actual_w1 = actual[actual['日期'].isin(pd.date_range('2026-07-01', '2026-07-07'))]
        pred_w1 = pred_new[pred_new['date'].isin(pd.date_range('2026-07-01', '2026-07-07'))]
        
        actual_profile = actual_w1.groupby('小时')['actual'].mean()
        pred_profile = pred_w1.groupby('hour')['load_mw'].mean()
        
        axes[i].plot(range(24), actual_profile.values, 'o-', color=colors[comp], linewidth=2, markersize=4, label='实际')
        axes[i].plot(range(24), pred_profile.values, 's--', color='red', linewidth=2, markersize=4, label='预测(HW+KNN)')
        
        # 标注午间高误差区
        axes[i].axvspan(10, 15, alpha=0.1, color='orange')
        axes[i].text(12.5, axes[i].get_ylim()[1]*0.95, '午间\n(光伏/天气影响)', ha='center', fontsize=7, color='orange')
    
    axes[i].set_title(f'{comp}', fontweight='bold')
    axes[i].set_xlabel('小时')
    axes[i].set_ylabel('MW')
    axes[i].legend(fontsize=8)
    axes[i].grid(True, alpha=0.3)
    axes[i].set_xticks(range(0, 24, 3))

plt.suptitle('7月第一周 逐时负荷: 预测 vs 实际', fontsize=13, fontweight='bold')
plt.tight_layout()
plt.savefig('预测输出_v2/hourly_profile_comparison.png')
plt.close()
print("图2: 逐时负荷对比 — 已保存")
```

- [ ] **Step 3: 新旧方法误差对比柱状图**

```python
# 5.3 新旧方法对比柱状图
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
metrics = ['逐时MAE_MW', '日总MAPE_%']
for i, metric in enumerate(metrics):
    data = df_comparison[df_comparison['指标'] == metric]
    x = np.arange(3)
    width = 0.3
    axes[i].bar(x - width/2, data['旧方法'], width, label='旧方法(XGB+Prophet)', color='gray', alpha=0.7)
    axes[i].bar(x + width/2, data['新方法'], width, label='新方法(HW+KNN)', color='#2563eb', alpha=0.7)
    axes[i].set_xticks(x)
    axes[i].set_xticklabels(['A公司', 'B公司', 'C公司'])
    axes[i].set_title(metric.replace('_', ' '), fontweight='bold')
    axes[i].legend(fontsize=8)
    axes[i].grid(True, alpha=0.3, axis='y')

plt.suptitle('新旧方法精度对比 — 7月实际数据', fontsize=13, fontweight='bold')
plt.tight_layout()
plt.savefig('预测输出_v2/method_comparison.png')
plt.close()
print("图3: 新旧方法对比 — 已保存")
```

---

### Task 6: 输出 Excel 报告

**Files:**
- Modify: `负荷预测_v2.py`（追加输出代码）

- [ ] **Step 1: 生成各公司 Excel 报告**

```python
# ============================================================
# 6. 输出结果
# ============================================================

for comp in ['A公司', 'B公司', 'C公司']:
    print(f"\n生成 {comp} 预测报告...")
    comp_pred = df_hourly_pred[df_hourly_pred['company'] == comp].copy()
    
    # 日汇总
    daily_report = comp_pred.groupby('date').agg(
        日均负荷_MW=('load_mw', 'mean'),
        日峰荷_MW=('load_mw', 'max'),
        日谷荷_MW=('load_mw', 'min'),
        日总用电量_MWh=('load_mw', 'sum'),
        峰谷差_MW=('load_mw', lambda x: x.max() - x.min()),
        模板波动均值_MW=('profile_std_mw', 'mean'),
    ).reset_index()
    daily_report.columns = ['日期', '日均负荷_MW', '日峰荷_MW', '日谷荷_MW',
                            '日总用电量_MWh', '峰谷差_MW', '预测不确定性_MW']
    
    # 峰谷时刻
    hourly_groups = comp_pred.groupby('date')
    daily_report['峰荷时刻'] = daily_report['日期'].map(
        lambda d: int(hourly_groups.get_group(d).loc[hourly_groups.get_group(d)['load_mw'].idxmax(), 'hour'])
    )
    daily_report['谷荷时刻'] = daily_report['日期'].map(
        lambda d: int(hourly_groups.get_group(d).loc[hourly_groups.get_group(d)['load_mw'].idxmin(), 'hour'])
    )
    
    # 误差说明
    error_note = ('注: 午间(10-15h)误差可能源自光伏出力、气温变化等天气因素；'
                  '异常波动可能源自市政调度指令。两项均需额外数据源验证。')
    
    # 月汇总
    monthly_summary = pd.DataFrame({
        '指标': ['月总用电量_MWh', '日均用电量_MWh', '日均峰荷_MW', '日均谷荷_MW',
                '平均峰谷差_MW', '典型峰荷时刻', '典型谷荷时刻', '预测方法', '误差说明'],
        '数值': [
            f"{daily_report['日总用电量_MWh'].sum():.1f}",
            f"{daily_report['日总用电量_MWh'].mean():.1f}",
            f"{daily_report['日峰荷_MW'].mean():.2f}",
            f"{daily_report['日谷荷_MW'].mean():.2f}",
            f"{daily_report['峰谷差_MW'].mean():.2f}",
            f"{int(daily_report['峰荷时刻'].mode().values[0]) if len(daily_report['峰荷时刻'].mode())>0 else '-'}:00",
            f"{int(daily_report['谷荷时刻'].mode().values[0]) if len(daily_report['谷荷时刻'].mode())>0 else '-'}:00",
            'Holt-Winters(日总量) + KNN模板匹配(逐时分配)',
            error_note
        ]
    })
    
    # 逐时数据
    hourly_out = comp_pred[['datetime', 'hour', 'load_mw', 'daily_total_mwh', 
                             'profile_std_mw', 'matched_dates']].copy()
    hourly_out.columns = ['时间', '小时', '预测负荷_MW', '日总量_MWh', '不确定性_MW', '匹配历史日期']
    hourly_out['日期'] = hourly_out['时间'].dt.date
    
    # 写入Excel
    with pd.ExcelWriter(f'预测输出_v2/{comp}_7月预测.xlsx', engine='openpyxl') as writer:
        daily_report.to_excel(writer, sheet_name='日汇总', index=False)
        monthly_summary.to_excel(writer, sheet_name='月汇总', index=False)
        hourly_out.to_excel(writer, sheet_name='逐时数据', index=False)
    
    print(f"  {comp}_7月预测.xlsx 已保存")
```

- [ ] **Step 2: 运行完整脚本，确认所有输出生成**

```bash
python 负荷预测_v2.py
```
检查 `预测输出_v2/` 下生成：3个 xlsx 文件 + 3张 png + 1个 csv

---

### Task 7: 最终验证与提交

- [ ] **Step 1: 确认 A公司日总 MAPE < 8%**

```bash
python -c "
import pandas as pd
df = pd.read_csv('预测输出_v2/模型对比_v2.csv')
print(df[df['指标']=='日总MAPE_%'])
"
```

- [ ] **Step 2: 清理临时文件，确认输出目录完整**

```bash
ls -la 预测输出_v2/
```

- [ ] **Step 3: 提交**

```bash
git add 负荷预测_v2.py 预测输出_v2/ docs/superpowers/specs/2026-07-29-load-forecast-v2-design.md
git commit -m "feat: 负荷预测V2 — Holt-Winters日总量 + KNN模板匹配逐时分配

改进点:
- 两阶段解耦预测，解决递归模型趋势外推过度问题
- Damped trend 防止下降趋势无限外推
- KNN模板匹配替代递归逐时预测，消除误差累积
- 新增80%预测区间和午间误差标注"
```
