# -*- coding: utf-8 -*-
"""
储能优化层：单日 24h 线性规划调度（自发自用 + 余电上网 + 柔性负荷功率可调）

核心：曝气/泵等设备功率可调（[flex_min, flex_max]×基准负荷），
白天光伏多时开大(多消纳)，夜间无光伏时开小(省电)，靠储能 + 电网兜底。

变量向量 x（nvar = 7*24 = 168）：
  x[0:24]     pch      充电功率 (kW, >=0)
  x[24:48]    pdis     放电功率 (kW, >=0)
  x[48:72]    soc      荷电状态 (SOC_MIN ~ SOC_MAX)
  x[72:96]    psell    余电上网功率 (kW, >=0, <= 光伏出力 pv)
  x[96:120]   pgrid    电网买电功率 (kW, >=0)
  x[120:144]  flex     实际用电功率 (负荷可调, flex_min~flex_max × 基准负荷)
  x[144:168]  flex_down 曝气压降量 (kW, >=0, >= 基准负荷 - flex)

富余光伏分配优先级（改动2落地）：
  储能充电(最高) → 下调曝气(次高) → 弃光(最低)
  通过目标函数 flex_down 项（FLEX_DEV_COST）给"压曝气"加正成本实现。
"""

import numpy as np
from scipy.optimize import linprog


