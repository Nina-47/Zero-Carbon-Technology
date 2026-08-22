# -*- coding: utf-8 -*-
"""
智能调度 全局配置
所有可调参数集中在此，方便改储能/柔性/光伏规模、切换路径。
"""

import os

# ---------------- 路径 ----------------
# 智能调度目录（本文件所在）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 模块二目录（父级）
MODULE2_DIR = os.path.dirname(BASE_DIR)
# 项目根目录（公用/公用）
# 目录结构: 公用/公用/模块二/智能调度/config.py
# MODULE2_DIR = .../公用/模块二，PROJECT_ROOT = .../公用/公用
PROJECT_ROOT = os.path.dirname(MODULE2_DIR)

# 光伏×天气 合并数据（光伏预测训练数据）
PV_WEATHER_CSV = os.path.join(PROJECT_ROOT, "04_预测输出", "V4_优化调度", "合并数据集_光伏×天气.csv")
# 原始调度数据（A 中嘉分表：光伏发电 + 实际用电量，优化层回测用）
DATA_SOURCE_XLSX = os.path.join(PROJECT_ROOT, "02_原始数据", "负荷数据", "A_中嘉污水厂.xlsx")
# B/C 分表（列布局与 A 一致：0日期 | 1-24电网 | 25-48光伏 | 49-72实际用电量；B/C 光伏列全 0）
DATA_SOURCE_B = os.path.join(PROJECT_ROOT, "02_原始数据", "负荷数据", "B_中山市污水处理.xlsx")
DATA_SOURCE_C = os.path.join(PROJECT_ROOT, "02_原始数据", "负荷数据", "C_珍家山污水厂.xlsx")
# 天气逐时辐射（长表 sheet：date + hour + 辐射_Wm2，光伏出力模型输入）
WEATHER_XLSX = os.path.join(PROJECT_ROOT, "02_原始数据", "天气数据", "中山天气_OpenMeteo.xlsx")
# 节点电价文件（含日前/实时电价，单位元/MWh）
PRICE_XLSX = os.path.join(PROJECT_ROOT, "02_原始数据", "电价数据", "广东电力市场电价_逐时.xlsx")

# 输出目录
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ---------------- 光伏 ----------------
# 真实装机基准 = 中嘉三站台账并网容量合计 8.12 MWp
#   （一期 3.47 + 二期 4.0905 + 车棚 0.562，场站信息表精确值）
# 占地系数实测：8.12 MWp ÷ 30 公顷(30万㎡) ≈ 0.027 kW/㎡（理论上限 0.035 另作参数）
PV_BASE_CAPACITY_KW = 8120.0
# 光伏系统性能比 PR（辐射→出力模型的综合效率，见 pv_output_model.py）
# 用 A 厂真实年发电 935 万 kWh ÷ 同期逐时辐射反推 = 0.6514，低于行业典型 0.8：
#   污水厂池顶/屋顶光伏朝向不正、气体腐蚀、清洗难，实际效率偏低。
# 通用化时 B/C/D 预测发电量必须用此实测值，否则会高估约 20% 发电量与收益。
PV_SYSTEM_PR = 0.6514
# 光伏容量放大系数 = 1.0 即用真实装机回测；>1 用于容量推荐器枚举"若扩装到 N 倍"
PV_SCALE = 1.0
# 当前仿真装机容量(kW) = 真实基准 × 放大系数
PV_CAPACITY_KW = PV_BASE_CAPACITY_KW * PV_SCALE

# ---------------- 储能 ----------------
E_BAT_MAX = 4000.0        # 储能额定容量 kWh (4 MWh，改进版)
P_BAT_MAX = 2000.0        # 储能最大充放电功率 kW (2 MW，2小时储能)
ETA_CH = 0.95             # 充电效率
ETA_DIS = 0.95            # 放电效率
SOC_MIN = 0.2
SOC_MAX = 0.9
SOC_INIT = 0.5

