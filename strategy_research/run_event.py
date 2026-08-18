# -*- coding: utf-8 -*-
"""事件研究执行器：事件识别 → 事件后超额收益统计 → html 报告。

- 事件识别：bool 型因子逐股票计算（factor.get_value），值为 1 的日期即事件日 D
- 事件后收益：D+1 开盘买入 → D+n 收盘（市场交易日历口径）；买入日停牌
  （无开盘价）或一字板（开盘 ≥ 涨停价，买不进）剔除该样本，窗口内停牌
  （卖出日无收盘价）记 NaN 剔除
- 基准：同事件日、同窗口的全池等权收益（主基准），sh000001 同窗口叠加展示
- 输出：factor_forward_returns_report.html（样本概览 / 累计收益曲线 / 窗口统计表 / 年度分面）

study_events（识别+统计）与 render_event_report（图表+html）分离，
供 factor 命令按 value_type 路由时与其他评估共用价格矩阵。
"""
from __future__ import annotations

import math
from pathlib import Path

import hikyuu as hku
import numpy as np
import pandas as pd

from difoss_stock_util import I, P, W

from . import config as cfg_mod
from . import factors
from .backtest import build_universe
from .strategies import StrategyConfig

EVENT_REPORT_NAME = 'factor_forward_returns_report.html'
TEMPLATE_PATH = Path(__file__).resolve().parent / 'report' / 'event_template.html'

WINDOWS = [1, 3, 5, 10, 20]      # 窗口统计表
CURVE_MAX = 20                   # 累计收益曲线绘制到 +20 日
ANNUAL_WINDOW = 5                # 年度分面所用窗口
MAX_FWD_RET = 10.0               # 窗口收益 |ret| 上限（1000%）


def build_price_matrix(stks: list, query: hku.Query, field: str) -> pd.DataFrame:
    """全池价格矩阵：index=日期（各股票 K 线日期的并集，即市场交易日历），
    columns=stock.market_code。停牌日无 K 线，对应位置为 NaN。"""
    series = {}
    for stk in stks:
        k = stk.get_kdata(query)
        if len(k) > 0:
            series[stk.market_code] = pd.Series(
                [float(getattr(x, field)) for x in k],
                index=[str(d.date()) for d in k.get_datetime_list()])
    df = pd.concat(series, axis=1)
    df.index = pd.to_datetime(df.index)
    return df


def _round_half_up(x: float) -> float:
    """四舍五入到 0.01（与 hikyuu roundEx 一致的 half away from zero）。

    +1e-9：消除浮点表示误差（如 11.605 存为 11.604999… 时仍应进位到 11.61）。
    """
    return math.floor(x * 100 + 0.5 + 1e-9) / 100


def _limit_price(prev_close: float, code: str) -> float:
    """当日涨停价：主板 10%、双创 20%（股票池默认剔除 ST，无 5% 档）。"""
    pct = 0.20 if code.startswith(('SH68', 'SZ30')) else 0.10
    return _round_half_up(prev_close * (1 + pct))


def _identify_events(factor: hku.Factor, stks: list, query: hku.Query) -> pd.DataFrame:
    """逐股票计算 bool 因子，返回事件表（columns: code, date）。"""
    rows = []
    for stk in stks:
        k = stk.get_kdata(query)
        if len(k) == 0:
            continue
        ind = factor.get_value(stk, query)
        dates = [str(d.date()) for d in k.get_datetime_list()]
        n = min(len(dates), len(ind))
        for i in range(ind.discard, n):
            if float(ind[i]) == 1.0:
                rows.append((stk.market_code, dates[i]))
    return pd.DataFrame(rows, columns=['code', 'date'])


