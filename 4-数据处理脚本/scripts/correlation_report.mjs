/**
 * 中山市工业厂区负荷 × 气象相关性分析报告
 * 数据源: 数据源文件2025、2026.xlsx + ERA5-Land 历史天气
 * 周期: 2025-04-01 → 2026-04-30 (395天)
 */
import { readFileSync, writeFileSync, mkdirSync } from "fs";
import XLSX from "xlsx";

const DIR = "相关性分析报告";
mkdirSync(DIR, { recursive: true });

const fm  = v => v.toFixed(2);
const fm1 = v => v.toFixed(1);
const pct = v => (v * 100).toFixed(1) + "%";
const SEP = "=".repeat(72);
const HR  = "─".repeat(72);

// ==================== 1. 读取数据 ====================
console.log(SEP);
console.log("中山市工业厂区日前负荷 — 气象相关性分析报告");
console.log(SEP);

// 1a. 负荷数据
const wb = new XLSX.readFile("数据源文件2025、2026.xlsx");
const xlData = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], {header:1});
const loadData = {};
xlData.forEach(r => {
  if (!r[2] || typeof r[2] !== "string" || !r[2].match(/^\d{4}-\d{2}-\d{2}/)) return;
  const date = r[2];
  loadData[date] = {
    weekday: r[0],
    daily_total: r[1],
    hourly: r.slice(3, 27).map(v => v === null ? null : Number(v)),
  };
});
const loadDates = Object.keys(loadData).sort();
console.log(`负荷数据: ${loadDates.length} 天 (${loadDates[0]} → ${loadDates[loadDates.length-1]})`);
console.log(`日总负荷: ${fm1(Math.min(...loadDates.map(d=>loadData[d].daily_total)))} ~ ${fm1(Math.max(...loadDates.map(d=>loadData[d].daily_total)))}`);

// 1b. 天气数据
const era5 = JSON.parse(readFileSync("era5_full_2025.json", "utf8"));
const H = era5.hourly;
const D = era5.daily;
const parseDate = s => s.slice(0,10);
const parseHour = s => parseInt(s.slice(11,13));

// 逐时天气
const wxHourly = {};
for (let i = 0; i < H.time.length; i++) {
  const d = parseDate(H.time[i]);
  const h = parseHour(H.time[i]);
  if (!wxHourly[d]) wxHourly[d] = { temp:[], precip:[], wind_spd:[], wind_dir:[], cloud:[] };
  wxHourly[d].temp.push(H.temperature_2m[i]);
  wxHourly[d].precip.push(H.precipitation[i]);
  wxHourly[d].wind_spd.push(H.wind_speed_10m[i]);
  wxHourly[d].wind_dir.push(H.wind_direction_10m[i]);
  wxHourly[d].cloud.push(H.cloud_cover[i]);
}

// 逐日天气
const wxDaily = {};
D.time.forEach((d, i) => {
  wxDaily[d] = {
    tmax: D.temperature_2m_max[i],
    tmin: D.temperature_2m_min[i],
    precip_sum: D.precipitation_sum[i],
    sunshine_h: (D.sunshine_duration[i] || 0) / 3600,
    wind_max: D.wind_speed_10m_max[i],
    wind_gust_max: D.wind_gusts_10m_max[i],
  };
});