# ---------------- 柔性负荷（设备功率可调） ----------------
# 曝气/泵等设备可变频调节功率。但本方案的定位：柔性负荷默认关闭（负荷刚性），
# 用于"说明储能存在的必要性"——即使曝气可调功率，也解决不了"夜间无光伏"，
# 必须靠储能把白天光伏存下来夜间用。故柔性负荷是可选概念，不追求优化收益。
FLEX_ENABLED = True       # 是否启用柔性负荷错峰（改动2打开，双模式滞回控制曝气下限）
FLEX_MIN = 0.65           # 节能模式曝气下限（常规稳定工况）
FLEX_MAX = 1.00           # 功率调节上限（满负荷）
FLEX_PENALTY = 0.30       # 柔性负荷微惩罚系数（仅 flex_enabled 时生效，抑制无脑开满）

# ---- 双模式滞回 + 安全兜底（专利1迁移，改动2）----
# 安全模式：冲击负荷 或 连续低曝气 时，上调曝气下限保微生物安全
FLEX_MIN_SAFE = 0.80      # 安全模式曝气下限（经验值，收窄调节空间）
FLEX_DOWN_CONT_H = 4      # 连续低曝气判定小时数（贴下限≥N小时 → 切安全模式）
LOAD_SHOCK_RATIO = 0.20   # 冲击负荷波动阈值：日负荷总量相对历史均值波动>20% 判定冲击
HYSTERESIS_DAYS = 3       # 连续重压曝气天数阈值（滞回，防频繁震荡）

# 压曝气成本：给"下调曝气"加正成本，建立"储能充电>下调曝气>弃光"分配优先级。
# 使优化器天然先充满储能、再压曝气、最后才弃光，避免储能闲置而曝气被压惨。
FLEX_DEV_COST = 0.20      # 压曝气偏离成本（>0 启动优先级）

# 曝气总量下调比例（专利1"降低日均曝气总量"的节能本质）：
#   节能模式下 sum(flex) 允许下调到 FLEX_ENERGY_RATIO×基准负荷（分区按需供气、消除末端过量曝气）。
#   冲击/安全模式下应传 1.0（不下调总量）。
FLEX_ENERGY_RATIO = 0.95  # 节能模式最多下调 5% 曝气总量

# ---------------- 并网模式 ----------------
# 自发自用、余电上网：光伏先自用，用不完的余电上网售出
ALLOW_GRID_EXPORT = True  # 是否允许余电上网（True=自发自用余电上网）

# ---------------- 天气/坐标 ----------------
LOCATION_NAME = "zhongshan"
# 中山市大致坐标（中嘉污水厂，中山城区西南部）
LATITUDE = 22.52
LONGITUDE = 113.39

# ---------------- 经济参数（三级电费 + 投资回报率模型） ----------------
# 三级电费：总电费 = 电度电费 + 基本电费(需量) + 力调电费(功率因数)

# ① 电度电费——用户侧分时目录电价（元/kWh）
# 峰平谷时段按附件6运行参数表：高峰10-12/14-19，低谷0-8，尖峰11-12/15-17
PRICE_SELL = 0.453     # 余电上网价：广东燃煤发电基准价 0.453 元/kWh

# ---- 到户电价（电度电费·电能量口径）----
# 污水厂实际购电价 = 售电公司合同「中长期 + 现货联动」：
#   90% 电量按中长期合约价（平段 377 元/MWh × 峰谷系数），10% 电量按现货节点价。
# 注：此为"电能量到户价"近似，未含输配电价/基本电费/力调电费（待优化清单）。
CONTRACT_FLAT_PRICE = 0.377   # 中长期合约平段价 元/kWh（377 元/MWh）
CONTRACT_RATIO = 0.90         # 中长期电量占比（现货联动 = 1 - 0.90 = 0.10）


