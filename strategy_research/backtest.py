# -*- coding: utf-8 -*-
"""统一回测执行器：单标的择时与截面组合两种模式（单标的 = 股票池 1 个标的的特例）。

- 策略由 strategies/ 组装（hikyuu Portfolio 组件：SE/AF/PF，内部走 TradeManager）
- 股票池过滤、执行、结果提取、落盘、实验注册表由本模块统一负责
- 产物目录：reports/<YYYYMMDD>_<slug>_<参数标签>_<run_id前6位>/（平铺可读）
- 实验注册表：strategy_research/data/experiments.db（runs 表：参数快照+commit+指标摘要）
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime as _dt, timedelta
from pathlib import Path

import hikyuu as hku

from difoss_stock_util import E, I, P, W

from . import config as cfg_mod
from . import factors
from .check import run_check
from .report import calc_max_drawdown, calc_sharpe
from .strategies import StrategyConfig, build_strategy

# 报告区块 1 的 T+1 制度声明
TPLUS1_DISCLAIMER = (
    'T+1 制度说明：本回测的买入/卖出信号均由 System 默认 buy_delay/sell_delay 推迟到'
    '下一交易日开盘执行，因此卖出日与买入日之间必然间隔 ≥1 个交易日——T+1 制度在'
    '日线次日开盘执行模型下自动满足（第一闭环实测 30 对交易最短持有恰为 1 个交易日、'
    '0 违规）。注意：系统无显式 T+1 组件，若未来使用分钟级数据或盘中信号，需另行实现'
    '（hikyuu 官方思路：自定义 MM 卖出数量控制，见 release.md）。'
    '一字板延迟与停牌自然跳过按 System 默认处理。'
)

RESULT_JSON = cfg_mod.RESULT_JSON
FUNDS_PNG = cfg_mod.FUNDS_PNG
DRAWDOWN_PNG = cfg_mod.DRAWDOWN_PNG

# 注册表库（data 目录，gitignore）
EXPERIMENTS_DB = cfg_mod.PKG_DIR / 'data' / 'experiments.db'


@dataclass
class BacktestResult:
    """回测结果（可 JSON 序列化，供 report 命令独立渲染）。"""
    meta: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)          # Performance 53 项 name -> value
    funds_curve: list = field(default_factory=list)    # [{'date': str, 'value': float}]
    drawdown_series: list = field(default_factory=list)  # [{'date': str, 'value': float}] 百分点
    trades: list = field(default_factory=list)         # [{'datetime': str, ...}] 成交明细
    rebalances: list = field(default_factory=list)     # [{'date', 'stocks', 'weights'}] 调仓明细（组合模式）
    sharpe: float = 0.0                                # 自算年化夏普（report.calc_sharpe）
    max_drawdown_mdd: float = 0.0                      # MDD 指标值（百分点）
    max_drawdown_self: float = 0.0                     # 自实现算法值（report.calc_max_drawdown）
    max_drawdown_consistent: bool = False              # 两独立实现一致才通过


def _fmt_num(v) -> float:
    """numpy/hikyuu 数值转 float（JSON 序列化安全）。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _git_commit() -> str:
    """当前仓库 HEAD commit（复现性记录）。失败返回空串。"""
    try:
        out = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(cfg_mod.REPO_DIR),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()[:12] if out.returncode == 0 else ''
    except Exception:
        return ''


def _tq_ctx():
    """tdxquant tqcenter 上下文（sys.path 注入 + initialize）。"""
    import sys
    for p in [r'D:\new_tdx_tet\PYPlugins\user', r'D:\new_tdx_tet\PYPlugins']:
        if p not in sys.path:
            sys.path.insert(0, p)
    from tqcenter import tq
    return tq


def _st_names() -> dict:
    """tqcenter 取沪深A股名称（用于 ST 剔除）。需 tdxw 运行（check 已保证）。"""
    tq = _tq_ctx()
    try:
        tq.initialize(__file__)
        lst = tq.get_stock_list('50', list_type=1)   # 50=沪深A股
        names = {x['Code'][:6].lower(): x['Name'] for x in lst} if lst else {}
        return names
    finally:
        try:
            tq.close()
        except Exception:
            pass