def _fwd_window_returns(open_df: pd.DataFrame, close_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """全池「D+1 开盘 → D+n 收盘」收益矩阵，行 = 买入日的前一交易日 D。

    |ret| > MAX_FWD_RET 记 NaN：前复权下低价股除息穿越 0 时会产生
    天文数字的假收益（如 open 恰为 1e-8 元），20 日内正常收益远达不到 10 倍。
    """
    ret = close_df.shift(-n) / open_df.shift(-1) - 1
    ret[ret.abs() > MAX_FWD_RET] = np.nan
    return ret


def _t_stat(x: np.ndarray) -> float:
    """超额样本的 t 值（均值 / 标准误），样本不足 2 或无方差时为 0。"""
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return 0.0
    sd = x.std(ddof=1)
    return float(x.mean() / (sd / math.sqrt(len(x)))) if sd > 1e-12 else 0.0


def _nanmean(x) -> float:
    x = x[np.isfinite(x)]
    return float(x.mean()) if len(x) else float('nan')


def _row_nanmean(a: np.ndarray) -> np.ndarray:
    """按行 nanmean：全 NaN 行返回 NaN（避免 nanmean 对空切片的警告）。"""
    cnt = np.sum(~np.isnan(a), axis=1)
    s = np.nansum(a, axis=1)
    return np.divide(s, cnt, out=np.full_like(s, np.nan), where=cnt > 0)


def study_events(stks: list, query: hku.Query, open_df: pd.DataFrame,
                 close_df: pd.DataFrame, factor_name: str | None = None) -> list[dict]:
    """对 bool 型因子做事件识别与事件后收益统计，返回报告数据（不含图表）。

    factor_name 指定时只处理该因子，否则处理全部 bool 型因子。
    """
    col_of = {c: i for i, c in enumerate(close_df.columns)}
    sh = hku.sm['sh000001']
    sh_open = build_price_matrix([sh], query, 'open').reindex(close_df.index)
    sh_close = build_price_matrix([sh], query, 'close').reindex(close_df.index)

    results = []
    for name in factors.list_factors():
        if factors.FACTOR_META[name].get('value_type') != 'bool':
            continue
        if factor_name and name != factor_name:
            continue
        factor = factors.build_factor(name)
        events = _identify_events(factor, stks, query)
        I(f'{name}: 事件 {len(events)} 个')
        if len(events) == 0:
            W(f'{name}: 无事件样本，跳过')
            continue

        # 事件日 → 市场日历位置与矩阵列位
        pos = close_df.index.get_indexer(pd.to_datetime(events['date']))
        cols = np.array([col_of[c] for c in events['code']])
        open1 = open_df.shift(-1).values[pos, cols]        # D+1 开盘（尾行 NaN）
        close0 = close_df.values[pos, cols]                # 事件日收盘
        limit = np.array([_limit_price(c0, c) for c0, c in zip(close0, events['code'])])
        valid = (pos >= 0) & np.isfinite(open1) & np.isfinite(close0) & (open1 < limit)
        I(f'{name}: 有效样本 {int(valid.sum())}（剔除一字板/停牌 {int((~valid).sum())}）')

        # 窗口统计表
        stats = []
        for n in WINDOWS:
            ret_n = _fwd_window_returns(open_df, close_df, n)
            er = ret_n.values[pos, cols][valid]
            bench = _row_nanmean(ret_n.values)[pos][valid]
            excess = er - bench
            stats.append({
                'n': n,
                'samples': int(np.isfinite(er).sum()),
                'mean_ret': round(_nanmean(er), 6),
                'mean_excess': round(_nanmean(excess), 6),
                'median_excess': round(float(np.nanmedian(excess)), 6),
                'pos_ratio': round(_nanmean(excess > 0) * 100, 2),
                't_stat': round(_t_stat(excess), 3),
            })

        # 累计收益曲线（+1 ~ +20 日）：事件组 / 全池等权 / 指数 / 超额
        curve_event, curve_bench, curve_sh, curve_excess = [], [], [], []
        for n in range(1, CURVE_MAX + 1):
            ret_n = _fwd_window_returns(open_df, close_df, n)
            er = ret_n.values[pos, cols][valid]
            bn = _row_nanmean(ret_n.values)[pos][valid]
            sh_n = _fwd_window_returns(sh_open, sh_close, n).values[pos, 0][valid]
            curve_event.append(round(_nanmean(er), 6))
            curve_bench.append(round(_nanmean(bn), 6))
            curve_sh.append(round(_nanmean(sh_n), 6))
            curve_excess.append(round(_nanmean(er - bn), 6))

        # 年度分面（窗口 ANNUAL_WINDOW 的平均超额）
        ret5 = _fwd_window_returns(open_df, close_df, ANNUAL_WINDOW)
        excess5 = ret5.values[pos, cols] - _row_nanmean(ret5.values)[pos]
        dfy = pd.DataFrame({
            'year': pd.to_datetime(events['date'].to_numpy()[valid]).year,
            'excess': excess5[valid]})
        annual = [{'year': int(y), 'events': int(len(g)),
                   'mean_excess': round(_nanmean(g['excess'].to_numpy()), 6)}
                  for y, g in dfy.groupby('year')]

        results.append({
            'name': name,
            'brief': factors.FACTOR_META[name]['brief'],
            'overview': {
                'events': int(len(events)),
                'stocks': int(events['code'].nunique()),
                'valid': int(valid.sum()),
                'first_date': str(pd.to_datetime(events['date']).min().date()),
                'last_date': str(pd.to_datetime(events['date']).max().date()),
                'years': len(annual),
            },
            'stats': stats,
            'curve': {'xs': list(range(1, CURVE_MAX + 1)), 'event': curve_event,
                      'bench': curve_bench, 'sh': curve_sh, 'excess': curve_excess},
            'annual': annual,
        })
    return results


def render_event_report(results: list[dict], config: cfg_mod.HikyuuConfig,
                        stock_count: int, start: str, end: str) -> Path:
    """渲染事件研究报告：图表 base64 + jinja2 html，输出到报告目录。"""
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

    for r in results:
        xs = r['curve']['xs']
        # 图 1：事件后累计超额收益（事件组 - 全池等权，逐日）
        fig, ax = plt.subplots(figsize=(10, 3.2))
        ax.plot(xs, r['curve']['excess'], color='#2563eb', linewidth=1.2)
        ax.axhline(0, color='#9ca3af', linewidth=0.5)
        ax.set_title(f"{r['name']} 事件后累计超额收益（事件组 - 全池等权，逐日）")
        ax.set_xlabel('事件后交易日'); ax.set_ylabel('累计超额')
        ax.grid(True, alpha=0.3)
        r['excess_img'] = _fig_to_b64(fig)

        # 图 2：累计净值对比（事件组 / 全池等权 / 上证指数）
        fig, ax = plt.subplots(figsize=(10, 3.2))
        ax.plot(xs, [1 + v for v in r['curve']['event']], color='#2563eb',
                linewidth=1.2, label='事件组')
        ax.plot(xs, [1 + v for v in r['curve']['bench']], color='#9ca3af',
                linewidth=1.2, label='全池等权')
        ax.plot(xs, [1 + v for v in r['curve']['sh']], color='#dc2626',
                linewidth=1.2, label='上证指数')
        ax.set_title(f"{r['name']} 事件后累计净值对比（D+1 开盘买入）")
        ax.set_xlabel('事件后交易日'); ax.set_ylabel('累计净值')
        ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
        r['curve_img'] = _fig_to_b64(fig)

        # 图 3：年度分面（事件数柱 + 平均超额线，双轴）
        if r['annual']:
            years = [a['year'] for a in r['annual']]
            fig, ax = plt.subplots(figsize=(10, 3.2))
            ax.bar(years, [a['events'] for a in r['annual']],
                   color='#e5e7eb', label='事件数')
            ax.set_ylabel('事件数')
            ax2 = ax.twinx()
            ax2.plot(years, [a['mean_excess'] for a in r['annual']],
                     color='#2563eb', marker='o', linewidth=1, label='平均超额')
            ax2.axhline(0, color='#9ca3af', linewidth=0.5)
            ax2.set_ylabel(f'平均超额（窗口 {ANNUAL_WINDOW} 日）')
            ax.set_title(f"{r['name']} 年度分布（事件数与平均超额）")
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            ax.legend(h1 + h2, l1 + l2, fontsize=8)
            r['annual_img'] = _fig_to_b64(fig)
        else:
            r['annual_img'] = None

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH.parent)))
    template = env.get_template(TEMPLATE_PATH.name)
    html = template.render(
        start=start, end=end, windows=WINDOWS, annual_window=ANNUAL_WINDOW,
        stock_count=stock_count, generated_at=pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
        results=results)
    out = config.report_dir / EVENT_REPORT_NAME
    out.write_text(html, encoding='utf-8')
    I(f'事件研究报告生成：{out}')
    return out


