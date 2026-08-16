# -*- coding: utf-8 -*-
"""五因子等权月度组合（TopN 截面选股）。

组件链（T7 定稿）：MF_EqualWeight → NORM_Zscore(out_extreme=True) →
SE_MultiFactor2(SCFilter_IgnoreNan | TopN) → AF_EqualWeight → PF_Simple
（adjust_mode='month'，每月首个交易日调仓）。

原型系统：SG_AllwaysBuy（截面选股，入选即买）+ MM_Nothing（数量由 AF 分配）。
"""
from __future__ import annotations

import hikyuu as hku

from .. import factors
from .base import BuiltStrategy, StrategyConfig
from .ma_cross import _make_query

META = {
    'name': '五因子等权月度组合（TopN）',
    'desc': '截面组合：动量/反转/波动率/量比/MA偏离 5 因子等权合成 + Zscore 归一化 + '
            'TopN 选股 + 等权分配 + 月度调仓。',
    'mode': 'portfolio',
}


def _make_mf(cfg: StrategyConfig, inds: list[hku.Indicator], stks: list[hku.Stock],
             query: hku.Query) -> hku.MultiFactorBase:
    if cfg.mf == 'equal-weight':
        mf = hku.MF_EqualWeight(inds, stks, query, ref_stk=hku.sm['sh000001'],
                                save_all_factors=True)
    elif cfg.mf == 'icir-weight':
        mf = hku.MF_ICIRWeight(inds, stks, query, ref_stk=hku.sm['sh000001'],
                               save_all_factors=True)
    else:
        raise ValueError(f'未知合成方式: {cfg.mf}')
    return mf


def _make_norm(cfg: StrategyConfig) -> hku.NormalizeBase:
    if cfg.norm == 'zscore':
        return hku.NORM_Zscore(out_extreme=True)
    if cfg.norm == 'quantile-uniform':
        return hku.NORM_Quantile_Uniform()
    if cfg.norm == 'minmax':
        return hku.NORM_MinMax()
    if cfg.norm == 'nothing':
        return hku.NORM_NOTHING()
    raise ValueError(f'未知归一化: {cfg.norm}')


def build(cfg: StrategyConfig, stks: list[hku.Stock]) -> BuiltStrategy:
    query = _make_query(cfg)

    # 因子：cfg.factors 指定子集，空则全部注册因子
    names = cfg.factors or factors.list_factors()
    inds = [factors.build_factor(n).formula for n in names]

    mf = _make_mf(cfg, inds, stks, query)
    mf.set_normalize(_make_norm(cfg))

    se = hku.SE_MultiFactor2(mf, filter=hku.SCFilter_IgnoreNan() | hku.SCFilter_TopN(cfg.topn))
    # 截面选股原型：入选即买。MM_FixedPercent(0.99) 留 1% 成本缓冲——
    # AF 等权分配的资金全额买入会因交易成本溢出被拒（实测大量 Can't buy，
    # 与第一闭环 MM 修订同源）；数量本质由 AF 决定，MM 只做缓冲取整
    proto = hku.SYS_Simple(sg=hku.SG_AllwaysBuy(), mm=hku.MM_FixedPercent(0.99),
                           sp=hku.SP_FixedPercent(0.001))
    se.add_stock_list(stks, proto)

    tm = hku.crtTM(date=hku.Datetime(int(cfg.start[:4]), int(cfg.start[5:7]), int(cfg.start[8:10])),
                   init_cash=cfg.init_cash, cost_func=hku.TC_FixedA2017(),
                   name=META['name'])
    pf = hku.PF_Simple(tm=tm, se=se, af=hku.AF_EqualWeight(),
                       adjust_cycle=cfg.adjust_cycle, adjust_mode=cfg.adjust_mode)
    meta = dict(META)
    meta.update({'factors': names, 'mf': cfg.mf, 'norm': cfg.norm, 'topn': cfg.topn})
    return BuiltStrategy(slug='tech5', mode='portfolio', pf=pf, query=query,
                         se=se, meta=meta)
