/**
 * 中山市工业厂区日前负荷预测 — 气象相关性分析报告 (Word版)
 */
import { readFileSync, writeFileSync } from "fs";
import {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  WidthType, AlignmentType, BorderStyle, HeadingLevel,
  TableLayoutType, ShadingType,
} from "docx";

// ============ 读取数据(复用correlation_report计算结果) ============
const reportTxt = readFileSync("相关性分析报告/相关性分析报告.txt", "utf8");
const corrCSV = readFileSync("相关性分析报告/逐时气温负荷相关性.csv", "utf8");
const seasonCSV = readFileSync("相关性分析报告/分季节相关性.csv", "utf8");
const precipCSV = readFileSync("相关性分析报告/降水等级负荷分析.csv", "utf8");
const weekdayCSV = readFileSync("相关性分析报告/星期效应.csv", "utf8");

const parseCSV = (csv) => {
  const lines = csv.trim().split("\n");
  const headers = lines[0].replace("﻿","").split(",");
  return lines.slice(1).map(l => {
    const vals = l.split(",");
    const obj = {};
    headers.forEach((h,i) => obj[h] = vals[i]);
    return obj;
  });
};

const hourlyCorr = parseCSV(corrCSV);
const seasonCorr = parseCSV(seasonCSV);
const precipData = parseCSV(precipCSV);
const weekdayData = parseCSV(weekdayCSV);

// ============ 样式工具 ============
const thinBorder = { style: BorderStyle.SINGLE, size: 1, color: "999999" };
const headerShading = { fill: "1F4E79", type: ShadingType.CLEAR };
const altShading = { fill: "F2F7FB", type: ShadingType.CLEAR };
const cellBase = { borders: { top: thinBorder, bottom: thinBorder, left: thinBorder, right: thinBorder }, width: { size: 1200, type: WidthType.DXA } };

function hCell(text, width = 1200) {
  return new TableCell({
    ...cellBase,
    width: { size: width, type: WidthType.DXA },
    shading: headerShading,
    children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text, bold: true, color: "FFFFFF", size: 18 })] })],
  });
}
function dCell(text, width = 1200, center = false) {
  return new TableCell({
    ...cellBase,
    width: { size: width, type: WidthType.DXA },
    children: [new Paragraph({ alignment: center ? AlignmentType.CENTER : AlignmentType.LEFT, children: [new TextRun({ text: String(text ?? ""), size: 18 })] })],
  });
}
function makeTable(headers, rows, widths = null) {
  const w = widths || headers.map(() => 1400);
  return new Table({
    layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({ children: headers.map((h,i) => hCell(h, w[i] || 1400)) }),
      ...rows.map((row, ri) => new TableRow({
        children: row.map((cell, ci) => {
          const c = dCell(cell, w[ci] || 1400, ci > 0);
          if (ri % 2 === 1) c.root.push({ shading: altShading });
          return c;
        }),
      })),
    ],
  });
}

// ============ 正文段落 ============
const h1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 400, after: 200 }, children: [new TextRun({ text, bold: true, size: 32, color: "1F4E79" })] });
const h2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 300, after: 150 }, children: [new TextRun({ text, bold: true, size: 26, color: "2E75B6" })] });
const para = (text) => new Paragraph({ spacing: { after: 100 }, children: [new TextRun({ text, size: 21 })] });
const boldP = (text) => new Paragraph({ spacing: { after: 80 }, children: [new TextRun({ text, bold: true, size: 21 })] });

