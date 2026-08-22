# -*- coding: utf-8 -*-
"""
光伏出力物理模型：辐射 → 逐时功率。

公式：P(t) = 装机(kW) × (G(t) / 1000 W/m²) × PR

  G(t)   逐时辐射 W/m²（OpenMeteo 天气数据）
  PR     系统性能比 Performance Ratio，把组件温度损失、逆变器效率、
         线路损耗、灰尘遮挡、朝向等全部打包成一个综合系数，典型 0.75~0.85。
         本方案用 A 厂真实年发电量反推校准（见 calibrate_pr）。

这是「容量通用化」的地基：任何厂只要有「逐时辐射 + 装机 kW」，
就能算出逐时光伏出力，不再依赖该厂的历史光伏数据（B/C/D 无光伏也能算）。
"""

import numpy as np

G_STC = 1000.0   # 标准测试条件辐射强度 W/m²


def pv_output_from_radiation(rad_wm2, capacity_kw, pr=0.80):
    """逐时辐射 → 逐时功率 kW。

    参数
    ----
    rad_wm2:      逐时辐射 W/m²，形状 (N,) 或 (N, 24)
    capacity_kw:  装机容量 kW（STC 峰值功率）
    pr:           系统性能比 0~1（默认 0.80，实际用 calibrate_pr 校准）

    返回
    ----
    与 rad_wm2 同形状的逐时功率 kW（下限截到 0，夜间辐射为 0 时出力为 0）。
    """
    rad = np.asarray(rad_wm2, dtype=float)
    p = capacity_kw * (rad / G_STC) * pr
    return np.clip(p, 0.0, None)


def calibrate_pr(annual_energy_kwh, capacity_kw, rad_wm2):
    """用真实年发电量反推系统性能比 PR。

    参数
    ----
    annual_energy_kwh: 真实年发电量 kWh
    capacity_kw:       装机 kW
    rad_wm2:           同期逐时辐射 W/m²（任意形状，求和后使用）

    返回
    ----
    PR = 年发电 / (装机 × Σ辐射/1000)，无量纲。
    """
    rad = np.asarray(rad_wm2, dtype=float)
    rad_sum = rad.sum()                       # W/m² · h
    energy_ideal = capacity_kw * rad_sum / G_STC   # PR=1 时的理论年发电 kWh
    if energy_ideal <= 0:
        return 0.0
    return annual_energy_kwh / energy_ideal
