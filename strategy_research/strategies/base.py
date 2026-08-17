# -*- coding: utf-8 -*-
"""策略库基础类型与注册表（无任何策略实现依赖，避免循环导入）。"""
from __future__ import annotations

from dataclasses import dataclass, field

import hikyuu as hku

# 策略注册表：slug -> build 函数（由 strategies/__init__.py 注册）
STRATEGY_BUILDERS: dict[str, callable] = {}
# 策略元信息：slug -> {name, desc, mode}
STRATEGY_META: dict[str, dict] = {}


@dataclass
class StrategyConfig:
    """策略运行参数（CLI 显式 > experiment config > 默认值）。"""
    strategy: str = 'tech5'
    topn: int = 10
    mf: str = 'equal-weight'            # equal-weight | icir-weight
    norm: str = 'zscore'                # zscore | quantile-uniform | minmax | nothing
    adjust_cycle: int = 1               # 月度调仓：每月第 N 个交易日
    adjust_mode: str = 'month'          # month | query | day
    init_cash: float = 1_000_000
    start: str = '2020-01-02'
    end: str = '2026-08-13'
    exclude_st: bool = True
    min_listed_days: int = 60
    min_active_days: int = 20
    factors: list = field(default_factory=list)   # 空 = 全部注册因子


@dataclass
class BuiltStrategy:
    """策略组装产物：PF 已含 tm/se/af，执行器直接 pf.run(query)。

    se 单独保留引用：调仓明细提取（每调仓日的入选标的）需要。
    """
    slug: str
    mode: str                          # system（单标的择时）| portfolio（截面组合）
    pf: hku.Portfolio
    query: hku.Query
    se: hku.SelectorBase = None
    meta: dict = field(default_factory=dict)   # 报告头部信息（名称/描述等）


def list_strategies() -> list[str]:
    return list(STRATEGY_BUILDERS)


def build_strategy(cfg: StrategyConfig, stks: list[hku.Stock]) -> BuiltStrategy:
    if cfg.strategy not in STRATEGY_BUILDERS:
        raise KeyError(f'策略不存在: {cfg.strategy}（可用：{", ".join(STRATEGY_BUILDERS)}）')
    return STRATEGY_BUILDERS[cfg.strategy](cfg, stks)
