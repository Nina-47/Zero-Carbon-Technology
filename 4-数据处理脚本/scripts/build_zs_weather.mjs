/**
 * 中山市历史天气数据 — 2025-01-01 至今
 * 输出格式: 横24小时 × 纵(每天×每因子)
 *
 * 因子:
 *   逐时 — 气温 / 降水量 / 风速 / 风向 / 云量 / 太阳总辐射
 *   逐日 — 最高温 / 最低温 / 日降水量 / 太阳总辐射 / 最大风速
 */
import { readFileSync, writeFileSync } from "fs";

const DIR = "中山市历史天气数据";
const fm = v => (v === null || v === undefined) ? "" : v.toFixed(1);
const fi = v => (v === null || v === undefined) ? "" : Math.round(v);
const fr = v => (v === null || v === undefined) ? "" : v.toFixed(3);

// ==================== 1. 读取 ====================
const raw = JSON.parse(readFileSync("era5_full_2025.json", "utf8"));
const radRaw = JSON.parse(readFileSync("era5_radiation.json", "utf8"));
const H = raw.hourly;
const D = raw.daily;

const parseDate = s => s.slice(0, 10);
const parseHour = s => parseInt(s.slice(11, 13));
const times = H.time;
const hours = times.map(parseHour);
const dates = times.map(parseDate);

// 辐射查找表
const radMap = {};
for (let i = 0; i < radRaw.hourly.time.length; i++) {
  const d = radRaw.hourly.time[i].slice(0, 10);
  const h = parseInt(radRaw.hourly.time[i].slice(11, 13));
  if (!radMap[d]) radMap[d] = new Array(24).fill(null);
  radMap[d][h] = radRaw.hourly.shortwave_radiation_MJpm2[i];
}

// ==================== 2. 构建逐时宽表 (按日×因子) ====================
const dayMap = {};
for (let i = 0; i < times.length; i++) {
  const d = dates[i];
  const h = hours[i];
  if (!dayMap[d]) {
    dayMap[d] = {
      temp:     new Array(24).fill(null),
      precip:   new Array(24).fill(null),
      wind_spd: new Array(24).fill(null),
      wind_dir: new Array(24).fill(null),
      cloud:    new Array(24).fill(null),
      radiation:new Array(24).fill(null),
    };
  }
  dayMap[d].temp[h]     = H.temperature_2m[i];
  dayMap[d].precip[h]   = H.precipitation[i];
  dayMap[d].wind_spd[h] = H.wind_speed_10m[i];
  dayMap[d].wind_dir[h] = H.wind_direction_10m[i];
  dayMap[d].cloud[h]    = H.cloud_cover[i];
}

// 填充辐射
for (const d of Object.keys(dayMap)) {
  const r24 = radMap[d];
  if (r24) {
    for (let h = 0; h < 24; h++) {
      dayMap[d].radiation[h] = r24[h] ?? null;
    }
  }
}

// ==================== 3. 构建逐日摘要 ====================
const dailyMap = {};
D.time.forEach((d, i) => {
  dailyMap[d] = {
    date: d,
    tmax: D.temperature_2m_max[i],
    tmin: D.temperature_2m_min[i],
    precip_sum: D.precipitation_sum[i],
    wind_max: D.wind_speed_10m_max[i],
    wind_gust_max: D.wind_gusts_10m_max[i],
  };
});

// 辐射日总和
for (const d of Object.keys(dailyMap)) {
  const r24 = radMap[d];
  if (r24) {
    dailyMap[d].radiation_sum = r24.reduce((a, b) => (a ?? 0) + (b ?? 0), 0);
  } else {
    dailyMap[d].radiation_sum = null;
  }
}

// ==================== 4. 导出 ====================

// --- 4a. 逐时宽表 (每个因子一张sheet，横24h纵每天) ---
function exportHourlyWide(factorKey, filename, precision = 1, fmtFn = null) {
  const fmt = fmtFn || (precision === 0 ? fi : fm);
  const days = Object.keys(dayMap).sort();
  const header = "日期," + Array.from({length:24},(_,h)=>`${String(h).padStart(2,"0")}:00`).join(",");
  let csv = "﻿" + header + "\n";
  for (const d of days) {
    const row = dayMap[d][factorKey];
    csv += d + "," + row.map(v => fmt(v)).join(",") + "\n";
  }
  writeFileSync(`${DIR}/${filename}`, csv);
  console.log(`  [导出] ${filename} — ${days.length} 天`);
}

