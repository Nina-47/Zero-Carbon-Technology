# -*- coding: utf-8 -*-
"""
入口：跑一次"明日运行决策"，输出操作员可执行的操作建议。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decision_engine import run_daily_decision, print_decision


if __name__ == "__main__":
    # 目标日：默认最后一天；可传命令行参数指定下标
    target_idx = int(sys.argv[1]) if len(sys.argv) > 1 else -1

    result = run_daily_decision(target_day_idx=target_idx, k=5)
    print_decision(result)
