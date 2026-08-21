/**
 * 光伏发电因素相关性分析 — 数据合并与特征工程
 * 合并: 光伏一期发电数据 + 全要素天气数据
 * 输出: 合并数据集_光伏×天气.csv
 */
import { readFileSync, writeFileSync } from "fs";
import XLSX from "xlsx";

const DIR = "光伏发电因素相关性分析";
const PV_FILE = `${DIR}/光伏数据部分.xlsx`;
const WX_FILE = `${DIR}/全要素天气表.xlsx`;
const OUTPUT_CSV = `${DIR}/合并数据集_光伏×天气.csv`;

const fm = v => (v === null || v === undefined) ? "" : v.toFixed(2);
const fm1 = v => (v === null || v === undefined) ? "" : v.toFixed(1);

// ==================== 1. 读取光伏数据 (一期) ====================
console.log("=".repeat(60));
console.log("光伏发电因素相关性分析 — 数据合并");
console.log("=".repeat(60));

const pvWb = XLSX.readFile(PV_FILE);
const pvSheet = pvWb.Sheets["污水处理厂8MWp光伏电站(一期)"];
const pvRaw = XLSX.utils.sheet_to_json(pvSheet, { header: 1 });

const toISO = s => {
  const d = new Date((s - 25569) * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
};

const pvData = {};
pvRaw.slice(1).forEach(r => {
  if (!r[0] || typeof r[0] !== "number") return;
  const date = toISO(r[0]);
  const totalGen = r[2];  // 总发电量(kWh)
  const hourly = r.slice(3, 27).map(v => v === null ? 0 : Number(v)); // 0-23h
  const capacity_kW = 8000;
  pvData[date] = {
    date,
    total_kWh: totalGen,
    hourly_kWh: hourly,
    capacity_factor: totalGen / (capacity_kW * 24),  // 日利用率
    peak_kW: Math.max(...hourly),
    gen_hours: hourly.filter(v => v > 0).length,      // 有效发电小时数
  };
});
const pvDates = Object.keys(pvData).sort();
console.log(`光伏一期: ${pvDates.length} 天 (${pvDates[0]} → ${pvDates[pvDates.length-1]})`);

// ==================== 2. 读取天气数据 ====================
const wxWb = XLSX.readFile(WX_FILE);

// 2a. 逐时天气(长格式)
const wxLong = XLSX.utils.sheet_to_json(wxWb.Sheets["全要素天气表_长格式_v2"], { header: 1 });
const wxHourly = {};
for (let i = 1; i < wxLong.length; i++) {
  const r = wxLong[i];
  const dateSerial = r[0];
  const factor = r[1];
  const date = toISO(dateSerial);
  if (!wxHourly[date]) wxHourly[date] = {};
  const values = r.slice(2, 26).map(v => v === "" || v === null ? null : Number(v));
  // Map factor names to keys
  if (factor.includes("气温")) wxHourly[date].temp = values;
  else if (factor.includes("降水")) wxHourly[date].precip = values;
  else if (factor.includes("风速")) wxHourly[date].wind_spd = values;
  else if (factor.includes("风向")) wxHourly[date].wind_dir = values;
  else if (factor.includes("云量")) wxHourly[date].cloud = values;
  else if (factor.includes("太阳总辐射")) wxHourly[date].radiation = values;
}

// 2b. 逐日摘要表
const wxDailySheet = XLSX.utils.sheet_to_json(wxWb.Sheets["逐日摘要表"], { header: 1 });
const wxDaily = {};
wxDailySheet.slice(1).forEach(r => {
  const date = toISO(r[0]);
  wxDaily[date] = {
    tmax: r[1], tmin: r[2], precip_sum: r[3],
    radiation_sum: r[4], wind_max: r[5], wind_gust_max: r[6],
  };
});

console.log(`天气数据: ${Object.keys(wxHourly).length} 天逐时  |  ${Object.keys(wxDaily).length} 天日摘要`);

// ==================== 3. 合并 + 衍生特征 ====================
const astroRadCache = {}; // 缓存理论辐射计算结果

function calcTheoreticalRadiation(lat, dateStr) {
  // 大气层顶太阳辐射 (W/m² 逐时) — 简化天文计算
  if (astroRadCache[dateStr]) return astroRadCache[dateStr];

  const dt = new Date(dateStr + "T12:00:00+08:00");
  const doy = Math.floor((dt - new Date(dt.getFullYear(), 0, 0)) / 86400000);
  const declination = 23.45 * Math.sin(2 * Math.PI * (284 + doy) / 365) * Math.PI / 180;
  const latRad = lat * Math.PI / 180;

  const hourly = [];
  for (let h = 0; h < 24; h++) {
    // 时角 (以正午12:00为0)
    const hourAngle = (h - 12) * 15 * Math.PI / 180;
    const cosZenith = Math.sin(latRad) * Math.sin(declination) +
                      Math.cos(latRad) * Math.cos(declination) * Math.cos(hourAngle);
    const solarConst = 1361; // W/m²
    // 大气层顶辐射
    const toa = cosZenith > 0 ? solarConst * cosZenith : 0;
    // 简化为 MJ/m²/h: W/m² * 3600 / 1e6
    hourly.push(toa > 0 ? toa * 0.0036 : 0);
  }
  astroRadCache[dateStr] = hourly;
  return hourly;
}

const merged = [];
const LAT = 22.52; // 中山市纬度

for (const date of pvDates) {
  if (!wxHourly[date] || !wxDaily[date]) {
    console.log(`  ⚠️ 天气数据缺失: ${date}`);
    continue;
  }

  const pv = pvData[date];
  const wh = wxHourly[date];
  const wd = wxDaily[date];
  const dt = new Date(date + "T00:00:00+08:00");

  // 基础属性
  const weekday = dt.getDay();
  const month = dt.getMonth() + 1;
  const season = [12, 1, 2].includes(month) ? "冬" : [3,4,5].includes(month) ? "春" :
                 [6,7,8].includes(month) ? "夏" : "秋";

  // 天气日统计
  const tempAvg = wh.temp ? wh.temp.reduce((a,b) => (a??0) + (b??0), 0) / 24 : null;
  const tempRange = wd.tmax !== null && wd.tmin !== null ? wd.tmax - wd.tmin : null;
  const cloudAvg = wh.cloud ? wh.cloud.filter(v => v !== null).reduce((a,b) => a+b, 0) /
                              wh.cloud.filter(v => v !== null).length : null;
  const windAvg = wh.wind_spd ? wh.wind_spd.filter(v => v !== null).reduce((a,b) => a+b, 0) /
                                 wh.wind_spd.filter(v => v !== null).length : null;
  const radDailySum = wh.radiation ?
    wh.radiation.filter(v => v !== null).reduce((a,b) => a+b, 0) : null;

  // 衍生 — 有效辐射小时 (>0.1 MJ/m²/h = 约28 W/m²)
  const effRadHours = wh.radiation ? wh.radiation.filter(v => v !== null && v > 0.1).length : 0;
  const highTempHours = wh.temp ? wh.temp.filter(v => v !== null && v > 30).length : 0;

  // 衍生 — 晴空指数 (clear-sky index)
  const theoryRad = calcTheoreticalRadiation(LAT, date);
  let clearSkyIndex = null;
  if (wh.radiation && theoryRad) {
    let actualSum = 0, theorySum = 0;
    for (let h = 0; h < 24; h++) {
      if (wh.radiation[h] !== null) { actualSum += wh.radiation[h]; theorySum += theoryRad[h]; }
    }
    clearSkyIndex = theorySum > 0 ? actualSum / theorySum : null;
  }

  // 天气分类
  const radLevel = radDailySum < 5 ? "极低辐射" : radDailySum < 10 ? "低辐射" :
                   radDailySum < 15 ? "中等辐射" : radDailySum < 20 ? "高辐射" : "极高辐射";
  const weatherType = cloudAvg === null ? "未知" :
    cloudAvg < 20 && wd.precip_sum < 0.5 ? "晴天" :
    cloudAvg < 50 && wd.precip_sum < 1 ? "多云" :
    cloudAvg < 80 && wd.precip_sum < 5 ? "阴天" : "雨天";

  // 衍生 — 连续阴雨天数 (往前看)
  // 这个在后面做

  merged.push({
    date, weekday, month, season,
    is_weekend: [0, 6].includes(weekday) ? 1 : 0,
    weekday_name: ["日","一","二","三","四","五","六"][weekday],
    // 光伏
    pv_total_kWh: pv.total_kWh,
    pv_capacity_factor: pv.capacity_factor,
    pv_peak_kW: pv.peak_kW,
    pv_gen_hours: pv.gen_hours,
    pv_hourly: pv.hourly_kWh,
    // 天气-日
    tmax: wd.tmax, tmin: wd.tmin, tavg: tempAvg,
    precip_sum: wd.precip_sum,
    rad_daily_sum: radDailySum,
    cloud_avg: cloudAvg,
    wind_avg: windAvg,
    wind_max: wd.wind_max,
    // 衍生特征
    temp_range: tempRange,
    clear_sky_index: clearSkyIndex,
    eff_rad_hours: effRadHours,
    high_temp_hours: highTempHours,
    // 天气-逐时
    temp_hourly: wh.temp,
    precip_hourly: wh.precip,
    wind_hourly: wh.wind_spd,
    cloud_hourly: wh.cloud,
    rad_hourly: wh.radiation,
    // 分类
    rad_level: radLevel,
    weather_type: weatherType,
  });
}

// 计算连续阴雨天数
for (let i = 0; i < merged.length; i++) {
  let consecutive = 0;
  for (let j = i; j >= 0; j--) {
    if (merged[j].precip_sum >= 1 || merged[j].cloud_avg >= 70) consecutive++;
    else break;
  }
  merged[i].consecutive_rain_days = consecutive;
}

console.log(`合并后样本: ${merged.length} 天`);

// ==================== 4. 导出CSV ====================
const hdr = [
  "日期", "星期", "是否周末", "月份", "季节",
  "日总发电量_kWh", "容量因子", "峰值功率_kW", "有效发电小时",
  "最高温_℃", "最低温_℃", "日均温_℃", "日降水量_mm",
  "日总辐射_MJpm2", "日均云量_pct", "日均风速_kmh", "最大风速_kmh",
  "气温日较差_℃", "晴空指数", "有效辐射小时", "高温小时_>30℃",
  "连续阴雨天数", "辐射等级", "天气类型",
];
// 逐时列
const hh24 = Array.from({ length: 24 }, (_, h) => `${h}时`);
for (const prefix of ["发电_kWh", "气温_℃", "降水_mm", "风速_kmh", "云量_pct", "辐射_MJpm2"]) {
  hh24.forEach(h => hdr.push(`${prefix}_${h}`));
}

let csv = "﻿" + hdr.join(",") + "\n";
for (const d of merged) {
  const row = [
    d.date, d.weekday, d.is_weekend, d.month, d.season,
    fm(d.pv_total_kWh), fm(d.pv_capacity_factor), fm(d.pv_peak_kW), d.pv_gen_hours,
    fm1(d.tmax), fm1(d.tmin), fm1(d.tavg), fm1(d.precip_sum),
    fm(d.rad_daily_sum), fm1(d.cloud_avg), fm1(d.wind_avg), fm1(d.wind_max),
    fm1(d.temp_range), fm(d.clear_sky_index), d.eff_rad_hours, d.high_temp_hours,
    d.consecutive_rain_days, d.rad_level, d.weather_type,
  ];
  // 逐时数据
  for (const arr of [d.pv_hourly, d.temp_hourly, d.precip_hourly, d.wind_hourly,
                      d.cloud_hourly, d.rad_hourly]) {
    for (let h = 0; h < 24; h++) {
      const v = arr ? arr[h] : null;
      row.push(v === null || v === undefined ? "" : (typeof v === "number" && v < 10 ? fm(v) : fm1(v)));
    }
  }
  csv += row.join(",") + "\n";
}

writeFileSync(OUTPUT_CSV, csv);
console.log(`[导出] ${OUTPUT_CSV}`);
console.log(`  列数: ${hdr.length} (含 ${6*24} 列逐时数据)`);

// 统计概览
console.log(`\n${"=".repeat(60)}`);
console.log("数据概览");
console.log("=".repeat(60));
const pvTotal = merged.map(d => d.pv_total_kWh);
const cf = merged.map(d => d.pv_capacity_factor);
const radDaily = merged.map(d => d.rad_daily_sum).filter(v => v !== null);

console.log(`  日发电量: ${Math.min(...pvTotal).toFixed(0)} ~ ${Math.max(...pvTotal).toFixed(0)} kWh, 均值 ${(pvTotal.reduce((a,b)=>a+b,0)/pvTotal.length).toFixed(0)}`);
console.log(`  容量因子: ${(Math.min(...cf)*100).toFixed(1)}% ~ ${(Math.max(...cf)*100).toFixed(1)}%, 均值 ${(cf.reduce((a,b)=>a+b,0)/cf.length*100).toFixed(1)}%`);
console.log(`  日总辐射: ${Math.min(...radDaily).toFixed(1)} ~ ${Math.max(...radDaily).toFixed(1)} MJ/m², 均值 ${(radDaily.reduce((a,b)=>a+b,0)/radDaily.length).toFixed(1)}`);

// 天气类型分布
const wtCount = {};
merged.forEach(d => { wtCount[d.weather_type] = (wtCount[d.weather_type] || 0) + 1; });
console.log(`  天气类型: ${Object.entries(wtCount).map(([k,v]) => `${k}(${v}天)`).join("  ")}`);

// 季节分布
const sCount = {};
merged.forEach(d => { sCount[d.season] = (sCount[d.season] || 0) + 1; });
console.log(`  季节分布: ${Object.entries(sCount).map(([k,v]) => `${k}(${v}天)`).join("  ")}`);

console.log(`\n数据已准备就绪，开始分析...`);