def tou_ratio(t, is_peak_season=False):
    """广东峰谷分时倍率（相对平段，现行 2021 政策）。

    峰:平:谷 = 1.7 : 1 : 0.38；尖峰 = 峰段×1.25 = 2.125（7/8/9月 + 高温天，简化按 7-9月整月）。
    时段：高峰 10-12、14-19；低谷 0-8；平段其余。
    """
    if is_peak_season and t in [11, 15, 16]:
        return 2.125   # 尖峰（峰段 1.7 × 1.25）
    if t in [10, 11, 14, 15, 16, 17, 18]:
        return 1.7     # 高峰 10-12、14-19
    if t in list(range(0, 8)):
        return 0.38    # 低谷 0-8
    return 1.0         # 平段


def contract_tou_price(t, is_peak_season=False):
    """中长期合约峰谷价（元/kWh）= 平段价 × 峰谷倍率。"""
    return CONTRACT_FLAT_PRICE * tou_ratio(t, is_peak_season)


def tou_price(t, is_peak_season=False):
    """旧目录峰谷价（平段 0.655 元/kWh × 倍率），仅作对比参考，已不用于主口径。"""
    return 0.655 * tou_ratio(t, is_peak_season)


def load_realtime_price():
    """加载广东电力现货节点实时电价，返回 {date: np.array(24)}（元/kWh）。

    读取 PRICE_XLSX「逐时数据」sheet，实时电价列(25-48) ÷1000 转元/kWh，
    负价 clip 到 0。文件缺失时返回 None（调用方回退到 tou_price）。
    """
    import numpy as np
    from datetime import datetime

    if not os.path.exists(PRICE_XLSX):
        return None

    import openpyxl
    wb = openpyxl.load_workbook(PRICE_XLSX, read_only=True, data_only=True)
    ws = wb["逐时数据"]
    out = {}
    for row in ws.iter_rows(min_row=3, values_only=True):  # 前 2 行是表头
        if row[0] is None:
            continue
        d = datetime.strptime(str(row[0]).strip()[:10], "%Y-%m-%d").date()
        vals = [0.0 if v is None else max(float(v), 0.0) / 1000.0 for v in row[25:49]]  # 元/MWh→元/kWh
        if len(vals) == 24:
            out[d] = np.array(vals)
    wb.close()
    return out


# 数据起点（负荷/光伏数据 2025-07-01 起）
DATA_START_DATE = "2025-07-01"

_realtime_price_cache = None


def price_for_day(day_idx: int):
    """返回第 day_idx 天（从 DATA_START_DATE 起）的 24h 到户电价数组（元/kWh）。

    到户价 = CONTRACT_RATIO × 中长期峰谷价 + (1-CONTRACT_RATIO) × 现货节点价。
    尖峰季(7/8/9月)按峰段×1.25 上浮；无现货数据时回退纯中长期峰谷价。结果缓存。
    """
    import numpy as np
    from datetime import datetime, timedelta

    global _realtime_price_cache
    if _realtime_price_cache is None:
        _realtime_price_cache = load_realtime_price()

    target_date = (datetime.strptime(DATA_START_DATE, "%Y-%m-%d") + timedelta(days=day_idx)).date()
    is_peak_season = target_date.month in [7, 8, 9]

    contract = np.array([contract_tou_price(t, is_peak_season) for t in range(24)])

    if _realtime_price_cache is None:
        return contract

    spot = _realtime_price_cache.get(target_date)
    if spot is None:
        return contract
    return CONTRACT_RATIO * contract + (1.0 - CONTRACT_RATIO) * spot


