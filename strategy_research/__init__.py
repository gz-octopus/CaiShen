# -*- coding: utf-8 -*-
"""strategy_research — CaiShen 策略研究回测系统（hikyuu 2.8.1 主架构）。

第一闭环：数据（TdxKDataDriver 直读）→ 因子（MA）→ 策略（金叉择时）→
回测（System + TradeManager）→ 报告（Performance 53 项 + html）。

入口：python -m strategy_research [check|backtest|report|first-loop]
设计文档见 docs/wayfinder/。
"""

__version__ = '0.1.0'
