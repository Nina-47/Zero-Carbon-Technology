"""
预计算全部日期的 Top-5 相似日 → JSON，供前端查表使用。
"""
import sys, os
sys.path.insert(0, '.')
import pandas as pd, numpy as np, json
from datetime import datetime
from collections import defaultdict

xlsx_path = 'data/weather_seed.xlsx'
df = pd.read_excel(xlsx_path, sheet_name='全要素天气表_长格式_v2')
df.columns = ['date', 'element'] + list(range(24))

element_map = {
    '气温(℃)': 'temperature_2m',
    '降水量(mm)': 'precipitation',
    '风速(km/h)': 'wind_speed_10m',
    '风向(°)': 'wind_direction_10m',
    '云量(%)': 'cloud_cover',
    '太阳总辐射(MJ/m²)': 'shortwave_radiation',
}

records = defaultdict(dict)
for _, row in df.iterrows():
    date_val = str(row['date'])[:10]
    element = str(row['element'])
    col_name = element_map.get(element)
    if col_name is None:
        continue
    for h in range(24):
        val = row[h]
        if pd.isna(val):
            continue
        key = f"{date_val}_{h}"
        records[key]['date'] = date_val
        records[key]['hour'] = h
        records[key][col_name] = float(val)

daily = defaultdict(lambda: {
    'temps': [], 'precips': [], 'rads': [],
    'winds': [], 'clouds': [],
})
for key, vals in records.items():
    d = vals['date']
    if 'temperature_2m' in vals:
        daily[d]['temps'].append(vals['temperature_2m'])
        daily[d]['precips'].append(vals.get('precipitation', 0))
        daily[d]['rads'].append(vals.get('shortwave_radiation', 0))
        daily[d]['winds'].append(vals.get('wind_speed_10m', 0))
        daily[d]['clouds'].append(vals.get('cloud_cover', 0))

dates = sorted(daily.keys())
print(f"Total days: {len(dates)}, range: {dates[0]} ~ {dates[-1]}")

features = {}
for d in dates:
    dd = daily[d]
    features[d] = {
        'tmax': np.max(dd['temps']),
        'tmin': np.min(dd['temps']),
        'tavg': np.mean(dd['temps']),
        'precip_sum': np.sum(dd['precips']),
        'rad_sum': np.sum(dd['rads']),
        'wind_avg': np.mean(dd['winds']),
        'cloud_avg': np.mean(dd['clouds']),
    }

def precip_level(p):
    if p < 0.1: return 0
    if p < 1.0: return 1
    if p < 10: return 2
    if p < 25: return 3
    if p < 50: return 4
    return 5

def season_idx(date_str):
    m = int(date_str[5:7])
    if m in [12, 1, 2]: return 0
    if m in [3, 4, 5]: return 1
    if m in [6, 7, 8]: return 2
    return 3

def weekday_idx(date_str):
    return datetime.strptime(date_str, '%Y-%m-%d').weekday()

feature_names = ['tmax', 'tmin', 'precip_sum', 'rad_sum', 'wind_avg', 'cloud_avg']
stats = {}
for fn in feature_names:
    vals = [features[d][fn] for d in dates]
    stats[fn] = {'mean': np.mean(vals), 'std': np.std(vals) or 1.0}

def zscore(val, fn):
    return (val - stats[fn]['mean']) / stats[fn]['std']

weights = {
    'tmin': 0.25, 'tmax': 0.20, 'precip': 0.18,
    'season': 0.12, 'date_decay': 0.10, 'dew': 0.10, 'weekday': 0.05,
}

def season_dist(d1, d2):
    s1, s2 = season_idx(d1), season_idx(d2)
    if s1 == s2: return 0
    if abs(s1 - s2) == 2: return 1.0
    return 0.5

def weekday_dist(d1, d2):
    w1 = 1 if weekday_idx(d1) >= 5 else 0
    w2 = 1 if weekday_idx(d2) >= 5 else 0
    return 0.0 if w1 == w2 else 1.0

