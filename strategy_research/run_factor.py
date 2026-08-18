# -*- coding: utf-8 -*-
"""因子评估执行器：按 FACTOR_META.value_type 分流。

- num 因子：IC/ICIR（hikyuu mf.get_ic / get_icir，spearman，全区间序列）+
  分层回测（mf.get_all_scores() 按日截面评分排序 → 剔除 NaN → 等分 N 层 →
  各层等权日收益累计；日频分层口径：纯因子区分度展示，非调仓组合），
  出 factor_report.html（IC 序列图 + 统计表 + 分层累计收益图 + 各层年化表）
- bool 因子（0/1 条件）：事件识别 + 事件后超额收益统计（见 run_event），
  出 factor_forward_returns_report.html
- 股票池：与回测同过滤规则（build_universe）
"""
from __future__ import annotations

import time
from pathlib import Path

import hikyuu as hku
import numpy as np
import pandas as pd

from difoss_stock_util import I, P, W

from . import config as cfg_mod
from . import factors
from .backtest import build_universe
from .run_event import build_price_matrix, render_event_report, study_events
from .strategies import StrategyConfig

FACTOR_REPORT_NAME = 'factor_report.html'
TEMPLATE_PATH = Path(__file__).resolve().parent / 'report' / 'factor_template.html'


def _factor_mf(ind: hku.Indicator, stks: list, query: hku.Query) -> hku.MultiFactorBase:
    """单因子 MF（等权单因子 = 直接评分），save_all_factors 供 IC 提取。"""
    return hku.MF_EqualWeight([ind], stks, query, ref_stk=hku.sm['sh000001'],
                              save_all_factors=True)


def _ic_stats(ic_ind: hku.Indicator) -> dict:
    """IC 序列统计：均值 / ICIR(年化) / 正 IC 占比 / 序列长度。"""
    vals = np.array([float(x) for x in ic_ind])
    vals = vals[np.isfinite(vals)]
    if len(vals) < 2:
        return {'ic_mean': 0.0, 'icir': 0.0, 'ic_pos_ratio': 0.0, 'n': len(vals)}
    icir = vals.mean() / vals.std(ddof=1) * np.sqrt(252) if vals.std(ddof=1) > 1e-12 else 0.0
    return {
        'ic_mean': float(vals.mean()),
        'icir': float(icir),
        'ic_pos_ratio': float((vals > 0).mean() * 100),
        'n': len(vals),
    }


def _layer_returns(scores_by_date: list, close_df: pd.DataFrame, layers: int) -> pd.DataFrame:
    """分层累计收益：每日截面按评分排序分 N 层，各层等权次日收益累计。

    close_df：index=日期，columns=股票代码（前复权收盘，日收益由 pct_change）。
    返回 DataFrame：index=日期，columns=layer 1..N（累计净值，起点 1.0）。
    """
    ret_df = close_df.pct_change().shift(-1)   # 今日分层 → 次日收益
    layer_equity = {i: [] for i in range(layers)}
    dates = []
    for date, score_list in scores_by_date:
        records = [(r.stock.market_code, r.value) for r in score_list]
        records = [(c, v) for c, v in records if c in close_df.columns and np.isfinite(v)]
        if len(records) < layers:
            continue
        records.sort(key=lambda x: x[1], reverse=True)   # 高分在前
        n = len(records)
        date_s = str(date.date())
        if date_s not in ret_df.index:
            continue
        row = ret_df.loc[date_s]
        for i in range(layers):
            lo, hi = int(n * i / layers), int(n * (i + 1) / layers)
            codes = [c for c, _ in records[lo:hi]]
            r = row[codes].mean() if len(codes) else np.nan
            layer_equity[i].append(0.0 if np.isnan(r) else float(r))
        dates.append(date_s)
    eq = pd.DataFrame(layer_equity, index=pd.to_datetime(dates))
    return (1 + eq).cumprod()