exportHourlyWide("temp",      "气温逐时表_℃.csv",          1);
exportHourlyWide("precip",    "降水量逐时表_mm.csv",        1);
exportHourlyWide("wind_spd",  "风速逐时表_kmh.csv",         1);
exportHourlyWide("wind_dir",  "风向逐时表_°.csv",           0);
exportHourlyWide("cloud",     "云量逐时表_pct.csv",         0);
exportHourlyWide("radiation", "太阳总辐射逐时表_MJpm2.csv", 3, fr);

// --- 4b. 全变量总装表 (每个因子24h横排) ---
const days = Object.keys(dayMap).sort();
const hh = Array.from({length:24},(_,h)=>String(h).padStart(2,"0"));
const megaCols = [
  "日期",
  ...hh.map(h => `气温_${h}h`),
  ...hh.map(h => `降水_${h}h`),
  ...hh.map(h => `风速_${h}h`),
  ...hh.map(h => `风向_${h}h`),
  ...hh.map(h => `云量_${h}h`),
  ...hh.map(h => `辐射_${h}h`),
];
let megaCSV = "﻿" + megaCols.join(",") + "\n";
for (const d of days) {
  const r = dayMap[d];
  const row = [
    d,
    ...r.temp.map(fm),
    ...r.precip.map(fm),
    ...r.wind_spd.map(fm),
    ...r.wind_dir.map(fi),
    ...r.cloud.map(fi),
    ...r.radiation.map(fr),
  ];
  megaCSV += row.join(",") + "\n";
}
writeFileSync(`${DIR}/逐时全变量宽表.csv`, megaCSV);
console.log(`  [导出] 逐时全变量宽表.csv — ${days.length} 天 × ${megaCols.length - 1} 列`);

// --- 4c. 逐日摘要表 ---
let dailyCSV = "﻿日期,最高温,最低温,日降水量,太阳总辐射_MJpm2,最大风速,最大阵风\n";
const dailyDays = Object.keys(dailyMap).sort();
for (const d of dailyDays) {
  const r = dailyMap[d];
  dailyCSV += `${r.date},${fm(r.tmax)},${fm(r.tmin)},${fm(r.precip_sum)},${fr(r.radiation_sum)},${fm(r.wind_max)},${fm(r.wind_gust_max)}\n`;
}
writeFileSync(`${DIR}/逐日摘要表.csv`, dailyCSV);
console.log(`  [导出] 逐日摘要表.csv — ${dailyDays.length} 天`);

// ==================== 5. 统计摘要 ====================
const SEP = "=".repeat(65);
console.log(`\n${SEP}`);
console.log("中山市 2025-01-01 → 2026-07-29 天气数据统计");
console.log(SEP);

const allT = dailyDays.map(d => dailyMap[d]);
const tmaxs = allT.map(r => r.tmax).filter(v => v !== null);
const tmins = allT.map(r => r.tmin).filter(v => v !== null);
const precipSum = allT.map(r => r.precip_sum).filter(v => v !== null);
const radSums = allT.map(r => r.radiation_sum).filter(v => v !== null);
const windMax = allT.map(r => r.wind_max).filter(v => v !== null);

const p = (arr, q) => { const s = [...arr].sort((a,b)=>a-b); return s[Math.floor(s.length*q/100)]; };