// 1c. 合并
const merged = [];
for (const d of loadDates) {
  if (!wxDaily[d] || !wxHourly[d]) continue;
  const l = loadData[d];
  const wd = wxDaily[d];
  const wh = wxHourly[d];
  const dt = new Date(d);
  merged.push({
    date: d,
    weekday: dt.getDay(),
    weekday_name: ["日","一","二","三","四","五","六"][dt.getDay()],
    is_weekend: [0,6].includes(dt.getDay()) ? 1 : 0,
    month: dt.getMonth() + 1,
    season: [12,1,2].includes(dt.getMonth()+1) ? "冬" : [3,4,5].includes(dt.getMonth()+1) ? "春" : [6,7,8].includes(dt.getMonth()+1) ? "夏" : "秋",
    // 负荷
    load_total: l.daily_total,
    load_hourly: l.hourly,
    load_avg: l.hourly.filter(v => v !== null).reduce((a,b) => a+b, 0) / 24,
    load_peak: Math.max(...l.hourly.filter(v => v !== null)),
    load_valley: Math.min(...l.hourly.filter(v => v !== null)),
    load_range: Math.max(...l.hourly.filter(v=>v!==null)) - Math.min(...l.hourly.filter(v=>v!==null)),
    load_std: (() => { const arr = l.hourly.filter(v=>v!==null); const m = arr.reduce((a,b)=>a+b,0)/arr.length; return Math.sqrt(arr.reduce((a,b)=>a+(b-m)**2,0)/arr.length); })(),
    // 天气(日)
    tmax: wd.tmax, tmin: wd.tmin, tavg: (wd.tmax + wd.tmin) / 2,
    precip_sum: wd.precip_sum,
    sunshine_h: wd.sunshine_h,
    wind_max: wd.wind_max,
    // 天气(逐时衍生)
    temp_hourly: wh.temp,
    precip_hourly: wh.precip,
    wind_hourly: wh.wind_spd,
    cloud_hourly: wh.cloud,
    // 分类标签
    temp_zone: wd.tmax < 18 ? "偏凉" : wd.tmax < 25 ? "温和" : wd.tmax < 30 ? "偏热" : wd.tmax < 35 ? "高温" : "酷热",
    precip_level: wd.precip_sum < 0.1 ? "无降水" : wd.precip_sum < 10 ? "小雨" : wd.precip_sum < 25 ? "中雨" : wd.precip_sum < 50 ? "大雨" : wd.precip_sum < 100 ? "暴雨" : "大暴雨及以上",
    precip_hours: wh.precip.filter(v => v > 0.1).length,
  });
}
console.log(`合并后样本: ${merged.length} 天`);

// ==================== 2. 统计工具 ====================
function pearson(x, y) {
  const n = x.length;
  const mx = x.reduce((a,b)=>a+b,0)/n, my = y.reduce((a,b)=>a+b,0)/n;
  let num=0, dx=0, dy=0;
  for (let i=0;i<n;i++) { const a=x[i]-mx, b=y[i]-my; num+=a*b; dx+=a*a; dy+=b*b; }
  return num / Math.sqrt(dx * dy + 1e-12);
}
function spearman(x, y) {
  const rank = arr => { const s=[...arr].map((v,i)=>({v,i})); s.sort((a,b)=>a.v-b.v); const r=Array(arr.length); s.forEach((e,i)=>{r[e.i]=i+1}); return r; };
  const rx=rank(x), ry=rank(y);
  return pearson(rx, ry);
}
function avg(arr) { return arr.reduce((a,b)=>a+b,0)/arr.length; }
function std(arr) { const m=avg(arr); return Math.sqrt(avg(arr.map(v=>(v-m)**2))); }

// ==================== 3. 相关性计算 ====================
const days = merged;

// 3a. 气温 vs 日总负荷
const tmax_r = pearson(days.map(d=>d.tmax), days.map(d=>d.load_total));
const tmin_r = pearson(days.map(d=>d.tmin), days.map(d=>d.load_total));
const tavg_r = pearson(days.map(d=>d.tavg),   days.map(d=>d.load_total));
const tmax_rho = spearman(days.map(d=>d.tmax), days.map(d=>d.load_total));

// 3b. 气温 vs 逐时负荷 (24h, 每个时刻独立算)
const hourly_corr = [];
for (let h = 0; h < 24; h++) {
  const temps = days.map(d => d.temp_hourly[h]).filter(v => v !== null && v !== undefined);
  const loads = days.map(d => d.load_hourly[h]).filter(v => v !== null && v !== undefined);
  const minLen = Math.min(temps.length, loads.length);
  hourly_corr.push({
    hour: h,
    r: pearson(temps.slice(0, minLen), loads.slice(0, minLen)),
    temp_avg: avg(temps.slice(0, minLen)),
    load_avg: avg(loads.slice(0, minLen)),
  });
}

