# -*- coding: utf-8 -*-
"""
污水处理厂7月负荷预测 V2 — Holt-Winters + KNN模板匹配
改进点: 两阶段解耦预测，解决递归模型趋势外推过度问题
        阶段一: Holt-Winters (damped trend + 7天季节性) 预测日总量
        阶段二: KNN历史模板匹配 分配逐时负荷
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

import platform
if platform.system() == 'Windows':
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
else:
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 150
plt.rcParams['savefig.dpi'] = 150
plt.rcParams['savefig.bbox'] = 'tight'

import os
os.makedirs('预测输出_v2', exist_ok=True)

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
df_hourly['dow'] = df_hourly['datetime'].dt.dayofweek
df_hourly['is_weekend'] = (df_hourly['dow'] >= 5).astype(int)

print(f"逐时记录: {len(df_hourly):,}")

# ============================================================
# 2. 阶段一: 日总量预测 — 自适应窗口 + 周季节性 + 均值回归
# ============================================================
from sklearn.metrics import mean_absolute_error

def forecast_daily_adaptive(daily_series, forecast_horizon=31):
    """
    日总量预测:
    1. 测试多个回看窗口 + 均值回归强度，在6月验证集上选最优
    2. 最优窗口的均值 + 周季节性修正
    3. 均值回归: 向全序列均值拉回
    4. 最小窗口约束: 窗口至少14天，避免被最后一周的短期波动锚定
    """
    y = daily_series.values.astype(float)
    n = len(y)
    dates = daily_series.index

    # 周季节性: 周一~周日去均值化系数
    dow_idx = np.array([d.dayofweek for d in dates])
    overall_mean = y.mean()
    seasonal = np.zeros(7)
    for d in range(7):
        mask = dow_idx == d
        if mask.sum() > 0:
            seasonal[d] = y[mask].mean() - overall_mean

    # 去季节性的序列
    deseasoned = y - np.array([seasonal[dow_idx[i]] for i in range(n)])

    # 测试多组参数: 回看窗口 × 均值回归强度
    windows = [14, 21, 28, 42, 56]  # 最小14天，防止短窗口过拟合
    reg_strengths = [0.0, 0.2, 0.4, 0.6]
    best_window = 14
    best_reg = 0.0
    best_mae = float('inf')

    val_start = max(14, n - 30)  # 6月验证

    for w in windows:
        if w >= n:
            continue
        for reg in reg_strengths:
            preds = []
            actuals = []
            for i in range(val_start, n):
                if i - w >= 0:
                    base = deseasoned[max(0, i-w):i].mean()
                    # 均值回归
                    deviation = base - deseasoned.mean()
                    if reg > 0:
                        base = base - deviation * reg
                    pred = base + seasonal[dow_idx[i]]
                    pred = max(pred, 0)
                    preds.append(pred)
                    actuals.append(y[i])
            if len(preds) > 0:
                mae = mean_absolute_error(actuals, preds)
                if mae < best_mae:
                    best_mae = mae
                    best_window = w
                    best_reg = reg

    print(f"  最优窗口={best_window}天, 均值回归={best_reg} (6月验证 MAE={best_mae:.2f} MWh)")

    # 用最优参数预测
    recent_deseasoned = deseasoned[-best_window:]
    base_forecast = recent_deseasoned.mean()

    # 均值回归
    all_mean = deseasoned.mean()
    deviation = base_forecast - all_mean
    if best_reg > 0:
        base_forecast = base_forecast - deviation * best_reg

    print(f"  基准预测: {base_forecast:.1f}, 全序列均值: {all_mean:.1f}, 偏差: {deviation:.1f}")

    # 生成31天预测 (每个预测日的均值 + 当天季节性)
    last_date = dates[-1]
    forecast_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=forecast_horizon, freq='D')

    forecasts = []
    for i in range(forecast_horizon):
        pred_dow = forecast_dates[i].dayofweek
        pred = base_forecast + seasonal[pred_dow]
        pred = max(pred, 0)
        forecasts.append(pred)

    forecast = pd.Series(forecasts, index=forecast_dates, name='daily_pred')

    # 置信区间
    fitted_deseasoned = np.array([deseasoned[max(0,i-best_window):i].mean()
                                  for i in range(val_start, n)])
    fitted_seasonal = np.array([seasonal[dow_idx[i]] for i in range(val_start, n)])
    residuals = y[-len(fitted_deseasoned):] - (fitted_deseasoned + fitted_seasonal)
    residual_std = residuals.std()

    lower = pd.Series([max(0, f - 1.28 * residual_std) for f in forecasts], index=forecast_dates)
    upper = pd.Series([f + 1.28 * residual_std for f in forecasts], index=forecast_dates)

    return forecast, lower, upper, {
        'best_window': best_window, 'seasonal': seasonal,
        'base_forecast': base_forecast, 'residual_std': residual_std,
        'overall_mean': overall_mean, 'best_reg': best_reg
    }

hw_results = {}

for comp in ['A公司', 'B公司', 'C公司']:
    print(f"\n{'='*50}")
    print(f"训练 {comp} 自适应日总量预测...")
    comp_daily = df_raw[df_raw['company'] == comp].set_index('date')['daily_total'].sort_index()

    forecast, lower, upper, info = forecast_daily_adaptive(comp_daily, forecast_horizon=31)

    hw_results[comp] = {
        'forecast': forecast,
        'lower': lower,
        'upper': upper,
        'info': info,
        'daily_series': comp_daily
    }

    print(f"  周季节性: {dict(zip(['一','二','三','四','五','六','日'], info['seasonal'].round(2)))}")
    print(f"  7月预测日均: {forecast.mean():.1f} MWh, std: {forecast.std():.1f} (历史std: {comp_daily.std():.1f})")

# ============================================================
# 3. 阶段二: KNN 模板匹配 — 逐时分配
# ============================================================

def build_template_library(df_hourly, company):
    """
    构建逐时分配模板库。
    对每一天，存储: 日总量 + 归一化逐时分配曲线 + 是否周末
    """
    comp_data = df_hourly[df_hourly['company'] == company]
    templates = []
    for dt, group in comp_data.groupby('date'):
        daily_total = group['load_mw'].sum()
        hourly = group.set_index('hour')['load_mw'].sort_index().values
        if len(hourly) != 24:
            continue
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
    """
    same_type = [t for t in templates if t['is_weekend'] == is_weekend]
    if len(same_type) == 0:
        same_type = templates  # fallback: 用全部

    # 按日总量距离排序
    same_type_sorted = sorted(same_type, key=lambda t: abs(t['daily_total'] - target_daily_total))
    top_k = same_type_sorted[:min(k, len(same_type_sorted))]

    # 加权平均 (权重 = 1 / (|日总量差| + epsilon))
    weights = np.array([1.0 / (abs(t['daily_total'] - target_daily_total) + 1e-3) for t in top_k])
    weights = weights / weights.sum()

    profiles = np.array([t['hourly_profile'] for t in top_k])
    weighted_profile = np.average(profiles, axis=0, weights=weights)
    weighted_profile = weighted_profile / weighted_profile.sum()

    matched_dates = [t['date'] for t in top_k]
    return weighted_profile, matched_dates

