/**
 * 从 Open-Meteo ERA5 Archive API 爬取逐小时短波辐射通量
 * 坐标: 中山市 (22.52°N, 113.38°E)
 * 时间: 2025-01-01 → 2026-07-29
 * 输出: era5_radiation.json
 */
import { writeFileSync } from "fs";

const LAT = 22.52;
const LON = 113.38;
const START = "2025-01-01";
const END = "2026-07-29";
const OUTPUT = "era5_radiation.json";

// Open-Meteo 单次请求最多约 600 天逐小时数据，分两段请求
const BATCHES = [
  { start: "2025-01-01", end: "2025-08-31" },
  { start: "2025-09-01", end: "2026-04-30" },
  { start: "2026-05-01", end: "2026-07-29" },
];

const URL = "https://archive-api.open-meteo.com/v1/archive";

async function fetchBatch(start, end) {
  const params = new URLSearchParams({
    latitude: LAT,
    longitude: LON,
    start_date: start,
    end_date: end,
    hourly: "shortwave_radiation",
    timezone: "Asia/Shanghai",
  });
  const url = `${URL}?${params}`;
  console.log(`  请求: ${url.slice(0, 120)}...`);
  const resp = await fetch(url);
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${body.slice(0, 300)}`);
  }
  return resp.json();
}

// W/m² → MJ/m² per hour: × 3600 (seconds) / 1,000,000 = × 0.0036
// 注意: ERA5 shortwave_radiation_flux 是过去1小时的平均通量(W/m²)
// 该小时的辐射能量 = W/m² × 3600s = J/m², /1e6 = MJ/m²
const WPM2_TO_MJPM2 = 3600 / 1_000_000; // 0.0036

async function main() {
  console.log("=".repeat(55));
  console.log("ERA5 逐小时短波辐射通量 爬取");
  console.log(`  坐标: ${LAT}°N, ${LON}°E (中山市)`);
  console.log(`  时间: ${START} → ${END}`);
  console.log("=".repeat(55));

  const allTimes = [];
  const allRadiation = [];

  for (const batch of BATCHES) {
    console.log(`\n[批次] ${batch.start} → ${batch.end}`);
    const data = await fetchBatch(batch.start, batch.end);
    const hourly = data.hourly;
    if (!hourly || !hourly.time) {
      console.error(`  错误: 响应无 hourly.time 字段`);
      console.error(`  响应键: ${Object.keys(data).join(", ")}`);
      continue;
    }

    const times = hourly.time;
    const fluxRaw = hourly.shortwave_radiation;
    console.log(`  获取: ${times.length} 条记录`);
    console.log(`  辐射范围: ${Math.min(...fluxRaw).toFixed(1)} ~ ${Math.max(...fluxRaw).toFixed(1)} W/m²`);

    // 过滤掉 NaN
    for (let i = 0; i < times.length; i++) {
      if (fluxRaw[i] != null && !Number.isNaN(fluxRaw[i])) {
        allTimes.push(times[i]);
        allRadiation.push(fluxRaw[i]);
      }
    }
  }

  // 去重 (按时间戳)
  const seen = new Map();
  for (let i = 0; i < allTimes.length; i++) {
    seen.set(allTimes[i], allRadiation[i]);
  }
  const sortedTimes = [...seen.keys()].sort();
  const sortedRad = sortedTimes.map(t => seen.get(t));

  const sortedRad_MJ = sortedRad.map(v => v * WPM2_TO_MJPM2);

  // 计算日总辐射
  const dailyMap = {};
  for (let i = 0; i < sortedTimes.length; i++) {
    const date = sortedTimes[i].slice(0, 10);
    if (!dailyMap[date]) dailyMap[date] = [];
    dailyMap[date].push(sortedRad_MJ[i]);
  }
  const dailyDates = Object.keys(dailyMap).sort();
  const dailyTotal = dailyDates.map(d => dailyMap[d].reduce((a, b) => a + b, 0));

  // 输出 JSON
  const output = {
    hourly: {
      time: sortedTimes,
      shortwave_radiation_MJpm2: sortedRad_MJ.map(v => Math.round(v * 1000) / 1000),
    },
    daily: {
      time: dailyDates,
      shortwave_radiation_sum_MJpm2: dailyTotal.map(v => Math.round(v * 100) / 100),
    },
    meta: {
      latitude: LAT,
      longitude: LON,
      source: "Open-Meteo ERA5-Land (archive-api)",
      parameter: "shortwave_radiation",
      unit_raw: "W/m² (hourly average)",
      unit_converted: "MJ/m² per hour & MJ/m² per day",
      conversion: "W/m² × 0.0036 = MJ/m²/h",
      fetched_at: new Date().toISOString(),
    },
  };

  writeFileSync(OUTPUT, JSON.stringify(output));
  console.log(`\n[导出] ${OUTPUT}`);
  console.log(`  逐小时: ${sortedTimes.length} 条 (${sortedTimes[0]} → ${sortedTimes[sortedTimes.length - 1]})`);
  console.log(`  逐日:   ${dailyDates.length} 天 (${dailyDates[0]} → ${dailyDates[dailyDates.length - 1]})`);
  console.log(`  日总辐射: ${Math.min(...dailyTotal).toFixed(2)} ~ ${Math.max(...dailyTotal).toFixed(2)} MJ/m²`);
  console.log(`  日均辐射: ${(dailyTotal.reduce((a, b) => a + b, 0) / dailyTotal.length).toFixed(2)} MJ/m²`);

  // 统计
  const allHourly = sortedRad_MJ;
  console.log(`\n  统计摘要:`);
  console.log(`    逐时辐射: ${allHourly.filter(v => v > 0).length}/${allHourly.length} 个非零小时`);
  console.log(`    逐时范围: ${Math.min(...allHourly).toFixed(3)} ~ ${Math.max(...allHourly).toFixed(3)} MJ/m²/h`);
  console.log(`    日均: ${(dailyTotal.reduce((a,b)=>a+b,0)/dailyTotal.length).toFixed(2)} MJ/m²/day`);
  console.log("=".repeat(55));
}

main().catch(err => {
  console.error("爬取失败:", err.message);
  process.exit(1);
});