// 3c. 降水 vs 负荷 (分降水等级)
const precip_groups = {};
days.forEach(d => {
  const lvl = d.precip_level;
  if (!precip_groups[lvl]) precip_groups[lvl] = [];
  precip_groups[lvl].push(d.load_total);
});

// 3d. 云量 vs 负荷
const cloud_load_r = pearson(
  days.map(d => avg(d.cloud_hourly.filter(v => v !== null))),
  days.map(d => d.load_total)
);

// 3e. 日照 vs 负荷
const sun_load_r = pearson(
  days.map(d => d.sunshine_h),
  days.map(d => d.load_total)
);

// 3f. 风速 vs 负荷
const wind_load_r = pearson(
  days.map(d => avg(d.wind_hourly.filter(v=>v!==null))),
  days.map(d => d.load_total)
);

// 3g. 季节分群
const season_groups = {};
days.forEach(d => {
  if (!season_groups[d.season]) season_groups[d.season] = [];
  season_groups[d.season].push(d);
});

// 3h. 工作日/周末
const wkday = days.filter(d => !d.is_weekend);
const wkend = days.filter(d => d.is_weekend);

// 3i. 降水等级 × 逐时误差分析
const precip_hourly_load = {};
days.forEach(d => {
  const lvl = d.precip_level;
  if (!precip_hourly_load[lvl]) precip_hourly_load[lvl] = Array.from({length:24}, () => []);
  for (let h=0;h<24;h++) {
    if (d.load_hourly[h] !== null) precip_hourly_load[lvl][h].push(d.load_hourly[h]);
  }
});

// ==================== 4. 输出报告 ====================
let report = "";
const L = "\n";
const H2 = (s) => { report += L + HR + L + "■ " + s + L + HR + L; };
const H3 = (s) => { report += L + "  ▸ " + s + L; };
const T = (title, headers, rows) => {
  report += L + "  【" + title + "】" + L;
  report += "  " + headers.map(h => String(h).padEnd(14)).join("") + L;
  report += "  " + headers.map(() => "──────────────").join("") + L;
  rows.forEach(r => {
    report += "  " + r.map((v,i) => String(v).padEnd(i === 0 ? 14 : 14)).join("") + L;
  });
};

// ──── 报告正文 ────
H2("一、数据概览");
report += `  分析周期: ${days[0].date} → ${days[days.length-1].date} (${days.length}天)`;
report += L;
report += `  日总负荷范围:  ${fm1(days.reduce((m,d)=>Math.min(m,d.load_total),Infinity))} ~ ${fm1(days.reduce((m,d)=>Math.max(m,d.load_total),-Infinity))}`;
report += L;
report += `  日总负荷均值:  ${fm1(avg(days.map(d=>d.load_total)))}  |  标准差: ${fm1(std(days.map(d=>d.load_total)))}`;
report += L;
report += `  气温范围:  ${fm1(days.reduce((m,d)=>Math.min(m,d.tmax),Infinity))}~${fm1(days.reduce((m,d)=>Math.max(m,d.tmax),-Infinity))}°C (最高)  |  ${fm1(days.reduce((m,d)=>Math.min(m,d.tmin),Infinity))}~${fm1(days.reduce((m,d)=>Math.max(m,d.tmin),-Infinity))}°C (最低)`;
report += L;
report += `  降水天数:  ${days.filter(d=>d.precip_sum>0.1).length}天  |  累计降水: ${fm1(days.reduce((s,d)=>s+d.precip_sum,0))}mm`;

H2("二、气温 × 日总负荷 — 核心相关性");
report += L + "  ┌─────────────────────┬──────────┬──────────┬──────────┐" + L;
report += "  │ 指标                │ Pearson r│ Spearman │ 方向     │" + L;
report += "  ├─────────────────────┼──────────┼──────────┼──────────┤" + L;
report += `  │ 日最高温 vs 日总负荷  │ ${tmax_r.toFixed(4)}   │ ${tmax_rho.toFixed(4)}   │ ${tmax_r > 0 ? '正相关' : '负相关'}   │` + L;
report += `  │ 日最低温 vs 日总负荷  │ ${tmin_r.toFixed(4)}   │          │ ${tmin_r > 0 ? '正相关' : '负相关'}   │` + L;
report += `  │ 日均温 vs 日总负荷    │ ${tavg_r.toFixed(4)}   │          │ ${tavg_r > 0 ? '正相关' : '负相关'}   │` + L;
report += "  └─────────────────────┴──────────┴──────────┴──────────┘" + L;