def run_event(start: str | None = None, end: str | None = None) -> Path | None:
    """事件研究入口：初始化 + 价格矩阵 + 统计 + 渲染（独立命令/调试用）。"""
    import time
    from datetime import datetime, timedelta
    t0 = time.time()
    config = cfg_mod.init_hikyuu()
    cfg_mod.ensure_dirs(config)
    start = start or cfg_mod.DEFAULT_START
    end = end or cfg_mod.DEFAULT_END
    cfg = StrategyConfig(start=start, end=end)

    P('====== 事件研究：事件后超额收益统计 ======')
    stks = build_universe(cfg, end)
    I(f'股票池：{len(stks)} 只')
    end_plus1 = datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
    query = hku.Query(hku.Datetime(int(start[:4]), int(start[5:7]), int(start[8:10])),
                      hku.Datetime(end_plus1.year, end_plus1.month, end_plus1.day),
                      hku.Query.DAY, recover_type=hku.Query.FORWARD)
    open_df = build_price_matrix(stks, query, 'open')
    close_df = build_price_matrix(stks, query, 'close')
    I(f'价格矩阵：{close_df.shape[1]} 只 × {close_df.shape[0]} 日')

    results = study_events(stks, query, open_df, close_df)
    if not results:
        W('无 bool 型因子或事件样本为空，未生成报告')
        return None
    out = render_event_report(results, config, len(stks), start, end)
    I(f'事件研究完成（耗时 {time.time() - t0:.1f}s）')
    return out