def build_universe(cfg: StrategyConfig, end: str) -> list[hku.Stock]:
    """全市场股票池 + 过滤（Q18 定稿）：剔除 ST、上市不满 N 日、近 N 日零成交。"""
    names = _st_names() if cfg.exclude_st else {}
    end_dt = _dt.strptime(end, '%Y-%m-%d')
    min_active = end_dt - timedelta(days=cfg.min_active_days)
    stks = []
    for stk in hku.sm.get_stock_list():
        if stk.market not in ('SH', 'SZ'):
            continue
        if not stk.valid or stk.type != 1:      # type=1 A股
            continue
        # 代码前缀白名单：type 判定不可靠（板块指数 881 等也会判为 type 1）
        code = stk.code
        if stk.market == 'SH' and not (code.startswith('60') or code.startswith('68')):
            continue
        if stk.market == 'SZ' and not (code.startswith('00') or code.startswith('30')):
            continue
        if cfg.exclude_st and 'ST' in names.get(stk.code.lower(), ''):
            continue
        # 上市不满 min_listed_days 个自然日：起点晚于回测起点 + 阈值
        cutoff = _dt.strptime(cfg.start, '%Y-%m-%d') + timedelta(days=cfg.min_listed_days)
        if stk.start_datetime > hku.Datetime(cutoff.year, cutoff.month, cutoff.day):
            continue
        if stk.last_datetime < hku.Datetime(min_active.year, min_active.month, min_active.day):
            continue  # 近 min_active_days 无新 K 线（长期停牌近似）
        stks.append(stk)
    return stks


def _extract_stats(tm: hku.TradeManager, query: hku.Query) -> dict:
    """Performance 53 项 → dict。"""
    ref_k = hku.sm['sh000001'].get_kdata(query)
    per = tm.get_performance(ref_k[-1].datetime, 'DAY')
    return {name: _fmt_num(v) for name, v in zip(per.names(), per.values())}


def _extract_trades(tm: hku.TradeManager) -> list[dict]:
    """成交明细 → 可序列化 dict 列表（剔除 INIT 初始记录）。"""
    out = []
    for t in tm.get_trade_list():
        business = str(t.business)
        if 'INIT' in business:
            continue
        biz_cn = '买入' if 'BUY' in business else ('卖出' if 'SELL' in business else business)
        out.append({
            'datetime': str(t.datetime),
            'stock': t.stock.market_code,
            'business': biz_cn,
            'plan_price': _fmt_num(t.plan_price),
            'real_price': _fmt_num(t.real_price),
            'number': _fmt_num(t.number),
            'cost_total': _fmt_num(t.cost.total),
            'cost_commission': _fmt_num(t.cost.commission),
            'cost_stamptax': _fmt_num(t.cost.stamptax),
            'cost_transferfee': _fmt_num(t.cost.transferfee),
            'cash': _fmt_num(t.cash),
        })
    return out


def _extract_rebalances(built, query: hku.Query) -> list[dict]:
    """调仓明细（组合模式）：每调仓日的入选标的与权重。"""
    out = []
    for d in built.pf.get_adjust_dates():
        sel = built.se.get_selected(d)
        stocks, weights = [], []
        for sw in sel:
            stocks.append(sw.sys.get_stock().market_code)
            weights.append(_fmt_num(sw.weight))
        out.append({'date': str(d.date()), 'stocks': stocks, 'weights': weights})
    return out


def _funds_and_drawdown(tm: hku.TradeManager, query: hku.Query) -> tuple[list, list, float]:
    """资金曲线（sh000001 交易日历对齐）+ MDD 回撤序列 + MDD 最大回撤（百分点）。"""
    dates = hku.sm['sh000001'].get_kdata(query).get_datetime_list()
    funds = tm.get_funds_curve(dates, 'DAY')
    curve = [{'date': str(d), 'value': _fmt_num(v)} for d, v in zip(dates, funds)]
    mdd_ind = hku.MDD(hku.VALUE([x['value'] for x in curve]))
    series = [{'date': str(d), 'value': _fmt_num(v)} for d, v in zip(dates, mdd_ind)]
    return curve, series, series[-1]['value'] if series else 0.0


def _run_dir_name(cfg: StrategyConfig, mode: str, run_id: int) -> str:
    """产物目录名：<YYYYMMDD>_<slug>_<参数标签>_<runid6>（人工可读）。"""
    date = _dt.now().strftime('%Y%m%d')
    tag = f't{cfg.topn}' if mode == 'portfolio' else 'std'
    return f'{date}_{cfg.strategy}_{tag}_{run_id:06d}'