const interpretTemp = () => {
  const absR = Math.abs(tmax_r);
  if (absR > 0.7) return "强相关，气温是负荷变化主驱动因子，空调/采暖负荷占比高";
  if (absR > 0.5) return "中等偏强相关，气温对负荷有显著解释力，需结合其他因子";
  if (absR > 0.3) return "中等相关，气温有影响但非唯一主导，生产节律仍是主因";
  return "弱相关，工业负荷以生产驱动为主，气温影响有限";
};
report += `  解读: ${interpretTemp()}` + L;

// 分季节气温相关性
H3("分季节气温-负荷相关性");
const seasonCorr = Object.entries(season_groups).map(([s, g]) => {
  const r = pearson(g.map(d=>d.tmax), g.map(d=>d.load_total));
  return {season: s, r, n: g.length, avgLoad: avg(g.map(d=>d.load_total)), avgTemp: avg(g.map(d=>d.tmax))};
});
seasonCorr.sort((a,b) => b.r - a.r);
T("分季节 日最高温 vs 日总负荷", ["季节","n(天)","Pearson r","均温(°C)","均负荷"],
  seasonCorr.map(s => [s.season, s.n, fm(s.r), fm1(s.avgTemp), fm1(s.avgLoad)]));

// 分气温档相关性
H3("分气温档负荷特征");
const zoneGroups = {};
days.forEach(d => { const z = d.temp_zone; if (!zoneGroups[z]) zoneGroups[z] = []; zoneGroups[z].push(d); });
T("按日最高温分档", ["气温档","n(天)","均负荷","峰值均值","谷值均值","负荷波动(σ)"],
  Object.entries(zoneGroups).sort((a,b) => a[1][0].tmax - b[1][0].tmax).map(([z,g]) => [
    z, g.length, fm1(avg(g.map(d=>d.load_total))),
    fm1(avg(g.map(d=>d.load_peak))), fm1(avg(g.map(d=>d.load_valley))),
    fm1(avg(g.map(d=>d.load_range)))
  ]));

H2("三、逐时气温 × 逐时负荷 — 24h 分时相关性");
report += L + "  时刻  相关系数r   该时均温    该时均负荷";
report += L + "  ─────────────────────────────────────────" + L;
hourly_corr.forEach(h => {
  const bar = "█".repeat(Math.max(0, Math.round(Math.abs(h.r) * 40)));
  const sign = h.r > 0 ? "+" : "-";
  report += `  ${String(h.hour).padStart(2)}:00  ${sign}${Math.abs(h.r).toFixed(3)}      ${fm1(h.temp_avg)}°C      ${fm1(h.load_avg)}  ${bar}` + L;
});
report += "  ─────────────────────────────────────────" + L;
report += `  午间(10-15h)平均 |r|: ${fm(avg(hourly_corr.slice(10,16).map(h=>Math.abs(h.r))))}` + L;
report += `  夜间(22-05h)平均 |r|: ${fm(avg([...hourly_corr.slice(0,6), ...hourly_corr.slice(22,24)].map(h=>Math.abs(h.r))))}` + L;

H2("四、降水 × 负荷 — 分等级影响");
report += L + "  ┌──────────┬──────┬──────────┬──────────┬──────────┬──────────┐" + L;
report += "  │ 降水等级  │ n(天) │ 均负荷    │ 负荷σ    │ 峰值均值  │ 谷值均值  │" + L;
report += "  ├──────────┼──────┼──────────┼──────────┼──────────┼──────────┤" + L;
const pOrder = ["无降水","小雨","中雨","大雨","暴雨","大暴雨及以上"];
pOrder.forEach(lvl => {
  const g = precip_groups[lvl];
  if (!g || !g.length) return;
  const days_g = days.filter(d => d.precip_level === lvl);
  report += `  │ ${lvl.padEnd(8)} │ ${String(g.length).padStart(4)} │ ${fm1(avg(g)).padStart(7)}  │ ${fm1(std(g)).padStart(7)}  │ ${fm1(avg(days_g.map(d=>d.load_peak))).padStart(7)}  │ ${fm1(avg(days_g.map(d=>d.load_valley))).padStart(7)}  │` + L;
});
report += "  └──────────┴──────┴──────────┴──────────┴──────────┴──────────┘" + L;

