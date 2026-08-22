/**
 * 更新全要素天气表_长格式_v2.xlsx
 * - 删除所有"日照时长"行
 * - 写入"太阳总辐射(MJ/m²)"逐小时数据
 */
import { readFileSync, writeFileSync } from "fs";
import XLSX from "xlsx";

const XLSX_FILE = "光伏发电因素相关性分析/全要素天气表_长格式_v2.xlsx";
const OUTPUT_FILE = "光伏发电因素相关性分析/全要素天气表_长格式_v2_已更新.xlsx";
const RADIATION_JSON = "era5_radiation.json";
const TARGET_SHEET = "全要素天气表_长格式_v2";
const NEW_FACTOR_NAME = "太阳总辐射(MJ/m²)";
const OLD_FACTOR_PATTERN = "日照时长";

// ==================== 1. 读取数据 ====================
console.log("=".repeat(55));
console.log("更新全要素天气表_长格式_v2.xlsx");
console.log("  删除: 日照时长行");
console.log("  写入: 太阳总辐射(MJ/m²) 逐小时数据");
console.log("=".repeat(55));

const wb = XLSX.readFile(XLSX_FILE);
const ws = wb.Sheets[TARGET_SHEET];
const data = XLSX.utils.sheet_to_json(ws, { header: 1 });

const radRaw = JSON.parse(readFileSync(RADIATION_JSON, "utf8"));
const radHourly = radRaw.hourly;

// 构建辐射查找表: date → [24个逐时值(MJ/m²)]
const radMap = {};
for (let i = 0; i < radHourly.time.length; i++) {
  const date = radHourly.time[i].slice(0, 10); // "2025-01-01"
  const hour = parseInt(radHourly.time[i].slice(11, 13)); // 0-23
  if (!radMap[date]) radMap[date] = new Array(24).fill(null);
  radMap[date][hour] = radHourly.shortwave_radiation_MJpm2[i];
}

// Excel序列号 → ISO日期 转换
// Excel: 1 = 1900-01-01, JS: 25569 = days from 1900-01-01 to 1970-01-01
function excelSerialToISODate(serial) {
  const jsDate = new Date((serial - 25569) * 86400 * 1000);
  const y = jsDate.getFullYear();
  const m = String(jsDate.getMonth() + 1).padStart(2, "0");
  const d = String(jsDate.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// ==================== 2. 替换数据 ====================
let replacedCount = 0;
let missingRadCount = 0;
const missingDates = [];

const newData = [data[0]]; // 保留表头

for (let i = 1; i < data.length; i++) {
  const row = data[i];
  const factorName = row[1];

  if (factorName && String(factorName).includes(OLD_FACTOR_PATTERN)) {
    // 这是日照时长行 → 替换为辐射强度
    const isoDate = excelSerialToISODate(row[0]);
    const radValues = radMap[isoDate];

    if (radValues) {
      // 构建新行: 日期 + 太阳总辐射 + 24个逐时值
      const newRow = [row[0], NEW_FACTOR_NAME, ...radValues];
      newData.push(newRow);
      replacedCount++;
    } else {
      // 辐射数据缺失，保留原日照数据但标记
      console.log(`  ⚠️ 辐射数据缺失: ${isoDate} (序列号 ${row[0]})，保留原日照行`);
      missingDates.push(isoDate);
      missingRadCount++;
      newData.push(row); // 保留原行
    }
  } else {
    // 非日照行，原样保留
    newData.push(row);
  }
}

console.log(`\n[结果]`);
console.log(`  原始总行数: ${data.length - 1} (不含表头)`);
console.log(`  替换日照行: ${replacedCount} 行`);
console.log(`  辐射缺失行: ${missingRadCount} 行 (保留原日照数据)`);
if (missingDates.length > 0) {
  console.log(`  缺失日期: ${missingDates.slice(0, 10).join(", ")}${missingDates.length > 10 ? "..." : ""}`);
}

// ==================== 3. 写回 ====================
// 用新数据重建 worksheet
const newWs = XLSX.utils.aoa_to_sheet(newData);
wb.Sheets[TARGET_SHEET] = newWs;

XLSX.writeFile(wb, OUTPUT_FILE);
console.log(`\n[导出] ${OUTPUT_FILE}`);
console.log(`  ⚠️ 原文件被占用，已保存到新文件。请关闭Excel后将新文件覆盖原文件。`);

// ==================== 4. 验证 ====================
const verifyWb = XLSX.readFile(OUTPUT_FILE);
const verifyWs = verifyWb.Sheets[TARGET_SHEET];
const verifyData = XLSX.utils.sheet_to_json(verifyWs, { header: 1 });

const newFactors = new Set();
verifyData.slice(1).forEach(r => { if (r[1]) newFactors.add(r[1]); });
console.log(`\n[验证] 更新后要素列表:`);
[...newFactors].sort().forEach(f => console.log(`  - ${f}`));

// 验证辐射数据格式
const radRows = verifyData.filter(r => r[1] === NEW_FACTOR_NAME);
console.log(`\n[验证] 辐射强度行数: ${radRows.length}`);
if (radRows.length > 0) {
  const firstRad = radRows[0];
  const dateISO = excelSerialToISODate(firstRad[0]);
  console.log(`  首行: 日期=${firstRad[0]} (${dateISO}), 要素="${firstRad[1]}"`);
  console.log(`  前6h: ${firstRad.slice(2, 8).map(v => (typeof v === 'number') ? v.toFixed(3) : v).join(", ")} MJ/m²`);
  // 验证: 计算该日总辐射
  const dailySum = firstRad.slice(2, 26).filter(v => typeof v === 'number').reduce((a, b) => a + b, 0);
  console.log(`  日总辐射: ${dailySum.toFixed(2)} MJ/m²`);
  // 检查是否还是全部相同的值
  const allSame = new Set(firstRad.slice(2, 26).filter(v => typeof v === 'number')).size === 1;
  console.log(`  24h全相同? ${allSame ? '是 (异常!)' : '否 (正确, 逐时独立值)'}`);
}

console.log("=".repeat(55));
console.log("更新完成!");
console.log("=".repeat(55));