console.log(`  数据跨度: ${dailyDays[0]} → ${dailyDays[dailyDays.length-1]} (${dailyDays.length} 天)`);
console.log(`  气温范围: ${Math.min(...tmaxs).toFixed(1)} ~ ${Math.max(...tmaxs).toFixed(1)}°C (最高)  |  ${Math.min(...tmins).toFixed(1)} ~ ${Math.max(...tmins).toFixed(1)}°C (最低)`);
console.log(`  气温中位: 最高 ${p(tmaxs,50).toFixed(1)}°C  |  最低 ${p(tmins,50).toFixed(1)}°C`);
console.log(`  降水概况: 累计 ${precipSum.reduce((a,b)=>a+b,0).toFixed(0)}mm  日均 ${(precipSum.reduce((a,b)=>a+b,0)/dailyDays.length).toFixed(2)}mm  最大日 ${Math.max(...precipSum).toFixed(1)}mm`);
console.log(`  太阳总辐射: 日均 ${(radSums.reduce((a,b)=>a+b,0)/radSums.length).toFixed(2)} MJ/m²  最大日 ${Math.max(...radSums).toFixed(2)} MJ/m²  最小日 ${Math.min(...radSums).toFixed(2)} MJ/m²`);
console.log(`  风速极值: 最大日风速 ${Math.max(...windMax).toFixed(1)} km/h`);

// 月度统计
console.log(`\n  月度速览:`);
console.log(`  月份    天数  均温    最高   最低   月降水mm  辐射日均   有雨天`);
for (let m = 1; m <= 7; m++) {
  for (const yr of [2025, 2026]) {
    const md = allT.filter(r => r.date.startsWith(`${yr}-${String(m).padStart(2,"0")}`));
    if (!md.length) continue;
    const avgT = md.reduce((s,r) => s + (r.tmax + r.tmin)/2, 0) / md.length;
    const sumP = md.reduce((s,r) => s + r.precip_sum, 0);
    const avgR = md.reduce((s,r) => s + (r.radiation_sum ?? 0), 0) / md.length;
    const rainD = md.filter(r => r.precip_sum > 0.1).length;
    console.log(`  ${yr}-${String(m).padStart(2,"0")}  ${md.length}天  ${avgT.toFixed(1)}   ${Math.max(...md.map(r=>r.tmax)).toFixed(1)}   ${Math.min(...md.map(r=>r.tmin)).toFixed(1)}   ${sumP.toFixed(0).padStart(6)}   ${avgR.toFixed(1).padStart(6)}   ${rainD}天`);
  }
}

for (let m = 8; m <= 12; m++) {
  const md = allT.filter(r => r.date.startsWith(`2025-${String(m).padStart(2,"0")}`));
  if (!md.length) continue;
  const avgT = md.reduce((s,r) => s + (r.tmax + r.tmin)/2, 0) / md.length;
  const sumP = md.reduce((s,r) => s + r.precip_sum, 0);
  const avgR = md.reduce((s,r) => s + (r.radiation_sum ?? 0), 0) / md.length;
  const rainD = md.filter(r => r.precip_sum > 0.1).length;
  console.log(`  2025-${String(m).padStart(2,"0")}  ${md.length}天  ${avgT.toFixed(1)}   ${Math.max(...md.map(r=>r.tmax)).toFixed(1)}   ${Math.min(...md.map(r=>r.tmin)).toFixed(1)}   ${sumP.toFixed(0).padStart(6)}   ${avgR.toFixed(1).padStart(6)}   ${rainD}天`);
}

console.log(`\n${SEP}`);
console.log(`全部文件已保存至: ${DIR}/`);
console.log(`  气温逐时表_℃.csv              — 横24h × 纵N天 (每格=气温℃)`);
console.log(`  降水量逐时表_mm.csv            — 横24h × 纵N天 (每格=降水mm)`);
console.log(`  风速逐时表_kmh.csv             — 横24h × 纵N天 (每格=风速km/h)`);
console.log(`  风向逐时表_°.csv               — 横24h × 纵N天 (每格=风向°)`);
console.log(`  云量逐时表_pct.csv             — 横24h × 纵N天 (每格=云量%)`);
console.log(`  太阳总辐射逐时表_MJpm2.csv     — 横24h × 纵N天 (每格=太阳总辐射MJ/m²)`);
console.log(`  逐时全变量宽表.csv             — 总装表 (145列 = 6因子×24h + 日期)`);
console.log(`  逐日摘要表.csv                 — 每日最高/最低温 + 降水 + 太阳总辐射 + 风速`);
console.log(SEP);