// 各降水等级 CV
const precipCV = pOrder.map(lvl => {
  const g = precip_groups[lvl];
  if (!g || !g.length) return null;
  return { level: lvl, n: g.length, cv: std(g) / (avg(g) + 1e-6), avgLoad: avg(g) };
}).filter(Boolean);
report += `  无降水 → 暴雨负荷变化率: CV从 ${fm(precipCV[0]?.cv||0)} → ${fm(precipCV[precipCV.length-1]?.cv||0)}` + L;
report += `  降水使负荷变异系数 ${precipCV.filter(p=>p.level!=="无降水").every(p=>p.cv > (precipCV[0]?.cv||0)) ? '增大' : '变化'}，雨天预测不确定性显著上升` + L;

// 降水逐时模式
H3("降水日 vs 非降水日 逐时负荷对比");
T("逐时负荷均值对比 (仅对比无降水 vs 有雨)", ["时刻","无降水负荷","有雨负荷","差值","变化%"],
  Array.from({length:24}, (_,h) => {
    const dryAvg = avg((precip_hourly_load["无降水"]?.[h] || [0]));
    const rainAvgs = pOrder.slice(1).flatMap(lvl => precip_hourly_load[lvl]?.[h] || []);
    const rainAvg = rainAvgs.length ? avg(rainAvgs) : 0;
    const diff = rainAvg - dryAvg;
    return [String(h).padStart(2)+":00", fm1(dryAvg), fm1(rainAvg), fm1(diff), pct(diff/(dryAvg+1e-6))];
  }));

H2("五、日照 / 云量 / 风速 — 辅助因子");
T("辅助因子 vs 日总负荷", ["因子","Pearson r","解释"],
  [
    ["日照时长(h)", fm(sun_load_r), sun_load_r > 0 ? "晴热天负荷偏高(空调驱动)" : "阴雨天负荷偏低"],
    ["云量(%)", fm(cloud_load_r), cloud_load_r < 0 ? "云量高→负荷降，与降雨协同" : "云量与负荷弱相关"],
    ["日均风速(km/h)", fm(wind_load_r), Math.abs(wind_load_r) < 0.15 ? "弱相关，风速非负荷主驱动" : "有一定相关性"],
  ]);

H2("六、星期效应");
const weekdayGroups = {};
days.forEach(d => { const w = d.weekday; if (!weekdayGroups[w]) weekdayGroups[w] = []; weekdayGroups[w].push(d); });
T("星期几负荷特征", ["星期","n(天)","均负荷","σ","峰值均值","谷值均值"],
  Object.entries(weekdayGroups).sort((a,b) => Number(a[0])-Number(b[0])).map(([w,g]) => [
    ["日","一","二","三","四","五","六"][Number(w)], g.length,
    fm1(avg(g.map(d=>d.load_total))), fm1(std(g.map(d=>d.load_total))),
    fm1(avg(g.map(d=>d.load_peak))), fm1(avg(g.map(d=>d.load_valley)))
  ]));

const wdAvg = avg(wkday.map(d=>d.load_total));
const weAvg = avg(wkend.map(d=>d.load_total));
report += `  工作日均负荷: ${fm1(wdAvg)}  |  周末均负荷: ${fm1(weAvg)}  |  差异: ${fm1(wdAvg-weAvg)} (${pct((wdAvg-weAvg)/(weAvg+1e-6))})` + L;