def _registry_insert(cfg: StrategyConfig, mode: str, result: BacktestResult,
                     out_dir: Path) -> int:
    """实验注册表写入，返回 run_id。"""
    EXPERIMENTS_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(EXPERIMENTS_DB))
    try:
        con.execute(
            'CREATE TABLE IF NOT EXISTS runs ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, strategy TEXT, mode TEXT,'
            'params TEXT, git_commit TEXT, summary TEXT, out_dir TEXT)')
        params = json.dumps(cfg.__dict__, ensure_ascii=False)
        summary = json.dumps({
            'sharpe': result.sharpe,
            'max_drawdown': result.max_drawdown_mdd,
            'trades': len(result.trades),
            'final_assets': result.stats.get('当前总资产'),
            'annual_return': result.stats.get('帐户平均年收益率%'),
        }, ensure_ascii=False)
        cur = con.execute(
            'INSERT INTO runs(ts, strategy, mode, params, git_commit, summary, out_dir)'
            ' VALUES (?,?,?,?,?,?,?)',
            (_dt.now().strftime('%Y-%m-%d %H:%M:%S'), cfg.strategy, mode, params,
             _git_commit(), summary, str(out_dir)))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def run_backtest(cfg: StrategyConfig | None = None, config: cfg_mod.HikyuuConfig | None = None,
                 skip_check: bool = False, draw_charts: bool = True,
                 report: bool = False) -> tuple[BacktestResult, Path]:
    """统一回测入口：股票池 → 策略组装 → pf.run → 提取 → 落盘 + 注册表。

    :return: (结果, 产物目录)
    """
    t0 = time.time()
    config = cfg_mod.init_hikyuu(config)
    cfg_mod.ensure_dirs(config)
    if cfg is None:
        cfg = StrategyConfig()

    P(f'====== 回测：{cfg.strategy} ======')
    I(f'参数：topn={cfg.topn} mf={cfg.mf} norm={cfg.norm} '
      f'调仓={cfg.adjust_mode}:{cfg.adjust_cycle} 区间 {cfg.start} ~ {cfg.end} '
      f'资金 {cfg.init_cash:,.0f}')

    if not skip_check:
        if not run_check(print_table=True):
            raise RuntimeError('数据就绪校验未通过，拒绝回测')

    # 股票池（系统模式单标的：忽略过滤，直接 [sh000001]）
    if cfg.strategy == 'ma-cross':
        stks = [hku.sm['sh000001']]
    else:
        stks = build_universe(cfg, cfg.end)
    I(f'股票池：{len(stks)} 只')

    built = build_strategy(cfg, stks)
    I(f'策略组装完成：{built.meta.get("name")}')

    built.pf.run(built.query)
    I(f'回测完成，耗时 {time.time() - t0:.2f}s')

    # ---- 结果提取 ----
    tm = built.pf.tm
    stats = _extract_stats(tm, built.query)
    trades = _extract_trades(tm)
    curve, drawdown_series, max_drawdown_mdd = _funds_and_drawdown(tm, built.query)
    daily_values = [x['value'] for x in curve]
    daily_returns = [b / a - 1 for a, b in zip(daily_values[:-1], daily_values[1:])]
    sharpe = calc_sharpe(daily_returns)
    # 交叉验证：MDD 指标 × 自实现算法。
    # get_max_pull_back 在 2.8.1 恒返回 0.0（实测指数+个股、多日期均如此），不可用
    max_drawdown_self = calc_max_drawdown(daily_values)
    mdd_consistent = abs(max_drawdown_mdd - max_drawdown_self) < 0.01

    I(f'交易 {len(trades)} 条 | 年化夏普 {sharpe:.4f} | '
      f'最大回撤 MDD指标={max_drawdown_mdd:.2f}% 自实现={max_drawdown_self:.2f}% '
      f'交叉验证{"一致" if mdd_consistent else "不一致！"}')

    result = BacktestResult(
        meta={
            'mode': built.mode,
            'strategy': cfg.strategy,
            'strategy_name': built.meta.get('name', ''),
            'strategy_desc': built.meta.get('desc', ''),
            'stock_count': len(stks),
            'start': cfg.start,
            'end': cfg.end,
            'recover_type': 'FORWARD（前复权）',
            'init_cash': cfg.init_cash,
            'cost_func': 'TC_FixedA2017',
            'slippage': 0.001,
            'adjust_mode': cfg.adjust_mode,
            'adjust_cycle': cfg.adjust_cycle,
            't_plus_1_disclaimer': TPLUS1_DISCLAIMER,
            'generated_at': _dt.now().strftime('%Y-%m-%d %H:%M:%S'),
            'git_commit': _git_commit(),
            'hikyuu_version': hku.__version__ if hasattr(hku, '__version__') else '',
        },
        stats=stats,
        funds_curve=curve,
        drawdown_series=drawdown_series,
        trades=trades,
        rebalances=_extract_rebalances(built, built.query) if built.mode == 'portfolio' else [],
        sharpe=sharpe,
        max_drawdown_mdd=max_drawdown_mdd,
        max_drawdown_self=max_drawdown_self,
        max_drawdown_consistent=mdd_consistent,
    )

    # ---- 落盘 + 注册表 ----
    run_id = _registry_insert(cfg, built.mode, result, Path(''))
    out_dir = config.report_dir / _run_dir_name(cfg, built.mode, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 目录名含 run_id（插入后才确定），注册表落库后回填真实路径
    con = sqlite3.connect(str(EXPERIMENTS_DB))
    con.execute('UPDATE runs SET out_dir=? WHERE id=?', (str(out_dir), run_id))
    con.commit()
    con.close()
    with open(out_dir / RESULT_JSON, 'w', encoding='utf-8') as f:
        json.dump(result.__dict__, f, ensure_ascii=False, indent=2)
    I(f'结果落盘：{out_dir}')

    if draw_charts:
        draw_funds_chart(built.pf.tm, built.query, out_dir)
        draw_drawdown_chart(drawdown_series, out_dir)
    if report:
        from .report import render_html
        render_html(result, output=out_dir / 'report.html', result_dir=out_dir)
    return result, out_dir


def draw_funds_chart(tm: hku.TradeManager, query: hku.Query, result_dir: Path) -> Path:
    """资金曲线图：hikyuu tm.performance（收益曲线 + 基准 + 统计文本），savefig → PNG。"""
    import matplotlib.pyplot as plt

    # TradeManager.performance 由 hikyuu.draw.drawplot 在 import hikyuu 时绑定
    tm.performance(query, ref_stk=hku.sm['sh000001'])
    path = result_dir / FUNDS_PNG
    plt.gcf().savefig(path, dpi=150, bbox_inches='tight')
    plt.close('all')
    I(f'资金曲线图落盘：{path}')
    return path


def draw_drawdown_chart(drawdown_series: list, result_dir: Path) -> Path:
    """回撤曲线图：MDD 序列独立小图（tm_performance 未含回撤子图，故补此独立图）。

    实现要点（实测修正）：x 轴必须用 datetime 对象而非字符串——字符串会被
    matplotlib 当分类轴，fill_between 多边形闭合错乱产生大片黑块（渲染 bug）；
    hikyuu MDD 指标返回正数，绘图时取负让回撤曲线挂在 0 线下方（惯例）。
    """
    from datetime import datetime as _dt
    import matplotlib
    import matplotlib.pyplot as plt

    # 显式配置中文字体（不依赖 hikyuu import 的全局 rcParams 副作用）
    matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
    matplotlib.rcParams['axes.unicode_minus'] = False

    dates = [_dt.strptime(x['date'][:10], '%Y-%m-%d') for x in drawdown_series]
    values = [-x['value'] for x in drawdown_series]  # 正值（MDD 输出）取负，向下绘制
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.fill_between(dates, values, 0, color='#c0504d', alpha=0.5)
    ax.plot(dates, values, color='#c0504d', linewidth=0.8)
    ax.set_title('回撤曲线（%）：MDD 指标对资金曲线计算')
    ax.set_ylabel('回撤（%）')
    ax.set_ylim(min(values) * 1.05, 1)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    path = result_dir / DRAWDOWN_PNG
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close('all')
    I(f'回撤曲线图落盘：{path}')
    return path


def load_result(result_dir: Path) -> BacktestResult:
    """从 JSON 读取回测结果（report 命令独立渲染入口）。"""
    path = result_dir / RESULT_JSON
    if not path.exists():
        raise FileNotFoundError(f'回测结果不存在: {path}（请先运行 backtest）')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return BacktestResult(**data)
