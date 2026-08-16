# -*- coding: utf-8 -*-
"""策略库：目录约定即注册表。

约定：每个策略是一个 build(cfg, stks) -> BuiltStrategy 函数；
策略文件只回答「组件怎么组装」（hikyuu 组件代码），股票池过滤与
执行由 backtest.py 统一负责。slug 为唯一标识（experiments 引用）。
"""
from __future__ import annotations

from . import ma_cross, tech5
from .base import (BuiltStrategy, StrategyConfig, STRATEGY_BUILDERS,
                   STRATEGY_META, build_strategy, list_strategies)

STRATEGY_BUILDERS.update({
    'ma-cross': ma_cross.build,
    'tech5': tech5.build,
})

STRATEGY_META.update({
    'ma-cross': ma_cross.META,
    'tech5': tech5.META,
})