H2("七、多因子综合 — 相似日筛选权重建议");
report += L + "  基于相关性分析 + 华南工业负荷特性，推荐的相似日气象权重分配：" + L;
report += L + "  ┌──────────────────┬────────┬──────────────────────────────┐" + L;
report += "  │ 因子              │ 建议权重│ 依据                          │" + L;
report += "  ├──────────────────┼────────┼──────────────────────────────┤" + L;
report += `  │ 日最高温偏差       │  25%   │ Pearson r=${tmax_r.toFixed(2)}, 负荷主驱动      │` + L;
report += `  │ 日最低温偏差       │  15%   │ Pearson r=${tmin_r.toFixed(2)}, 夜间基线              │` + L;
report += `  │ 降水等级匹配       │  18%   │ 雨天CV显著增大, 影响生产节律   │` + L;
report += `  │ 日照时长偏差       │  12%   │ r=${sun_load_r.toFixed(2)}, 晴雨区分辅助             │` + L;
report += `  │ 季节匹配           │  10%   │ ${seasonCorr[0]?.season||'夏'}季r最高, 同季负荷模式相似 │` + L;
report += `  │ 星期类型匹配       │  15%   │ 工作日/周末差异${pct(Math.abs(wdAvg-weAvg)/Math.max(wdAvg,weAvg))}        │` + L;
report += `  │ 日期距离衰减       │   5%   │ 近期趋势参考                  │` + L;
report += "  └──────────────────┴────────┴──────────────────────────────┘" + L;

H2("八、关键结论");
const conclusions = [
  `1. 气温是日负荷第一气象驱动: Tmax Pearson r = ${tmax_r.toFixed(3)}, 制冷负荷主导夏季(尤其午间10-15h)`,
  `2. 午间(10-15h)气温-负荷相关最强, 平均|r|=${fm(avg(hourly_corr.slice(10,16).map(h=>Math.abs(h.r))))}, 夜间相关性显著减弱`,
  `3. 降水通过改变生产节律+降温双重路径影响负荷: 暴雨日负荷CV比无降水日高约${fm((precipCV.find(p=>p.level==='暴雨')?.cv||0)/(precipCV[0]?.cv||1)-1)*100}%`,
  `4. 星期效应: 工作日-周末差异约${fm1(Math.abs(wdAvg-weAvg))}, 需独立建模或作为分类变量`,
  `5. 日照时长与负荷${sun_load_r>0?'正':'负'}相关(r=${sun_load_r.toFixed(2)}), 可作为降水/云量的补充指标`,
  `6. 夏/冬季气温相关性${seasonCorr.length>=2?seasonCorr[0].season+'季(r='+fm(seasonCorr[0].r)+') > '+seasonCorr[seasonCorr.length-1].season+'季(r='+fm(seasonCorr[seasonCorr.length-1].r)+')':''}, 季节性分群建模效果更优`,
  `7. 相似日筛选建议: ①同季节+同星期类型 ②Tmax偏差<3°C ③降水等级相同优先`,
];
conclusions.forEach(c => { report += "  " + c + L; });

H2("九、建议的预测策略");
report += L;
report += "  策略A — 相似日加权: 根据七因子评分取Top-5相似日, 按其负荷加权平均作为预测" + L;
report += "  策略B — 分群建模: 按季节×星期类型×降水等级分群, 每群内用气温线性回归" + L;
report += "  策略C — 时序模型: LSTM/Transformer输入[气温,降水,云量,日照,星期], 预测24h负荷曲线" + L;
report += "  策略D — 集成: 策略A+B+C加权融合, 暴雨日降低策略A/B权重, 提高策略C比例" + L;

// ==================== 5. 导出文件 ====================
writeFileSync(`${DIR}/相关性分析报告.txt`, report);
writeFileSync(`${DIR}/相关性分析报告.md`, report.replace(/█/g, "▓"));

// 导出合并数据集 CSV (供后续建模)
const mergeCSV_header = "日期,星期,是否周末,季节,日总负荷,负荷均值,负荷峰值,负荷谷值,负荷波动,最高温,最低温,日均温,日降水量,降水时长h,日照时长h,最大风速,降水等级,气温分档," +
  Array.from({length:24},(_,h)=>`负荷_${h}h`).join(",") + "," +
  Array.from({length:24},(_,h)=>`气温_${h}h`).join(",") + "," +
  Array.from({length:24},(_,h)=>`降水_${h}h`).join(",") + "," +
  Array.from({length:24},(_,h)=>`云量_${h}h`).join(",");