def run_factor(start: str | None = None, end: str | None = None, layers: int = 10,
               factor_name: str | None = None,
               entries: tuple[str, ...] = ('d1_open',)) -> Path:
    """因子评估主入口，输出 html 评估报告。

    factor_name 指定时只评估该因子，否则评估全部注册因子。
    entries：bool 因子事件研究的入场变体（见 run_event.ENTRIES）。
    """
    t0 = time.time()
    config = cfg_mod.init_hikyuu()
    cfg_mod.ensure_dirs(config)
    start = start or cfg_mod.DEFAULT_START
    end = end or cfg_mod.DEFAULT_END
    cfg = StrategyConfig(start=start, end=end)

    all_names = factors.list_factors()
    if factor_name:
        if factor_name not in all_names:
            raise KeyError(f'因子不存在: {factor_name}（可用：{", ".join(all_names)}）')
        all_names = [factor_name]
        P(f'====== 因子评估：{factor_name} ======')
    else:
        P('====== 因子评估：IC/ICIR + 分层回测 ======')
    stks = build_universe(cfg, end)
    I(f'股票池：{len(stks)} 只')
    from datetime import datetime, timedelta
    end_plus1 = datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
    query = hku.Query(hku.Datetime(int(start[:4]), int(start[5:7]), int(start[8:10])),
                      hku.Datetime(end_plus1.year, end_plus1.month, end_plus1.day),
                      hku.Query.DAY, recover_type=hku.Query.FORWARD)

    # 全池前复权收盘矩阵（分层收益用；bool 型因子评估时另建开盘矩阵）
    close_df = build_price_matrix(stks, query, 'close')
    I(f'收盘矩阵：{close_df.shape[1]} 只 × {close_df.shape[0]} 日')

    results = []
    num_names = [n for n in all_names
                 if factors.FACTOR_META[n].get('value_type') != 'bool']
    for name in num_names:
        ind = factors.build_factor(name).formula
        mf = _factor_mf(ind, stks, query)
        ic_ind = mf.get_ic(ndays=0)
        icir_ind = mf.get_icir(ir_n=120, ic_n=0)
        stats = _ic_stats(ic_ind)
        stats['icir_hky'] = float([x for x in icir_ind][-1]) if len(icir_ind) > 0 else 0.0
        scores = mf.get_all_scores()
        dates_ic = [str(d.date()) for d in mf.get_datetime_list()]
        ic_series = [{'date': d, 'value': _f(v)} for d, v in zip(dates_ic, ic_ind)]
        layer_eq = _layer_returns(list(zip(mf.get_datetime_list(), scores)), close_df, layers)
        layer_annual = {
            f'L{i+1}': float(layer_eq.iloc[-1, i] ** (252 / len(layer_eq)) - 1)
            if len(layer_eq) > 0 and not np.isnan(layer_eq.iloc[-1, i]) else 0.0
            for i in range(layers)
        }
        results.append({
            'name': name,
            'brief': factors.FACTOR_META[name]['brief'],
            'direction': factors.FACTOR_META[name]['direction'],
            'stats': stats,
            'ic_series': ic_series,
            'layer_dates': [str(d.date()) for d in layer_eq.index],
            'layer_curves': {f'L{i+1}': [round(float(v), 6) for v in layer_eq.iloc[:, i]]
                             for i in range(layers)},
            'layer_annual': layer_annual,
        })
        I(f'{name}: IC 均值 {stats["ic_mean"]:.4f} | ICIR {stats["icir"]:.2f} | '
          f'正 IC 占比 {stats["ic_pos_ratio"]:.1f}%')

    # 图表：IC 序列图 + 分层收益图（matplotlib → base64，多因子共一张图组）
    if results:
        from .report import _png_to_base64  # noqa: F401  复用 base64 工具
        import base64
        from io import BytesIO
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
        matplotlib.rcParams['axes.unicode_minus'] = False

        def _fig_to_b64(fig) -> str:
            buf = BytesIO()
            fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
            plt.close(fig)
            return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')

        # IC 序列图（分面）
        n_f = len(results)
        fig, axes = plt.subplots(n_f, 1, figsize=(12, 1.6 * n_f), sharex=True)
        if n_f == 1:
            axes = [axes]
        for ax, r in zip(axes, results):
            ax.plot([x['date'] for x in r['ic_series']], [x['value'] for x in r['ic_series']],
                    color='#2563eb', linewidth=0.6)
            ax.axhline(0, color='#9ca3af', linewidth=0.5)
            ax.set_title(f"{r['name']} — IC 均值 {r['stats']['ic_mean']:.4f} / "
                         f"ICIR {r['stats']['icir']:.2f} / 正 IC 占比 {r['stats']['ic_pos_ratio']:.0f}%")
        ic_img = _fig_to_b64(fig)

        # 分层收益图（每因子一张，10 层曲线）
        layer_imgs = []
        for r in results:
            fig, ax = plt.subplots(figsize=(10, 3.2))
            cmap = plt.cm.RdYlGn
            for i in range(layers):
                key = f'L{i+1}'
                ax.plot(r['layer_dates'], r['layer_curves'][key],
                        color=cmap(i / (layers - 1)), linewidth=0.8, label=key)
            ax.set_title(f"{r['name']} 分层累计净值（L1 最高分 … L{layers} 最低分）")
            ax.grid(True, alpha=0.3)
            ax.legend(ncol=layers, fontsize=7, loc='upper left')
            layer_imgs.append(_fig_to_b64(fig))

        # html 渲染
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH.parent)))
        template = env.get_template(TEMPLATE_PATH.name)
        html = template.render(
            start=start, end=end, layers=layers,
            stock_count=len(stks), generated_at=pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
            ic_img=ic_img, layer_imgs=layer_imgs, results=results)
        out = config.report_dir / FACTOR_REPORT_NAME
        out.write_text(html, encoding='utf-8')
        I(f'因子评估报告生成：{out}（耗时 {time.time() - t0:.1f}s）')
    else:
        W('无 num 型因子，跳过因子评估报告')
        out = None

    # bool 因子 → 事件研究（复用股票池与收盘矩阵，另建开盘/low 矩阵）
    event_path = None
    bool_names = [n for n in all_names
                  if factors.FACTOR_META[n].get('value_type') == 'bool']
    if bool_names:
        open_df = build_price_matrix(stks, query, 'open')
        low_df = build_price_matrix(stks, query, 'low')
        ev_results = study_events(stks, query, open_df, close_df, low_df,
                                  factor_name=factor_name if factor_name else None,
                                  entries=entries)
        if ev_results:
            event_path = render_event_report(ev_results, config, len(stks), start, end)
        else:
            W('bool 因子无事件样本，未生成事件报告')
    return out, event_path


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float('nan')
