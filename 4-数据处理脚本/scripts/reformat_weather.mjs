/**
 * 重整格式: 每天6行(6因子) × 横24h
 * 因子: 气温 / 降水量 / 风速 / 风向 / 云量 / 太阳总辐射(替代原日照时长)
 * 输出: 全要素天气表_长格式_v2.csv
 */
import { readFileSync, writeFileSync } from "fs";

const raw = JSON.parse(readFileSync("era5_full_2025.json", "utf8"));
const radRaw = JSON.parse(readFileSync("era5_radiation.json", "utf8"));
const H = raw.hourly;
const D = raw.daily;

const parseDate = s => s.slice(0, 10);
const parseHour = s => parseInt(s.slice(11, 13));

const times = H.time;
const hours = times.map(parseHour);
const dates = times.map(parseDate);

// 构建辐射查找表: "YYYY-MM-DD" → [24h值]
const radMap = {};
for (let i = 0; i < radRaw.hourly.time.length; i++) {
  const d = radRaw.hourly.time[i].slice(0, 10);
  const h = parseInt(radRaw.hourly.time[i].slice(11, 13));
  if (!radMap[d]) radMap[d] = new Array(24).fill(null);
  radMap[d][h] = radRaw.hourly.shortwave_radiation_MJpm2[i];
}

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
      radiation: new Array(24).fill(null),  // 逐时独立辐射值
    };
  }
  dayMap[d].temp[h]     = H.temperature_2m[i];
  dayMap[d].precip[h]   = H.precipitation[i];
  dayMap[d].wind_spd[h] = H.wind_speed_10m[i];
  dayMap[d].wind_dir[h] = H.wind_direction_10m[i];
  dayMap[d].cloud[h]    = H.cloud_cover[i];
}

// 填充辐射（逐时独立值，每个小时不同）
for (const d of Object.keys(dayMap)) {
  const rad24 = radMap[d];
  if (rad24) {
    for (let h = 0; h < 24; h++) {
      dayMap[d].radiation[h] = rad24[h] ?? null;
    }
  }
}

const fm = v => (v === null || v === undefined) ? "" : v.toFixed(1);
const fi = v => (v === null || v === undefined) ? "" : Math.round(v);
const fr = v => (v === null || v === undefined) ? "" : v.toFixed(3);  // 辐射用3位小数

const days = Object.keys(dayMap).sort();

const hh = Array.from({length:24}, (_,h) => `${String(h).padStart(2,"0")}:00`);
const header = "日期,要素," + hh.join(",");

let csv = "﻿" + header + "\n";

const factors = [
  { key: "temp",      name: "气温(℃)",           fmt: fm },
  { key: "precip",    name: "降水量(mm)",         fmt: fm },
  { key: "wind_spd",  name: "风速(km/h)",         fmt: fm },
  { key: "wind_dir",  name: "风向(°)",            fmt: fi },
  { key: "cloud",     name: "云量(%)",            fmt: fi },
  { key: "radiation", name: "太阳总辐射(MJ/m²)",  fmt: fr },
];

for (const d of days) {
  for (const f of factors) {
    const row = [d, f.name, ...dayMap[d][f.key].map(f.fmt)];
    csv += row.join(",") + "\n";
  }
}

writeFileSync("中山市历史天气数据/全要素天气表_长格式_v2.csv", csv);

const totalRows = days.length * factors.length;
console.log(`[导出] 全要素天气表_长格式_v2.csv`);
console.log(`  格式: ${days.length} 天 × ${factors.length} 要素 = ${totalRows} 行`);
console.log(`  列数: 日期 + 要素名 + 24h = 26 列`);
console.log(`  要素: ${factors.map(f=>f.name).join(" | ")}`);
console.log(``);
console.log(`  示例 (第1天, 仅显示前8h):`);
const lines = csv.split("\n");
console.log(`  ${lines[0].split(",").slice(0,10).join("  ")}`);
for (let i = 1; i <= factors.length && i < lines.length; i++) {
  console.log(`  ${lines[i].split(",").slice(0,10).join("  ")}`);
}
console.log(`  ... (共 ${totalRows} 行)`);

// 辐射统计
const allRadDaily = [];
for (const d of days) {
  const r24 = dayMap[d].radiation.filter(v => v !== null);
  if (r24.length > 0) {
    allRadDaily.push(r24.reduce((a,b) => a + b, 0));
  }
}
console.log(``);
console.log(`  太阳总辐射统计: 日均 ${(allRadDaily.reduce((a,b)=>a+b,0)/allRadDaily.length).toFixed(2)} MJ/m²  |  最小 ${Math.min(...allRadDaily).toFixed(2)}  |  最大 ${Math.max(...allRadDaily).toFixed(2)} MJ/m²`);
