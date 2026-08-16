# -*- coding: utf-8 -*-
"""因子库：目录约定即注册表。

约定：每个因子是一个返回 hku.Factor 的构建函数（无 K 线上下文，
运行时由 MF 绑定）；函数名即因子名（snake_case，唯一）；元数据在
FACTOR_META 中登记（方向：positive/negative/neutral，用于合成前的方向统一）。

因子名称与 K 线类型的组合是 hikyuu 唯一标识（本库固定 DAY）。
日频因子值不落库（hikyuu 计算快于存储读取，官方实践建议）；
原始值不预截面化，截面/标准化由 MF 完成。
"""
from __future__ import annotations

import hikyuu as hku

from . import tech

# 因子注册表：名称 -> 构建函数
FACTOR_BUILDERS: dict[str, callable] = {
    'momentum_20': tech.build_momentum_20,
    'reversal_5': tech.build_reversal_5,
    'volatility_20': tech.build_volatility_20,
    'volume_ratio_20': tech.build_volume_ratio_20,
    'ma_bias_20': tech.build_ma_bias_20,
}

# 因子元数据（hikyuu Factor.brief 之外的登记项）
FACTOR_META: dict[str, dict] = {
    'momentum_20': {'direction': 'positive', 'brief': '20 日动量（ROCP 收益率）'},
    'reversal_5': {'direction': 'negative', 'brief': '5 日反转（负 5 日收益）'},
    'volatility_20': {'direction': 'neutral', 'brief': '20 日波动率（STDEV）'},
    'volume_ratio_20': {'direction': 'positive',
                        'brief': '20 日量比 VOL/MA(VOL,20)-1（换手率替代：stkfinance 表空，流通股本无数据）'},
    'ma_bias_20': {'direction': 'neutral', 'brief': 'MA 偏离度 CLOSE/MA(CLOSE,20)-1'},
}


def build_factor(name: str) -> hku.Factor:
    """按名构建因子对象（构建函数返回无上下文的 hku.Factor）。"""
    if name not in FACTOR_BUILDERS:
        raise KeyError(f'因子不存在: {name}（可用：{", ".join(FACTOR_BUILDERS)}）')
    return FACTOR_BUILDERS[name]()


def list_factors() -> list[str]:
    """全部因子名（注册顺序）。"""
    return list(FACTOR_BUILDERS)


def build_all() -> list[hku.Factor]:
    """构建全部因子（按注册顺序）。"""
    return [f() for f in FACTOR_BUILDERS.values()]