// ============ 构建文档 ============
const doc = new Document({
  styles: { default: { document: { run: { font: "微软雅黑", size: 21 } } } },
  sections: [{
    children: [
      // ──── 封面 ────
      new Paragraph({ spacing: { before: 2000 }, children: [] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: "中山市工业厂区", bold: true, size: 48, color: "1F4E79" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [new TextRun({ text: "日前负荷预测 — 气象相关性分析报告", bold: true, size: 40, color: "1F4E79" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 600, after: 100 }, children: [new TextRun({ text: "数据周期: 2025-04-01 → 2026-04-30 (395天)", size: 24, color: "666666" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [new TextRun({ text: "数据源: ERA5-Land 再分析 + 三公司逐时负荷表", size: 24, color: "666666" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [new TextRun({ text: "生成日期: 2026-07-30", size: 24, color: "666666" })] }),

      // ──── 一、数据概览 ────
      h1("一、数据概览"),
      para("本报告基于中山市 (22.52°N, 113.40°E) 三家公司2025年4月至2026年4月逐时负荷数据，结合 Open-Meteo ERA5-Land 同期气象再分析数据，系统分析气象因子与工业负荷的相关性，为日前负荷预测模型的特征选择与权重分配提供定量依据。"),
      para(""),
      makeTable(["指标","数值"], [
        ["分析周期","2025-04-01 → 2026-04-30 (395天)"],
        ["日总负荷范围","345.5 ~ 700.9"],
        ["日总负荷均值","579.8 ± 59.2"],
        ["气温范围 (日最高)","13.1 ~ 36.5°C"],
        ["气温范围 (日最低)","6.6 ~ 27.4°C"],
        ["降水天数","236天 (59.7%)"],
        ["累计降水量","1976.3 mm"],
        ["气象数据源","Open-Meteo ERA5-Land (0.1°格点)"],
      ], [2400, 6000]),

      // ──── 二、气温相关性 ────
      h1("二、气温 × 负荷 — 核心相关性"),
      para("气温是工业负荷的第一气象驱动因子。华南地区空调制冷负荷与气温呈显著正相关，且夜间相关性高于午间——这一反直觉发现说明夜间基础负荷对温度的敏感性超过日间生产高峰时段。"),
      para(""),
      makeTable(["指标","Pearson r","Spearman ρ","方向","解释"],
        [["日最高温 vs 日总负荷","0.569","0.671","正相关","空调制冷主驱动"],
         ["日最低温 vs 日总负荷","0.694","—","正相关","夜间基线, 相关性最强"],
         ["日均温 vs 日总负荷","0.657","—","正相关","综合温控负荷指标"],
        ], [2000, 1200, 1200, 1000, 2600]),

      h2("2.1 分季节气温相关性"),
      para("季节是气温-负荷关系的核心调节变量。秋季相关最强 (r=0.76)，因为气温变化直接决定空调开关；夏季几乎不相关 (r=0.07)，因为高温已饱和，空调全天候运行。"),
      para(""),
      makeTable(["季节","样本数","Pearson r","均温(°C)","均负荷","解释"],
        seasonCorr.map(s => [s["季节"], s["样本数"], s["Pearson_r"], s["均温"], s["均负荷"],
          s["季节"]==="秋"?"气温→空调开关, 敏感度最高":
          s["季节"]==="夏"?"高温饱和, 空调全开, 相关性消失":
          s["季节"]==="春"?"过渡季, 温控负荷波动大":
          "冬季采暖+生产叠加, 呈弱负相关"]),
        [800, 800, 1000, 1000, 1000, 3300]),

      h2("2.2 分气温档负荷特征"),
      para("随着日最高温从偏凉升至酷热，日均负荷从533升至630 (+18%)，负荷波动(峰谷差)从11.1升至13.9，说明高温不仅推高总负荷，还放大了日内波动。"),
      para(""),
      makeTable(["气温档","天数","均负荷","峰值均值","谷值均值","峰谷差"],
        [["偏凉 (<18°C)","13","533.2","28.0","16.9","11.1"],
         ["温和 (18-25°C)","86","534.5","28.1","17.2","10.9"],
         ["偏热 (25-30°C)","137","569.9","29.9","18.5","11.4"],
         ["高温 (30-35°C)","151","616.1","33.0","20.0","13.0"],
         ["酷热 (>35°C)","8","630.3","34.6","20.7","13.9"],
        ], [1200, 700, 1000, 1000, 1000, 1000]),

      h2("2.3 逐时气温-负荷相关性 (24h剖面)"),
      para("相关性呈典型的 U 型分布：夜间 (22-05h) 平均 |r|=0.65，午间 (10-15h) 降至 0.42。这是因为午间生产活动主导负荷变化，掩盖了气温信号；夜间生产停止后气温成为负荷变化主因。"),
      para(""),
      makeTable(["时刻","Pearson r","该时均温","该时均负荷","相关强度"],
        hourlyCorr.map(h => [h["时刻"]+":00", h["相关系数r"], h["该时均温"]+"°C", h["该时均负荷"],
          Math.abs(Number(h["相关系数r"]))>0.6?"███ 强":
          Math.abs(Number(h["相关系数r"]))>0.5?"██ 中强":
          Math.abs(Number(h["相关系数r"]))>0.4?"█ 中等":" 弱"]),
        [800, 1100, 1100, 1100, 1200]),

      // ──── 三、降水分析 ────
      h1("三、降水 × 负荷 — 反直觉的雨天负荷上升"),
      para("与直觉相反，中山市雨天工业负荷普遍高于晴天。无降水日均负荷 544，小雨日 595 (+9.4%)，中雨日 611 (+12.3%)。原因分析：(1) 华南降雨多伴随降温，气温回落后生产活动反而增加；(2) 雨天停工可能性低，工业负荷具有刚性；(3) 除湿负荷部分抵消降温效应。"),
      para(""),
      makeTable(["降水等级","天数","均负荷","负荷σ","CV","峰值","谷值"],
        precipData.map(p => [p["降水等级"], p["样本数"], p["均负荷"], p["负荷σ"], p["变异系数CV"], p["峰值均值"], p["谷值均值"]]),
        [1000, 700, 900, 800, 800, 900, 900]),

      h2("3.1 降水日 vs 非降水日 逐时负荷差异"),
      para("雨天负荷全线高于晴天，午间差距最大 (+16~20%)。降水对负荷预测的影响不是简单的衰减因子，而是结构性偏移——这要求在相似日筛选中优先匹配降水等级。"),
      h2("3.2 新增因子: 相对湿度与露点温度"),
      para("补充拉取 ERA5 相对湿度与露点温度数据后发现：露点温度 r=0.673 超过日最高温 r=0.569，成为当前最强单一气象因子。华南高温高湿环境下，体感温度(由露点决定)对空调负荷的解释力优于干球温度。"),
      para(""),
      makeTable(["新增因子","Pearson r","数据源","状态"],
        [["相对湿度(%)","0.515","ERA5 hourly","已拉取,待合并"],
         ["露点温度(°C)","0.673","ERA5 hourly","已拉取, 最强单因子"],
         ["地表气压(hPa)","-0.598","ERA5 hourly","已拉取, 天气系统前兆"],
        ], [2000, 1200, 2000, 1800]),

      // ──── 四、辅助因子 ────
      h1("四、太阳、风力与星期效应"),
      h2("4.1 日照与云量"),
      para("日照时长与日总负荷 r=0.01 (几乎无关)，云量与日总负荷 r=0.29 (弱正相关)。两者的独立解释力有限，主要通过与温度和降水的共线性间接影响。在相似日筛选中可降低日照权重。"),
      h2("4.2 星期效应"),
      para("工作日与周末负荷差异仅 0.7% (581 vs 577)，工业负荷的生产连续性极高。星期标签的建模权重可从原 15% 下调至 10%。"),
      para(""),
      makeTable(["星期","天数","均负荷","σ","峰值","谷值"],
        weekdayData.map(w => [w["星期"], w["n"], w["均负荷"], w["负荷σ"], w["峰值均值"], w["谷值均值"]]),
        [900, 700, 900, 800, 900, 900]),

      // ──── 五、综合权重 ────
      h1("五、相似日筛选 — 气象权重分配方案 (标定版)"),
      para("基于395天实际相关性数据，对初始经验权重进行定量标定："),
      para(""),
      makeTable(["因子","原权重","标定后","调整依据"],
        [["日最高温偏差","25%","20%","Tmax r=0.57, 略低于最低温"],
         ["日最低温偏差","15%","20%","Tmin r=0.69, 夜间基线最强, 上调"],
         ["降水等级匹配","20%","18%","雨天负荷反增非衰减, 非线性影响"],
         ["日照时长偏差","10%","5%","r=0.01, 独立贡献极低, 大幅下调"],
         ["季节匹配","10%","15%","秋季r=0.76 vs 夏季r=0.07, 季节调节作用超预期"],
         ["星期类型匹配","15%","10%","工作日/周末差异仅0.7%, 下调"],
         ["日期距离衰减","5%","10%","同季近一周优先, 生产连续性考量"],
         ["露点温度偏差","—","新增5%","r=0.673, 体感温度核心指标"],
        ], [1600, 1000, 1000, 4300]),

      // ──── 六、建议 ────
      h1("六、预测策略建议"),
      boldP("策略A — 相似日加权:"),
      para("按七因子评分取 Top-5 相似日, 负荷加权平均。优点: 可解释、稳健；缺点: 极端天气下候选池不足。"),
      boldP("策略B — 分群线性回归:"),
      para("按 季节 × 星期类型 × 降水等级 分群, 每群内用 气温+露点温度 做多元回归。优点: 捕捉群内线性关系；缺点: 群间不连续。"),
      boldP("策略C — 时序深度学习:"),
      para("LSTM / Transformer 输入 [24h气温, 24h湿度, 24h降水, 云量, 露点, 气压, 季节编码, 星期编码], 输出 24h 负荷曲线。优点: 捕获非线性、时序依赖。"),
      boldP("策略D — 集成:"),
      para("策略 A+B+C 加权融合。暴雨/台风日降低相似日权重, 提高时序模型权重。滚动回测评估最优权重分配。"),

      // ──── 七、后续数据需求 ────
      h1("七、待补充数据清单"),
      makeTable(["优先级","数据项","来源","预期贡献"],
        [["P0","相对湿度 + 露点温度","ERA5 (已拉取)","r=0.52/0.67, 合并建模"],
         ["P0","地表气压","ERA5 (已拉取)","r=-0.60, 台风/冷锋前兆"],
         ["P1","法定节假日 + 调休标识","国务院通知, 手动标注","春节/国庆负荷骤降"],
         ["P1","时序滞后特征 (lag-24h/168h)","已有数据衍生","捕捉负荷持续性"],
         ["P2","台风日/暴雨红色预警","气象局历史预警","极端事件建模"],
         ["P2","有序用电/限电日","供电局通知","异常负荷剔除"],
         ["P3","工厂检修/停产日","厂方提供","数据清洗"],
        ], [800, 2500, 2000, 2700]),

      // ──── 附录 ────
      h1("附录: 数据文件清单"),
      para("以下为整理后的项目文件结构，供后续建模直接使用："),
      para(""),
      makeTable(["路径","说明","用途"],
        [["数据源文件2025、2026.xlsx","三公司逐时负荷原始表","负荷标签"],
         ["era5_full_2025.json","ERA5气温/降水/风/云/日照 (575天)","气象主数据"],
         ["era5_humidity.json","ERA5湿度/露点/气压 (395天)","气象补充数据"],
         ["中山市历史天气数据/","天气宽表 + 7/31相似日分析","天气查询"],
         ["相关性分析报告/","相关性报告 + 合并数据集(114列)","建模入模数据"],
         ["build_zs_weather.mjs","天气表构建脚本","数据更新"],
         ["correlation_report.mjs","相关性分析脚本","定期重算"],
        ], [2800, 2600, 1600]),
    ],
  }],
});

// ============ 输出 ============
const buffer = await Packer.toBuffer(doc);
writeFileSync("中山市工业负荷_气象相关性分析报告.docx", buffer);
console.log("[完成] 中山市工业负荷_气象相关性分析报告.docx");
console.log(`  大小: ${(buffer.length/1024).toFixed(0)} KB`);

// 最终文件清单
console.log("\n整理后文件结构:");
import { execSync } from "child_process";
const tree = execSync('find . -maxdepth 3 -not -path "./.claude/*" -not -path "./node_modules/*" -not -name "package*.json" -not -name "*.mjs" | sort').toString();
console.log(tree);
