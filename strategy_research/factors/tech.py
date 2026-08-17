# -*- coding: utf-8 -*-
"""技术因子实现（价量可算，全部 hikyuu 指标一行式）。

每个构建函数返回 hku.Factor：name + formula(Indicator) + brief 元数据。
Indicator 无 K 线上下文（裸指标），运行时由 MF/回测绑定数据。
"""
from __future__ import annotations

import hikyuu as hku


def _factor(name: str, formula: hku.Indicator, brief: str) -> hku.Factor:
    return hku.Factor(name, formula, brief=brief)


def build_momentum_20() -> hku.Factor:
    """20 日动量：过去 20 个交易日收益率（ROCP）。"""
    return _factor('momentum_20', hku.ROCP(hku.CLOSE(), n=20), '20 日动量')


def build_reversal_5() -> hku.Factor:
    """5 日反转：短期涨幅的镜像（负 5 日收益），反转因子取负方向。"""
    return _factor('reversal_5', -hku.ROCP(hku.CLOSE(), n=5), '5 日反转')


def build_volatility_20() -> hku.Factor:
    """20 日波动率：收盘价样本标准差（STDEV）。"""
    return _factor('volatility_20', hku.STDEV(hku.CLOSE(), n=20), '20 日波动率')


def build_volume_ratio_20() -> hku.Factor:
    """20 日量比：当日成交量相对 20 日均量的偏离。

    换手率的替代实现：hikyuu 的 TURNOVER/HSL 依赖流通股本
    （stkfinance 表，当前为空返回 NaN），改用纯价量的量比表达活跃度。
    """
    return _factor('volume_ratio_20', hku.VOL() / hku.MA(hku.VOL(), n=20) - 1,
                   '20 日量比（换手率替代）')


def build_ma_bias_20() -> hku.Factor:
    """MA 偏离度：收盘价相对 20 日均线的偏离比例。"""
    return _factor('ma_bias_20', hku.CLOSE() / hku.MA(hku.CLOSE(), n=20) - 1,
                   'MA(20) 偏离度')
