# -*- coding: utf-8 -*-
"""单标的 MA(10)/MA(30) 金叉择时（第一闭环迁移，组合范式表达）。

组合范式：股票池 = [sh000001] + SG_Cross 择时原型系统 + 等权分配 +
每根 K 线评估调仓（adjust_mode='query'，信号驱动而非定期）。
实测（2026-08-16）：本范式结果与第一闭环基线逐位一致
（60 笔交易、期末资产 822621.31、夏普 -0.2224289778、MDD 34.68696762）。
"""
from __future__ import annotations

import hikyuu as hku

from .base import BuiltStrategy, StrategyConfig

META = {
    'name': '上证指数 MA(10)/MA(30) 金叉择时',
    'desc': '单标的择时：MA10 上穿 MA30 金叉全仓买入，死叉全仓卖出（第一闭环迁移，组合范式表达）。',
    'mode': 'system',
}


def _make_query(cfg: StrategyConfig) -> hku.Query:
    from datetime import datetime, timedelta
    end_plus1 = datetime.strptime(cfg.end, '%Y-%m-%d') + timedelta(days=1)
    return hku.Query(
        hku.Datetime(int(cfg.start[:4]), int(cfg.start[5:7]), int(cfg.start[8:10])),
        hku.Datetime(end_plus1.year, end_plus1.month, end_plus1.day),
        hku.Query.DAY, recover_type=hku.Query.FORWARD)


def build(cfg: StrategyConfig, stks: list[hku.Stock]) -> BuiltStrategy:
    sh = hku.sm['sh000001']
    proto = hku.SYS_Simple(
        sg=hku.SG_Cross(hku.MA(hku.CLOSE(), n=10), hku.MA(hku.CLOSE(), n=30)),
        mm=hku.MM_FixedPercent(0.99),   # 全仓（0.99 留 1% 成本缓冲，第一闭环实测定稿）
        sp=hku.SP_FixedPercent(0.001))
    se = hku.SE_Fixed([sh], proto)
    tm = hku.crtTM(date=hku.Datetime(int(cfg.start[:4]), int(cfg.start[5:7]), int(cfg.start[8:10])),
                   init_cash=cfg.init_cash, cost_func=hku.TC_FixedA2017(),
                   name=META['name'])
    pf = hku.PF_Simple(tm=tm, se=se, af=hku.AF_EqualWeight(),
                       adjust_cycle=1, adjust_mode='query')
    return BuiltStrategy(slug='ma-cross', mode='system', pf=pf, query=_make_query(cfg),
                         se=se, meta=dict(META))
