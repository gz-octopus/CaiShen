# -*- coding: utf-8 -*-
"""第一闭环策略：sh000001 上证指数 MA(10)/MA(30) 金叉择时（T1 定稿）。

- 因子：hku.MA(CLOSE, 10) / hku.MA(CLOSE, 30) + hku.SG_Cross（金叉买/死叉卖）
- 资金管理：MM_FixedPercent(0.99) 全仓进出（空仓起步）。
  实测（2026-08-14）：p=1.0 时买入金额+交易成本超现金被 hikyuu 直接拒绝
  （TradeManager.cpp "Can't buy"），30 次金叉仅 19 次买进；p=0.99 成本缓冲 1%，
  30 次全部成交且无警告。0.99 即「全仓」的落地形态（T1 定稿修订）。
- 无止损止盈（不配置 ST/TP）
- 交易假设：初始资金 100 万；TC_FixedA2017 + SP_FixedPercent(0.001)；
  信号次日开盘价成交（System 原生 buy_delay/sell_delay 行为）
- A 股规则：仅一字板延迟 + 停牌自然跳过（System 默认）；T+1 不做，报告显式声明偏差
"""
from __future__ import annotations

import hikyuu as hku

STRATEGY_NAME = '上证指数 MA(10)/MA(30) 金叉择时'
STRATEGY_DESC = '单标的择时：MA10 上穿 MA30 金叉全仓买入，死叉全仓卖出；空仓起步、全仓进出、无止损止盈。'


def create_system(tm: hku.TradeManager, fast_n: int = 10, slow_n: int = 30,
                  slippage: float = 0.001) -> hku.System:
    """构建 MA 金叉择时 System（T1 定稿参数，默认不调参）。

    :param tm: TradeManager 账户（crtTM 构造，见 T5 落地约束）
    :param fast_n: MA 快线周期（默认 10）
    :param slow_n: MA 慢线周期（默认 30）
    :param slippage: 滑点比例（SP_FixedPercent，默认 0.001）
    """
    fast = hku.MA(hku.CLOSE(), n=fast_n)
    slow = hku.MA(hku.CLOSE(), n=slow_n)
    sg = hku.SG_Cross(fast, slow)            # 金叉买入 / 死叉卖出
    mm = hku.MM_FixedPercent(0.99)           # 全仓进出（0.99 留 1% 成本缓冲，见模块 docstring）
    sp = hku.SP_FixedPercent(slippage)       # 滑点 0.1%
    # 不传 st/tp：无止损止盈；不传 cn/ev：无额外条件（SYS_Simple 原生默认）
    sys_ = hku.SYS_Simple(tm=tm, sg=sg, mm=mm, sp=sp)
    sys_.name = STRATEGY_NAME
    return sys_


def get_stock(code: str = 'sh000001') -> hku.Stock:
    """获取策略标的（默认 sh000001 上证指数）。"""
    return hku.sm[code]
