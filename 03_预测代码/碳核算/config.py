"""模块三碳核算——全部核算参数与排放因子（与数据来源清单.xlsx 对齐）。

口径约定：
- 只计 CO2（除范围一 CH4/N2O 折算 CO2e 外）。
- 广东项目优先省级因子 0.4419。
- 一次计算任务锁定一个不可变因子快照，禁止混用报告/优化/LCA 三套因子。
"""

# ============ 电力排放因子 (kgCO2/kWh) ============
EF_REPORT = 0.4419          # 广东省 2023 电力 CO2 因子（范围二正式报告，年度固定）
EF_NATIONAL = 0.5306        # 全国 2023（备选/对比）
EF_SOUTH = 0.4042           # 南方区域 2023（备选/对比）
EF_CFP = 0.5777             # 2024 全国电力碳足迹因子（仅 LCA，kgCO2e/kWh）

# EF_opt(t) 时变碳因子（节点电价代理法，方法二），映射区间与年均校准
EF_OPT_LOW = 0.30           # 低价时段碳强度下界
EF_OPT_HIGH = 0.65          # 高价时段碳强度上界
EF_OPT_ANNUAL_TARGET = EF_REPORT  # 年均校准目标 = 省级固定因子

# ============ 范围一：工艺直接排放 ============
# CH4
B0 = 0.25                   # 最大产甲烷潜能 kgCH4/kgCOD, IPCC 2006(2019修订)
MCF = 0.05                  # 甲烷修正因子(AAO工艺，好氧为主)
GWP_CH4 = 28.0              # IPCC AR5
# N2O
EF_N2O = 0.016              # kgN2O-N/kgN, Li et al. 2023 国内AAO中值
MOL_N2O_N = 44.0 / 28.0     # N2O 与 N 摩尔质量比
GWP_N2O = 265.0             # IPCC AR5

# ============ 范围一：水质活动数据 ============
COD_IN = 150.0              # mg/L, 广东地区实际进水统计中值
COD_EFF = 10.0              # mg/L, SCADA照片实测(准Ⅳ类)
TN_IN = 30.0                # mg/L
TN_EFF = 7.0                # mg/L
Q_DAY = 400000.0            # m3/d, 公开处理规模40万吨/天(中山最大,设计规模口径)
SEC = 0.57                  # kWh/m3 吨水电耗, 由真实总负荷9022万kWh÷40万m3/天×396天反推(深度处理厂电耗偏高)
COD_SLUDGE_RATIO = 0.15     # 剩余污泥携带 COD 占总去除量比例(用于CH4扣除)

# ============ 储能工程参数 ============
BATTERY_CAPACITY = 16000.0  # kWh (16MWh，与优化调度 E_BAT_MAX 对齐)
BATTERY_POWER_MAX = 8000.0  # kW (8MW，与优化调度 P_BAT_MAX 对齐)
ETA_RT = 0.90               # 往返总效率(模块二设定 η_c=η_d=94.87%)
SOC_MIN = 0.10
SOC_MAX = 0.90
R_AUX = 0.03                # 辅助电耗占充放电量比例(广东夏季)
DOD = 0.90                  # 设计放电深度(LCA)
N_EFC = 6000                # 等效全循环次数 @80%DoD
K_AVAIL = 0.95              # 设备可用系数

# ============ LCA 隐含碳 ============
LFP_CELL_CF = 19.9          # kgCO2e/kWh, 电芯 cradle-to-gate
SYS_EMBODIED = 70.0         # kgCO2e/kWh, 储能系统级隐含碳(取60-80中值)
RECYCLING_RATIO = 0.10      # 退役回收抵减占隐含碳比例

# ============ 价格 ============
FEED_IN_PRICE = 0.453       # 燃煤标杆上网电价(余电上网收益,不影响碳核算)

# ============ 路径 ============
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # 碳核算/
MODULE3_DIR = os.path.dirname(BASE_DIR)                        # 03_预测代码/
PROJECT_DIR = os.path.dirname(MODULE3_DIR)                     # 项目根目录
RAW_DATA_DIR = os.path.join(PROJECT_DIR, "02_原始数据")         # 原始数据目录

# 节点电价文件（含日前/实时电价，单位元/MWh）
PRICE_XLSX = os.path.join(RAW_DATA_DIR, "电价数据", "广东电力市场电价_逐时.xlsx")

# ============ 单位换算 ============
T_PER_KG = 1e-3