def date_decay(d1, d2):
    delta = abs((datetime.strptime(d1, '%Y-%m-%d') - datetime.strptime(d2, '%Y-%m-%d')).days)
    if delta <= 90:
        return 0.0
    return float(1.0 - np.exp(-(delta - 90) / 180.0))

def precip_dist(p1, p2):
    diff = abs(p1 - p2)
    if diff <= 1.0:
        cont = diff / 5.0
    elif diff <= 10.0:
        cont = 0.2 + (diff - 1.0) / 45.0
    else:
        cont = min(0.4 + (diff - 10.0) / 200.0, 0.7)
    lvl_diff = abs(precip_level(p1) - precip_level(p2)) / 5.0
    return 0.7 * cont + 0.3 * lvl_diff

SCALE = 5.0
all_results = {}

for i, target_d in enumerate(dates):
    if i % 100 == 0:
        print(f"Processing {i}/{len(dates)}: {target_d}")

    tf = features[target_d]
    target_is_rainy = tf['precip_sum'] >= 0.5

    distances = []
    for cand_d in dates:
        if cand_d == target_d:
            continue
        cf = features[cand_d]
        if target_is_rainy and cf['precip_sum'] < 0.3:
            continue

        d_num = (
            weights['tmax'] * SCALE * abs(zscore(tf['tmax'], 'tmax') - zscore(cf['tmax'], 'tmax')) +
            weights['tmin'] * SCALE * abs(zscore(tf['tmin'], 'tmin') - zscore(cf['tmin'], 'tmin')) +
            weights['dew'] * SCALE * abs(zscore(tf['tavg'], 'tmax') - zscore(cf['tavg'], 'tmax')) +
            weights['dew'] * SCALE * abs(zscore(tf['cloud_avg'], 'cloud_avg') - zscore(cf['cloud_avg'], 'cloud_avg'))
        )

        d_disc = (
            weights['precip'] * precip_dist(tf['precip_sum'], cf['precip_sum']) +
            weights['season'] * season_dist(target_d, cand_d) +
            weights['weekday'] * weekday_dist(target_d, cand_d) +
            weights['date_decay'] * date_decay(target_d, cand_d)
        )

        total = d_num + d_disc
        distances.append((cand_d, total))

    distances.sort(key=lambda x: x[1])
    top5 = distances[:5]

    sigma = float(np.median([d[1] for d in distances])) if distances else 1.0
    if sigma < 0.001:
        sigma = 1.0

    all_results[target_d] = []
    for cand_d, dist in top5:
        sim = max(0.0, round(100.0 * np.exp(-dist / sigma), 1))
        cf = features[cand_d]
        all_results[target_d].append({
            'date': cand_d,
            'similarity_pct': sim,
            'distance': round(dist, 4),
            'tmax': round(cf['tmax'], 1),
            'tmin': round(cf['tmin'], 1),
            'precip_sum': round(cf['precip_sum'], 1),
            'rad_sum': round(cf['rad_sum'], 1),
            'precip_level': precip_level(cf['precip_sum']),
            'season': season_idx(cand_d),
            'weekday': weekday_idx(cand_d),
        })

# 验证
for td in ['2025-07-15', '2025-10-15', '2026-01-15', '2025-08-03']:
    print(f"\n=== {td} ===")
    tf = features[td]
    print(f"  tmax={tf['tmax']:.1f}, tmin={tf['tmin']:.1f}, precip={tf['precip_sum']:.1f}, rad={tf['rad_sum']:.1f}")
    for r in all_results[td][:3]:
        print(f"  -> {r['date']}  sim={r['similarity_pct']}%  dist={r['distance']}  tmax={r['tmax']}  tmin={r['tmin']}  precip={r['precip_sum']}")

output = {
    'generated': datetime.now().isoformat(),
    'total_days': len(all_results),
    'top_n': 5,
    'features': {d: {k: round(v, 2) if isinstance(v, float) else v for k, v in feat.items()} for d, feat in features.items()},
    'results': all_results,
}
with open('data/similarity_results.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

size = os.path.getsize('data/similarity_results.json')
print(f"\nSaved: data/similarity_results.json ({size/1024:.0f}KB)")