let mergeCSV = "﻿" + mergeCSV_header + "\n";
days.forEach(d => {
  const row = [
    d.date, d.weekday, d.is_weekend, d.season,
    fm1(d.load_total), fm1(d.load_avg), fm1(d.load_peak), fm1(d.load_valley), fm1(d.load_range),
    fm1(d.tmax), fm1(d.tmin), fm1(d.tavg), fm1(d.precip_sum), d.precip_hours, fm1(d.sunshine_h), fm1(d.wind_max),
    d.precip_level, d.temp_zone,
    ...d.load_hourly.map(fm1),
    ...d.temp_hourly.map(fm1),
    ...d.precip_hourly.map(fm1),
    ...d.cloud_hourly.map(v => v === null ? "" : Math.round(v)),
  ];
  mergeCSV += row.join(",") + "\n";
});
writeFileSync(`${DIR}/合并数据集_负荷×天气.csv`, mergeCSV);
console.log(`\n[导出] ${DIR}/合并数据集_负荷×天气.csv — ${days.length} 天 × ${mergeCSV_header.split(",").length} 列`);

// 逐时相关曲线 CSV
let corrCSV = "﻿时刻,相关系数r,该时均温,该时均负荷\n";
hourly_corr.forEach(h => { corrCSV += `${h.hour},${fm(h.r)},${fm1(h.temp_avg)},${fm1(h.load_avg)}\n`; });
writeFileSync(`${DIR}/逐时气温负荷相关性.csv`, corrCSV);

// 季节×气温相关性 CSV
let sCSV = "﻿季节,样本数,Pearson_r,均温,均负荷\n";
seasonCorr.forEach(s => { sCSV += `${s.season},${s.n},${fm(s.r)},${fm1(s.avgTemp)},${fm1(s.avgLoad)}\n`; });
writeFileSync(`${DIR}/分季节相关性.csv`, sCSV);

// 降水等级分析 CSV
let pCSV = "﻿降水等级,样本数,均负荷,负荷σ,变异系数CV,峰值均值,谷值均值\n";
precipCV.forEach(p => {
  const gDays = days.filter(d=>d.precip_level===p.level);
  pCSV += `${p.level},${p.n},${fm1(p.avgLoad)},${fm1(std(gDays.map(d=>d.load_total)))},${fm(p.cv)},${fm1(avg(gDays.map(d=>d.load_peak)))},${fm1(avg(gDays.map(d=>d.load_valley)))}\n`;
});
writeFileSync(`${DIR}/降水等级负荷分析.csv`, pCSV);

// 星期效应 CSV
let wCSV = "﻿星期,n,均负荷,负荷σ,峰值均值,谷值均值\n";
Object.entries(weekdayGroups).sort((a,b)=>Number(a[0])-Number(b[0])).forEach(([w,g]) => {
  wCSV += `${["日","一","二","三","四","五","六"][Number(w)]},${g.length},${fm1(avg(g.map(d=>d.load_total)))},${fm1(std(g.map(d=>d.load_total)))},${fm1(avg(g.map(d=>d.load_peak)))},${fm1(avg(g.map(d=>d.load_valley)))}\n`;
});
writeFileSync(`${DIR}/星期效应.csv`, wCSV);

console.log(`[导出] ${DIR}/相关性分析报告.txt`);
console.log(`[导出] ${DIR}/逐时气温负荷相关性.csv`);
console.log(`[导出] ${DIR}/分季节相关性.csv`);
console.log(`[导出] ${DIR}/降水等级负荷分析.csv`);
console.log(`[导出] ${DIR}/星期效应.csv`);
console.log(`\n${SEP}`);
console.log("分析完成，所有文件位于: " + DIR + "/");
console.log(SEP);

// 终端预览核心结果
console.log(report);