def ef_opt_for_day(day_idx: int):
    """第 day_idx 天的 24h 碳因子（kgCO2/kWh），节点电价代理法构造。

    逐时节点电价 → min-max 归一化 → 映射到 [EF_OPT_LOW, EF_OPT_HIGH]，
    再等比校准到 EF_OPT_ANNUAL_TARGET，保留日内峰谷形态。
    高价时段≈火电顶出→碳强度高，低价时段≈新能源大发→碳强度低。
    返回 np.array(24)。
    """
    import numpy as np
    price = price_for_day(day_idx)
    p = np.asarray(price, dtype=float)
    p_min, p_max = p.min(), p.max()
    if p_max > p_min:
        norm = (p - p_min) / (p_max - p_min)
    else:
        norm = np.zeros_like(p)
    ef = EF_OPT_LOW + norm * (EF_OPT_HIGH - EF_OPT_LOW)
    scale = EF_OPT_ANNUAL_TARGET / ef.mean()
    return ef * scale


# ② 基本电费（需量）—— 储能削峰的真实收益来源
DEMAND_PRICE = 38.0    # 需量电价 元/kW/月

# ③ 力调电费（功率因数奖惩）—— 固定系数，不影响容量优化
PF_TARGET = 0.90       # 功率因数考核值
PF_PENALTY = 0.01      # 力调费率(奖惩比例) ±1%，对容量规划为固定项

# 多目标权重：目标 = w_cost×分时购电成本 + w_green×外购电量
# w_cost 大→偏经济套利；w_green 大→偏绿电/减碳
W_COST = 1.0    # 分时成本权重
W_GREEN = 1.0   # 绿电(外购电量)权重，可调

# ---------------- 电碳双驱：碳因子 + 碳价 ----------------
# 目标函数加"碳成本"项：w_carbon × 碳因子(kgCO2/kWh) × 碳价(元/kg)，
# 让储能/光伏调度同时追求「省电费」+「减碳」，实现电碳双驱。
W_CARBON = 1.0               # 碳成本权重（0=纯经济调度，1=电碳双驱）
CARBON_PRICE = 0.038         # 元/kgCO2 = 38元/吨（广东 GDEA 碳配额成交价，可调参数）
EF_OPT_LOW = 0.30            # 碳因子下界（节点电价代理法，与碳核算口径一致）
EF_OPT_HIGH = 0.65           # 碳因子上界
EF_OPT_ANNUAL_TARGET = 0.4419  # 年均校准目标 = 广东省级电力因子(与模块三对齐)

# 投资成本（单位：元）
PV_INVEST_PER_KW = 4000.0        # 光伏投资 4.0 元/W = 4000 元/kW = 400 万元/MW
BATTERY_E_INVEST_PER_KWH = 1200.0  # 储能能量投资 1.2 元/Wh = 1200 元/kWh
BATTERY_P_INVEST_PER_KW = 800.0   # 储能功率(PCS等) 约 800 元/kW

# 设备寿命 / 回收期基准
PV_LIFETIME_YEARS = 25      # 光伏寿命 25 年
BATTERY_LIFETIME_YEARS = 10 # 储能寿命 10 年
IRR_TARGET = 0.12           # 目标内部收益率 12%


def print_config():
    """打印关键配置，便于运行前核对。"""
    print("=" * 50)
    print("智能调度配置")
    print("=" * 50)
    print(f"光伏容量: 真实基准 {PV_BASE_CAPACITY_KW/1000:.1f} MW × 放大 {PV_SCALE} = {PV_CAPACITY_KW/1000:.1f} MW")
    print(f"储能: {E_BAT_MAX/1000:.0f} MWh / {P_BAT_MAX/1000:.0f} MW")
    print(f"SOC 范围: {SOC_MIN} ~ {SOC_MAX}, 初值 {SOC_INIT}")
    print(f"柔性负荷: {'启用' if FLEX_ENABLED else '关闭(刚性负荷)'}，功率范围 {FLEX_MIN*100:.0f}%~{FLEX_MAX*100:.0f}%")
    print(f"并网模式: 自发自用 + {'余电上网' if ALLOW_GRID_EXPORT else '否'}")
    print(f"多目标: w_cost×分时成本 + w_green×外购电量 (权重 {W_COST}/{W_GREEN})")
    print("=" * 50)