def generate_hourly_forecast(daily_forecast, templates, is_weekend_map, k=5):
    """
    对每一天的日总量预测，匹配模板并生成逐时负荷
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
                'company': None,
                'hour': h,
                'load_mw': daily_total * profile[h],
                'daily_total_mwh': daily_total,
                'profile_std_mw': profile_std[h],
                'matched_dates': [str(d.date()) for d in matched]
            })
    return results

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

# 合理性检查
for comp in ['A公司', 'B公司', 'C公司']:
    comp_pred = df_hourly_pred[df_hourly_pred['company'] == comp]
    daily_sum = comp_pred.groupby('date')['load_mw'].sum()
    hw_daily = hw_results[comp]['forecast']
    diff = (daily_sum - hw_daily).abs().max()
    print(f"  {comp} 日总量加总 vs HW预测 最大偏差: {diff:.6f} MWh (应接近0)")
    print(f"  {comp} 负荷范围: {comp_pred['load_mw'].min():.2f} ~ {comp_pred['load_mw'].max():.2f} MW")

# ============================================================
# 4. 模型评估 — 新旧方法对比
# ============================================================
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

def load_actual_july(comp):
    """加载 7月实际逐时数据"""
    folder = 'A公司_7月预测'
    fname = f'{comp}_7月预测.xlsx'
    xls = pd.ExcelFile(f'{folder}/{fname}')
    sheet_name = [s for s in xls.sheet_names if '逐时' in s][0]
    df = pd.read_excel(f'{folder}/{fname}', sheet_name=sheet_name)

    if '实际' in df.columns:
        actual_col = '实际'
    else:
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
all_daily_errors = []  # 存储每日误差用于后续分析

for comp in ['A公司', 'B公司', 'C公司']:
    print(f"\n{'='*40}")
    print(f"{comp} 新旧方法对比")

    actual = load_actual_july(comp)
    if actual is None or len(actual) == 0:
        print(f"  {comp}: 无实际数据，跳过")
        continue

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

    for metric, old_val, new_val, unit in [
        ('逐时MAE', mae_old, mae_new, 'MW'),
        ('逐时RMSE', rmse_old, rmse_new, 'MW'),
        ('逐时R2', r2_old, r2_new, ''),
        ('日总MAPE', mape_old, mape_new, '%')
    ]:
        improvement = ((old_val - new_val) / old_val * 100) if old_val != 0 else 0
        comparison_rows.append({
            '公司': comp, '指标': metric, '旧方法': round(old_val, 4),
            '新方法': round(new_val, 4), '提升%': round(improvement, 1), '单位': unit
        })

    # 存每日误差
    for dt, row in daily_new.iterrows():
        all_daily_errors.append({
            '公司': comp, '日期': dt,
            '实际_MWh': row['actual'],
            '新方法预测_MWh': row['load_mw'],
            '旧方法预测_MWh': row['集成预测_MW'],
            '新方法误差%': abs(row['actual'] - row['load_mw']) / row['actual'] * 100,
            '旧方法误差%': abs(row['actual'] - row['集成预测_MW']) / row['actual'] * 100
        })

df_comparison = pd.DataFrame(comparison_rows)
print("\n\n=== 汇总对比 ===")
print(df_comparison.to_string(index=False))
df_comparison.to_csv('预测输出_v2/模型对比_v2.csv', index=False, encoding='utf-8-sig')

df_daily_errors = pd.DataFrame(all_daily_errors)
df_daily_errors.to_csv('预测输出_v2/每日误差对比.csv', index=False, encoding='utf-8-sig')

# 午间误差专项分析 (标注光伏/天气影响)
print("\n\n=== 午间时段(10-15h)误差分析 ===")
for comp in ['A公司', 'B公司', 'C公司']:
    actual = load_actual_july(comp)
    if actual is None:
        continue
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
    print(f"    → 午间误差偏大，可能与光伏出力、气温变化有关，需天气数据验证")

# ============================================================
# 5. 可视化
# ============================================================
colors = {'A公司': '#2563eb', 'B公司': '#059669', 'C公司': '#d97706'}

# 5.1 日总量预测对比
fig, axes = plt.subplots(3, 1, figsize=(16, 10))
for i, comp in enumerate(['A公司', 'B公司', 'C公司']):
    hist = df_raw[df_raw['company'] == comp].set_index('date')['daily_total'].sort_index()
    axes[i].plot(hist.index, hist.values, color=colors[comp], linewidth=0.8, alpha=0.7, label='4-6月实际')

    forecast = hw_results[comp]['forecast']
    lower = hw_results[comp]['lower']
    upper = hw_results[comp]['upper']
    axes[i].plot(forecast.index, forecast.values, color='red', linewidth=1.8, label='HW预测')
    axes[i].fill_between(forecast.index, lower.values, upper.values, alpha=0.15, color='red', label='80% CI')

    actual = load_actual_july(comp)
    if actual is not None:
        daily_actual = actual.groupby('日期')['actual'].sum()
        axes[i].scatter(daily_actual.index, daily_actual.values, color='green', s=20, alpha=0.8, label='7月实际')

    axes[i].axvline(x=pd.Timestamp('2026-07-01'), color='black', linestyle='--', alpha=0.4)
    axes[i].set_ylabel('日总 MWh')
    axes[i].set_title(f'{comp} — 趋势分解 + 周季节性', fontweight='bold')
    axes[i].legend(fontsize=8, loc='upper left')
    axes[i].grid(True, alpha=0.3)

axes[-1].set_xlabel('日期')
plt.suptitle('日总量预测: 趋势分解 + 周季节性 (Damped Trend)', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig('预测输出_v2/daily_forecast_comparison.png')
plt.close()
print("\n图1: 日总量预测对比 — 已保存")

# 5.2 典型日逐时负荷对比
fig, axes = plt.subplots(1, 3, figsize=(16, 5))
for i, comp in enumerate(['A公司', 'B公司', 'C公司']):
    actual = load_actual_july(comp)
    pred_new = df_hourly_pred[df_hourly_pred['company'] == comp]

    if actual is not None:
        actual_w1 = actual[actual['日期'].isin(pd.date_range('2026-07-01', '2026-07-07'))]
        pred_w1 = pred_new[pred_new['date'].isin(pd.date_range('2026-07-01', '2026-07-07'))]

        actual_profile = actual_w1.groupby('小时')['actual'].mean()
        pred_profile = pred_w1.groupby('hour')['load_mw'].mean()

        axes[i].plot(range(24), actual_profile.values, 'o-', color=colors[comp], linewidth=2, markersize=4, label='实际')
        axes[i].plot(range(24), pred_profile.values, 's--', color='red', linewidth=2, markersize=4, label='预测(HW+KNN)')

        ymax = max(actual_profile.max(), pred_profile.max())
        axes[i].axvspan(10, 15, alpha=0.1, color='orange')
        axes[i].text(12.5, ymax * 0.95, '午间\n(光伏/天气影响)', ha='center', fontsize=7, color='orange')
        axes[i].set_ylim(0, ymax * 1.1)

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

# 5.3 新旧方法对比柱状图
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
plot_metrics = ['逐时MAE', '日总MAPE']
for i, metric in enumerate(plot_metrics):
    data = df_comparison[df_comparison['指标'] == metric]
    x = np.arange(3)
    width = 0.3
    axes[i].bar(x - width/2, data['旧方法'], width, label='旧方法(XGB+Prophet)', color='gray', alpha=0.7)
    axes[i].bar(x + width/2, data['新方法'], width, label='新方法(HW+KNN)', color='#2563eb', alpha=0.7)
    axes[i].set_xticks(x)
    axes[i].set_xticklabels(['A公司', 'B公司', 'C公司'])
    unit = data['单位'].iloc[0] if len(data) > 0 else ''
    axes[i].set_title(f'{metric} ({unit})', fontweight='bold')
    axes[i].legend(fontsize=8)
    axes[i].grid(True, alpha=0.3, axis='y')

plt.suptitle('新旧方法精度对比 — 7月实际数据', fontsize=13, fontweight='bold')
plt.tight_layout()
plt.savefig('预测输出_v2/method_comparison.png')
plt.close()
print("图3: 新旧方法对比 — 已保存")

# 5.4 每日误差走势 (A公司重点)
fig, ax = plt.subplots(figsize=(14, 5))
a_errors = df_daily_errors[df_daily_errors['公司'] == 'A公司']
x_dates = pd.to_datetime(a_errors['日期'])
ax.plot(x_dates, a_errors['新方法误差%'], 'o-', color='#2563eb', linewidth=1.5, markersize=5, label='新方法(HW+KNN)')
ax.plot(x_dates, a_errors['旧方法误差%'], 's--', color='gray', linewidth=1.5, markersize=5, label='旧方法(XGB+Prophet)')
ax.axhline(y=8, color='green', linestyle=':', alpha=0.6, label='目标线 8%')
ax.set_ylabel('日总误差 %')
ax.set_title('A公司 每日预测误差对比 (MAPE)', fontweight='bold')
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig('预测输出_v2/daily_error_trend.png')
plt.close()
print("图4: A公司每日误差走势 — 已保存")

# ============================================================
# 6. 输出 Excel 报告
# ============================================================

error_note = ('注: 午间(10-15h)误差可能源自光伏出力、气温变化等天气因素；'
              '异常波动可能源自市政调度指令。两项均需额外数据源验证。'
              '建议获取一年以上历史数据 + 天气数据以进一步提升精度。')

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
        预测不确定性_MW=('profile_std_mw', 'mean'),
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
            '趋势分解(日总量) + KNN模板匹配(逐时分配)',
            error_note
        ]
    })

    # 逐时数据
    hourly_out = comp_pred[['datetime', 'hour', 'load_mw', 'daily_total_mwh',
                             'profile_std_mw', 'matched_dates']].copy()
    hourly_out.columns = ['时间', '小时', '预测负荷_MW', '日总量_MWh', '不确定性_MW', '匹配历史日期']
    hourly_out['日期'] = hourly_out['时间'].dt.date

    with pd.ExcelWriter(f'预测输出_v2/{comp}_7月预测.xlsx', engine='openpyxl') as writer:
        daily_report.to_excel(writer, sheet_name='日汇总', index=False)
        monthly_summary.to_excel(writer, sheet_name='月汇总', index=False)
        hourly_out.to_excel(writer, sheet_name='逐时数据', index=False)

    print(f"  {comp}_7月预测.xlsx 已保存")

print("\n" + "="*60)
print("预测完成!")
print("="*60)
print("\n输出文件:")
print("  预测输出_v2/A公司_7月预测.xlsx")
print("  预测输出_v2/B公司_7月预测.xlsx")
print("  预测输出_v2/C公司_7月预测.xlsx")
print("  预测输出_v2/模型对比_v2.csv")
print("  预测输出_v2/每日误差对比.csv")
print("  预测输出_v2/*.png (4张图)")