def daily_opt_dispatch(
    pv_kw,
    load_kw,
    E_max=16000.0,
    P_max=8000.0,
    eta_ch=0.95,
    eta_dis=0.95,
    soc_min=0.2,
    soc_max=0.9,
    soc0=0.5,
    flex_min=0.65,
    flex_max=1.00,
    flex_penalty=0.30,
    flex_enabled=False,
    flex_min_override=None,
    flex_dev_cost=0.20,
    flex_energy_ratio=0.95,
    price=None,
    w_cost=1.0,
    w_green=1.0,
    w_carbon=1.0,
    carbon_price=0.038,
    ef_opt=None,
):
    """
    单日 24h 储能优化调度（多目标：分时购电成本 + 绿电）。

    目标：
      c[pgrid] = w_cost×分时电价 + w_green       → 少买电、低谷充高峰放
      c[flex]  = flex_penalty                    → 抑制无脑开满曝气
      c[flex_down] = flex_dev_cost               → 给"压曝气"加正成本，实现分配优先级

    flex_min_override: 传入今日实际曝气下限（双模式状态机决定）。None 则用 flex_min。

    返回 dict: {pch, pdis, soc, psell, pgrid, pbat, flex, flex_down,
                buy_kwh, export_kwh, net_grid_kwh, green_ratio, cost_yuan, status,
                chg_kwh, dis_kwh, chg_pv_kwh, dis_replace_kwh}
    """
    pv = np.asarray(pv_kw, dtype=float)
    load = np.asarray(load_kw, dtype=float)
    H = 24
    nvar = 7 * H

    if flex_min_override is not None:
        flex_min = flex_min_override

    if price is None:
        price = np.full(H, 0.391)

    if ef_opt is None:
        ef_opt = np.zeros(H)
    else:
        ef_opt = np.asarray(ef_opt, dtype=float)

    i_pch = 0
    i_pdis = H
    i_soc = 2 * H
    i_psell = 3 * H
    i_pgrid = 4 * H
    i_flex = 5 * H
    i_flex_down = 6 * H

    has_battery = E_max > 0 and P_max > 0

    # 目标函数
    c = np.zeros(nvar)
    for t in range(H):
        c[i_pgrid + t] = w_cost * price[t] + w_green * 1.0 + w_carbon * ef_opt[t] * carbon_price
        c[i_flex + t] = flex_penalty        # 抑制无脑开满曝气
        c[i_flex_down + t] = flex_dev_cost  # 压曝气有成本 → 先充储能、再压曝气、最后弃光

    A_eq = []
    b_eq = []

    # 功率平衡等式（逐时）：
    # 光伏 - 上网 + 放电 - 充电 + 买电 = 实际用电 flex
    # => -pch + pdis - psell + pgrid - flex = -pv
    for t in range(H):
        row = np.zeros(nvar)
        row[i_pch + t] = -1.0
        row[i_pdis + t] = 1.0
        row[i_psell + t] = -1.0
        row[i_pgrid + t] = 1.0
        row[i_flex + t] = -1.0
        A_eq.append(row)
        b_eq.append(-pv[t])

    # SOC 递推等式
    if has_battery:
        for t in range(H):
            row = np.zeros(nvar)
            row[i_soc + t] = 1.0
            row[i_pch + t] = -eta_ch / E_max
            row[i_pdis + t] = 1.0 / (E_max * eta_dis)
            if t == 0:
                A_eq.append(row)
                b_eq.append(soc0)
            else:
                row[i_soc + t - 1] = -1.0
                A_eq.append(row)
                b_eq.append(0.0)

    # 日总用电量（曝气总量）约束：节能模式下允许下调至 flex_energy_ratio×基准，
    # 对应专利1"降低日均曝气总量"的节能本质（分区按需供气、消除末端过量曝气）。
    A_ub = []
    b_ub = []
    # 上限 sum(flex) <= sum(load)（不能超额曝气）
    row_ub = np.zeros(nvar)
    for t in range(H):
        row_ub[i_flex + t] = 1.0
    A_ub.append(row_ub)
    b_ub.append(load.sum())
    # 下限 sum(flex) >= flex_energy_ratio×sum(load)（节能模式可下压，冲击/安全模式 ratio=1）
    row_lb = np.zeros(nvar)
    for t in range(H):
        row_lb[i_flex + t] = -1.0
    A_ub.append(row_lb)
    b_ub.append(-flex_energy_ratio * load.sum())

    # flex_down 定义约束（不等式，用 A_ub）：flex_down >= 基准负荷 - flex
    # 即压降量不小于基准负荷与实际用电之差（flex 上调时差为负，flex_down 取下界 0）
    # 等价变形为 <= 形式：-flex - flex_down <= -load[t]
    for t in range(H):
        row = np.zeros(nvar)
        row[i_flex + t] = -1.0
        row[i_flex_down + t] = -1.0
        A_ub.append(row)
        b_ub.append(-load[t])

    A_eq = np.array(A_eq)
    b_eq = np.array(b_eq)
    A_ub = np.array(A_ub)
    b_ub = np.array(b_ub)

    # ---- 上下界 ----
    lb = np.zeros(nvar)
    ub = np.full(nvar, np.inf)
    for t in range(H):
        if has_battery:
            ub[i_pch + t] = P_max
            ub[i_pdis + t] = P_max
            ub[i_soc + t] = soc_max
            lb[i_soc + t] = soc_min
        else:
            ub[i_pch + t] = 0.0
            ub[i_pdis + t] = 0.0
            ub[i_soc + t] = 0.0
        ub[i_psell + t] = pv[t]
        # 柔性负荷：关闭(刚性)时 flex 锁死=基准负荷；开启时功率可调
        if flex_enabled:
            ub[i_flex + t] = flex_max * load[t]
            lb[i_flex + t] = flex_min * load[t]
        else:
            ub[i_flex + t] = load[t]
            lb[i_flex + t] = load[t]
        # flex_down 上界 = 基准负荷（最大压降不超过基准负荷）
        ub[i_flex_down + t] = load[t]

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=list(zip(lb, ub)), method="highs")

    status = res.status if hasattr(res, "status") else None
    if not res.success:
        return {
            "status": status,
            "message": res.message if hasattr(res, "message") else "求解失败",
            "pch": None, "pdis": None, "soc": None,
            "psell": None, "pgrid": None, "flex": None, "pbat": None,
            "flex_down": None,
        }

    x = res.x
    pch = x[i_pch:i_pch + H]
    pdis = x[i_pdis:i_pdis + H]
    soc = x[i_soc:i_soc + H]
    psell = x[i_psell:i_psell + H]
    pgrid = x[i_pgrid:i_pgrid + H]
    flex = x[i_flex:i_flex + H]
    pbat = pdis - pch
    flex_down = x[i_flex_down:i_flex_down + H]

    buy_kwh = pgrid.sum()
    export_kwh = psell.sum()
    net_grid_kwh = buy_kwh - export_kwh
    # 绿电占比统一口径：光伏发电量 ÷ 原始负荷（储能只搬运时间、不新增绿电）
    pv_total = pv.sum()
    load_total = load.sum()
    green_ratio = pv_total / load_total * 100 if load_total > 0 else 0.0
    cost_yuan = np.sum(pgrid * price)
    carbon_kg = np.sum(pgrid * ef_opt)            # 当日购电碳排放 (kgCO2)
    carbon_cost_yuan = carbon_kg * carbon_price    # 当日碳成本 (元)

    # 储能减碳统计（供后置碳核算拆分"储能单独减排"贡献，docx 第三节）
    chg_kwh = pch.sum()              # 储能总充电量
    dis_kwh = pdis.sum()             # 储能总放电量
    # 充电中来自光伏的部分：光伏扣除上网后，优先给储能充电，逐时取 min(充电, 光伏可充部分)
    chg_pv_kwh = 0.0
    for t in range(H):
        pv_avail = pv[t] - psell[t]  # 光伏里"留厂内"（自用+充电）的部分
        chg_pv_kwh += min(pch[t], max(pv_avail, 0.0))
    # 放电"真正被负荷吸收"的部分（替代购电），逐时取 min(放电, 负荷)
    dis_replace_kwh = np.minimum(pdis, flex).sum()

    return {
        "status": status,
        "pch": pch, "pdis": pdis, "soc": soc,
        "psell": psell, "pgrid": pgrid, "flex": flex, "pbat": pbat,
        "flex_down": flex_down,
        "buy_kwh": buy_kwh, "export_kwh": export_kwh,
        "net_grid_kwh": net_grid_kwh, "green_ratio": green_ratio,
        "cost_yuan": cost_yuan,
        "carbon_kg": carbon_kg, "carbon_cost_yuan": carbon_cost_yuan,
        "objective_value": res.fun,
        # 储能减碳统计项
        "chg_kwh": chg_kwh, "dis_kwh": dis_kwh,
        "chg_pv_kwh": chg_pv_kwh, "dis_replace_kwh": dis_replace_kwh,
    }
