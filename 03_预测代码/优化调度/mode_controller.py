# -*- coding: utf-8 -*-
"""
双模式滞回状态机（专利1《低碳深度脱氮智能控制》迁移）

核心：把固定曝气下限（FLEX_MIN=0.65）升级为双模式动态下限，
用"负荷波动率"和"连续低曝气时长"两个可从总负荷时序算出的代理指标，
替代专利里无法获取的微生物/DOW 在线数据。

模式：
  节能模式：曝气下限 65%（常规稳定工况），最大化消纳光伏
  安全模式：曝气下限 80%（冲击负荷 或 连续低曝气），收窄调节空间保微生物安全

触发规则（滞回防震荡）：
  1. 冲击负荷豁免：当日负荷日总量相对前 7 日均值波动 > LOAD_SHOCK_RATIO(20%)
     → 当日走安全模式，且曝气刚性不下调（flex_min=flex_max=1.0，等于关闭柔性）
  2. 连续低曝气：昨日曝气有 ≥ FLEX_DOWN_CONT_H(4h) 贴在下限
     → 今日上调下限到 80%
  3. 滞回：连续 HYSTERESIS_DAYS(3天) 重压曝气才切安全；安全模式至少维持 1 天才允许切回
"""

import numpy as np


class ModeController:
    """
    跨天双模式状态机，持"前 N 日负荷"和"昨日优化结果"状态，
    判定每日走节能/安全模式，返回该日 flex_min_override 值。
    """

    def __init__(self, flex_min, flex_min_safe, flex_max,
                 flex_down_cont_h, load_shock_ratio, hysteresis_days,
                 flex_energy_ratio=0.95, shock_rigid=True):
        self.flex_min = flex_min                  # 节能模式下限 0.65
        self.flex_min_safe = flex_min_safe        # 安全模式下限 0.80
        self.flex_max = flex_max                  # 上限 1.0
        self.flex_down_cont_h = flex_down_cont_h  # 连续低曝气判定小时数
        self.load_shock_ratio = load_shock_ratio  # 冲击负荷波动阈值
        self.hysteresis_days = hysteresis_days    # 滞回天数
        self.flex_energy_ratio = flex_energy_ratio  # 节能模式曝气总量下调比例
        self.shock_rigid = shock_rigid            # 冲击负荷是否刚性(不下调)

        # 状态：历史负荷日总量（滚动队列，用于冲击判定）
        self.load_daily_sum_window = []   # 存近 7 日负荷日总量
        # 状态：连续重压曝气天数 + 昨日贴下限小时数
        self.consecutive_low_days = 0
        self.last_low_hours = 0
        # 当前模式（'eco' 节能 / 'safe' 安全）
        self.mode = 'eco'
        self.safe_min_days = 0            # 安全模式已持续天数（滞回用）

    def reset(self):
        self.load_daily_sum_window = []
        self.consecutive_low_days = 0
        self.last_low_hours = 0
        self.mode = 'eco'
        self.safe_min_days = 0

    def decide(self, load_kw):
        """
        给定今日负荷时序（kW, 长度 24），判定今日模式并返回 flex_min_override。

        返回 (flex_min_override, mode, is_shock)
          - flex_min_override: 传给 daily_opt_dispatch 的曝气下限
          - mode: 'eco' / 'safe'
          - is_shock: 是否触发冲击负荷豁免（冲击时曝气刚性）——由 update 里处理刚性
        """
        load_sum = float(np.sum(load_kw))

        # 1. 冲击负荷判定（需至少 7 日历史数据方可判，前期默认非冲击）
        is_shock = False
        if len(self.load_daily_sum_window) >= 7:
            hist_mean = float(np.mean(self.load_daily_sum_window[-7:]))
            if hist_mean > 0 and abs(load_sum - hist_mean) / hist_mean > self.load_shock_ratio:
                is_shock = True

        # 2. 连续低曝气判定
        low_stress = self.last_low_hours >= self.flex_down_cont_h

        # 3. 模式迁移（滞回）
        # 进入安全模式条件：冲击负荷(立即) 或 连续低曝气满 hyster days
        if is_shock:
            new_mode = 'safe'
            self.consecutive_low_days = 0
        elif low_stress:
            self.consecutive_low_days += 1
            if self.consecutive_low_days >= self.hysteresis_days:
                new_mode = 'safe'
            else:
                new_mode = self.mode
        else:
            # 无低曝气压力：连续计数清零，可切回节能
            self.consecutive_low_days = 0
            new_mode = 'eco'

        # 滞回：安全模式至少维持 1 天，避免频繁震荡
        if self.mode == 'safe' and new_mode == 'eco':
            if self.safe_min_days >= 1:
                self.mode = 'eco'
                self.safe_min_days = 0
            else:
                self.mode = 'safe'   # 还需再维持 1 天
        else:
            self.mode = new_mode

        if self.mode == 'safe':
            self.safe_min_days += 1
        else:
            self.safe_min_days = 0

        # 4. 确定 flex_min_override 与 flex_energy_ratio
        if is_shock and self.shock_rigid:
            # 冲击负荷：曝气刚性，不下调（下限=上限=1.0，总量不降）
            flex_min_override = 1.0
            flex_energy_ratio = 1.0
        elif self.mode == 'safe':
            flex_min_override = self.flex_min_safe
            flex_energy_ratio = 1.0
        else:
            flex_min_override = self.flex_min
            flex_energy_ratio = self.flex_energy_ratio

        # 记录今日负荷日总量（供后续冲击判定）
        self.load_daily_sum_window.append(load_sum)
        if len(self.load_daily_sum_window) > 7:
            self.load_daily_sum_window.pop(0)

        return flex_min_override, flex_energy_ratio, self.mode, is_shock

    def update_after_optimize(self, res, load_kw=None):
        """优化后回调：根据今日结果更新"昨日贴下限小时数"等状态。

        判定"低曝气"：flex_down（压降量）> 1% × 基准负荷均值 的小时数。
        避免用绝对阈值(如1e-3 kW)把浮点噪声误判为压曝气（曾导致安全模式锁死99%）。
        """
        if res is None or res.get("flex") is None:
            self.last_low_hours = 0
            return
        if res.get("flex_down") is not None:
            down = res["flex_down"]
            if load_kw is not None:
                thr = 0.01 * float(np.mean(load_kw))
            else:
                thr = 1.0  # 无基准负荷时退化到绝对阈值 1 kW
            self.last_low_hours = int(np.sum(down > thr))
        else:
            self.last_low_hours = 0
