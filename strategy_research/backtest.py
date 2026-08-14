# -*- coding: utf-8 -*-
"""回测执行：System + TradeManager 事件驱动。

- 单标的 sh000001 MA(10)/MA(30) 金叉择时，区间 2020-01-02 ~ 2026-08-13
- 复权 FORWARD（前复权）；信号次日开盘价成交（System 原生 buy_delay/sell_delay）
- 结果落盘：backtest_result.json + 图表 PNG（report 命令独立渲染）
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime as _dt
from pathlib import Path

import hikyuu as hku

from difoss_stock_util import E, I, P

from . import config as cfg_mod
from . import strategy as st_mod
from .check import run_check
from .report import calc_max_drawdown, calc_sharpe

# 报告区块 1 的 T+1 制度声明
TPLUS1_DISCLAIMER = (
    'T+1 制度说明：本回测的买入/卖出信号均由 System 默认 buy_delay/sell_delay 推迟到'
    '下一交易日开盘执行，且金叉与死叉不可能出现在同一根 K 线，因此卖出日与买入日之间'
    '必然间隔 ≥1 个交易日——T+1 制度在日线次日开盘执行模型下自动满足'
    '（实测 30 对交易最短持有恰为 1 个交易日、0 违规）。'
    '注意：系统无显式 T+1 组件，若未来使用分钟级数据或盘中信号，需另行实现'
    '（hikyuu 官方思路：自定义 MM 卖出数量控制，见 release.md）。'
    '一字板延迟与停牌自然跳过按 System 默认处理。'
)

RESULT_JSON = cfg_mod.RESULT_JSON
FUNDS_PNG = cfg_mod.FUNDS_PNG
DRAWDOWN_PNG = cfg_mod.DRAWDOWN_PNG


@dataclass
class BacktestResult:
    """回测结果（可 JSON 序列化，供 report 命令独立渲染）。"""
    meta: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)          # Performance 53 项 name -> value
    funds_curve: list = field(default_factory=list)    # [{'date': str, 'value': float}]
    drawdown_series: list = field(default_factory=list)  # [{'date': str, 'value': float}] 百分点
    trades: list = field(default_factory=list)         # [{'datetime': str, ...}]
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


def build_trade_manager(start: str, init_cash: float, cost_func: str, name: str) -> hku.TradeManager:
    """crtTM(date=, init_cash=, cost_func=, name=) 是 2.8.1 唯一正确构造方式（旧 4 参构造已废）。"""
    cost_cls = getattr(hku, cost_func, None)
    if cost_cls is None:
        raise ValueError(f'未知交易成本函数: {cost_func}')
    return hku.crtTM(date=hku.Datetime(int(start[:4]), int(start[5:7]), int(start[8:10])),
                     init_cash=init_cash, cost_func=cost_cls(), name=name)


def _extract_stats(per: hku.Performance) -> dict:
    """Performance 53 项 → dict（names/values 顺序一一对应）。"""
    return {name: _fmt_num(v) for name, v in zip(per.names(), per.values())}


def _extract_trades(tm: hku.TradeManager) -> list[dict]:
    """交易明细 → 可序列化 dict 列表。

    剔除 BUSINESS.INIT（账户初始记录，非交易）；cost 是 CostRecord 对象，
    拆出 total/commission/stamptax/transferfee；business 转中文。
    """
    trades = tm.get_trade_list()
    out = []
    for t in trades:
        business = str(t.business)
        if 'INIT' in business:
            continue
        if 'BUY' in business:
            biz_cn = '买入'
        elif 'SELL' in business:
            biz_cn = '卖出'
        else:
            biz_cn = business
        out.append({
            'datetime': str(t.datetime),
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


def _calc_funds_curve_and_drawdown(tm: hku.TradeManager, dates) -> tuple[list, list, float]:
    """资金曲线（总资产日序列）+ MDD 回撤序列 + MDD 指标最大回撤（百分点）。

    MDD 指标对资金曲线序列计算（正值，百分点）；交叉验证用自实现算法（见 run_backtest）。
    """
    funds = tm.get_funds_curve(dates, 'DAY')
    curve = [{'date': str(d), 'value': _fmt_num(v)} for d, v in zip(dates, funds)]

    # MDD 指标：序列每个点为截至该点的最大回撤（%），末点 = 全期最大回撤
    mdd_ind = hku.MDD(hku.VALUE([x['value'] for x in curve]))
    series = [{'date': str(d), 'value': _fmt_num(v)} for d, v in zip(dates, mdd_ind)]
    max_drawdown_mdd = series[-1]['value'] if series else 0.0
    return curve, series, max_drawdown_mdd


def run_backtest(start: str | None = None, end: str | None = None,
                 stock_code: str | None = None,
                 init_cash: float | None = None,
                 cost_func: str | None = None, slippage: float | None = None,
                 fast_n: int | None = None, slow_n: int | None = None,
                 skip_check: bool = False, config: cfg_mod.HikyuuConfig | None = None,
                 result_dir: Path | None = None,
                 draw_charts: bool = True) -> BacktestResult:
    """执行回测并落盘结果（JSON + PNG）。

    :param skip_check: 跳过数据就绪校验（默认 False，任一不过拒绝回测）
    """
    t0 = time.time()
    config = cfg_mod.init_hikyuu(config)
    cfg_mod.ensure_dirs(config)
    if result_dir is None:
        result_dir = config.report_dir

    start = start or cfg_mod.DEFAULT_START
    end = end or cfg_mod.DEFAULT_END
    stock_code = stock_code or cfg_mod.DEFAULT_STOCK
    init_cash = cfg_mod.DEFAULT_INIT_CASH if init_cash is None else init_cash
    cost_func = cost_func or config.cost_func
    slippage = config.slippage if slippage is None else slippage
    fast_n = cfg_mod.DEFAULT_FAST_N if fast_n is None else fast_n
    slow_n = cfg_mod.DEFAULT_SLOW_N if slow_n is None else slow_n

    P(f'====== 回测：{st_mod.STRATEGY_NAME} ======')
    I(f'标的 {stock_code} | 区间 {start} ~ {end} | 复权 FORWARD | '
      f'初始资金 {init_cash:,.0f} | 成本 {cost_func} | 滑点 {slippage} | MA({fast_n})/MA({slow_n})')

    if not skip_check:
        if not run_check(print_table=True):
            raise RuntimeError('数据就绪校验未通过，拒绝回测')

    stock = hku.sm[stock_code]
    # DATE 查询 end 边界为 exclusive（2.8.1 实测：end=08-13 得最后根 08-12），
    # 内部 +1 天保证包含定稿区间末端交易日；end 为非交易日时 +1 天无副作用
    end_plus1 = _dt.strptime(end, '%Y-%m-%d')
    from datetime import timedelta
    end_plus1 = (end_plus1 + timedelta(days=1)).strftime('%Y-%m-%d')
    query = hku.Query(hku.Datetime(int(start[:4]), int(start[5:7]), int(start[8:10])),
                      hku.Datetime(int(end_plus1[:4]), int(end_plus1[5:7]), int(end_plus1[8:10])),
                      hku.Query.DAY, recover_type=hku.Query.FORWARD)
    kdata = stock.get_kdata(query)
    if len(kdata) == 0:
        raise RuntimeError(f'{stock_code} 区间 {start}~{end} K 线为空（检查 preload day=True 与数据目录）')
    I(f'K 线就绪：{len(kdata)} 根，{kdata[0].datetime.date()} ~ {kdata[-1].datetime.date()}')

    tm = build_trade_manager(start, init_cash, cost_func, name=st_mod.STRATEGY_NAME)
    sys_ = st_mod.create_system(tm, fast_n=fast_n, slow_n=slow_n, slippage=slippage)
    I(f'System 构建完成：{sys_.name}')

    sys_.run(stock, query)  # 2.8.1 签名：run(stock, query)
    I(f'回测完成，耗时 {time.time() - t0:.2f}s')

    # ---- 结果提取 ----
    per = tm.get_performance(kdata[-1].datetime, 'DAY', ext=True)
    stats = _extract_stats(per)
    trades = _extract_trades(tm)
    dates = kdata.get_datetime_list()
    curve, drawdown_series, max_drawdown_mdd = _calc_funds_curve_and_drawdown(tm, dates)
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
            'strategy_name': st_mod.STRATEGY_NAME,
            'strategy_desc': st_mod.STRATEGY_DESC,
            'stock_code': stock_code,
            'stock_name': stock.name,
            'start': start,
            'end': end,
            'recover_type': 'FORWARD（前复权）',
            'init_cash': init_cash,
            'cost_func': cost_func,
            'slippage': slippage,
            'fast_n': fast_n,
            'slow_n': slow_n,
            't_plus_1_disclaimer': TPLUS1_DISCLAIMER,
            'generated_at': _dt.now().strftime('%Y-%m-%d %H:%M:%S'),
            'hikyuu_version': hku.__version__ if hasattr(hku, '__version__') else '',
        },
        stats=stats,
        funds_curve=curve,
        drawdown_series=drawdown_series,
        trades=trades,
        sharpe=sharpe,
        max_drawdown_mdd=max_drawdown_mdd,
        max_drawdown_self=max_drawdown_self,
        max_drawdown_consistent=mdd_consistent,
    )

    # ---- 落盘 ----
    json_path = result_dir / RESULT_JSON
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result.__dict__, f, ensure_ascii=False, indent=2)
    I(f'结果落盘：{json_path}')

    if draw_charts:
        draw_funds_chart(tm, query, result_dir)
        draw_drawdown_chart(drawdown_series, result_dir)
    return result


def draw_funds_chart(tm: hku.TradeManager, query: hku.Query, result_dir: Path) -> Path:
    """资金曲线图：hikyuu tm.performance（收益曲线 + 基准 + 统计文本），savefig → PNG。"""
    import matplotlib.pyplot as plt

    # TradeManager.performance 由 hikyuu.draw.drawplot 在 import hikyuu 时绑定
    tm.performance(query, ref_stk=hku.sm[cfg_mod.DEFAULT_STOCK])
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
