# -*- coding: utf-8 -*-
"""报告层：自算指标 + jinja2 单文件 html。

- 自算年化夏普：get_funds_curve 日收益率 mean/std × √252，无风险利率 0（纯函数 calc_sharpe，可单测）
- 最大回撤：backtest 阶段 MDD 指标与自实现算法交叉验证（两值一致才通过），此处仅呈现
- html：jinja2 单文件自包含（图表 base64 内嵌），6 区块布局，固定名 first_loop_report.html
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from difoss_stock_util import E, I

from . import config as cfg_mod

if TYPE_CHECKING:
    from .backtest import BacktestResult

TEMPLATE_PATH = Path(__file__).resolve().parent / 'report' / 'template.html'
DEFAULT_REPORT_NAME = cfg_mod.DEFAULT_REPORT_NAME

# 53 项中用于指标卡 ×6 的 key（key 名以 2.8.1 Performance.names() 实测为准）
KEY_ANNUAL_RETURN = '帐户平均年收益率%'
KEY_WIN_RATE = '赢利交易比例%'
KEY_PROFIT_LOSS_RATIO = '平均赢利/平均亏损比例'
KEY_TRADE_COUNT = '已平仓交易总数'


def calc_sharpe(daily_returns, periods_per_year: int = 252) -> float:
    """自算年化夏普：日收益率 mean/std × √周期数，无风险利率 0。

    空仓段日收益为 0（资金不变），计入序列；std 为样本标准差（ddof=1）。
    """
    arr = np.asarray(list(daily_returns), dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 2:
        return 0.0
    std = arr.std(ddof=1)
    # numpy std（Welford 算法）对恒定序列有 ~1e-19 浮点残差，须 epsilon 保护而非 == 0
    if std < 1e-12 or np.isnan(std):
        return 0.0
    return float(arr.mean() / std * np.sqrt(periods_per_year))


def calc_max_drawdown(equity_values) -> float:
    """自实现最大回撤（百分点，正数）：max over t of (peak_before_t - value_t) / peak_before_t × 100。

    与 hikyuu MDD 指标交叉验证用（get_max_pull_back 在 2.8.1 恒返回 0.0
    不可用——实测指数+个股、多日期均如此，交叉验证改用本函数与 MDD 指标互证）。
    空仓段资金不变，回撤为 0，不影响峰值跟踪。
    """
    arr = np.asarray(list(equity_values), dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return 0.0
    peak = arr[0]
    max_dd = 0.0
    for v in arr:
        if v > peak:
            peak = v
        elif peak > 0:
            dd = (peak - v) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return float(max_dd)


def _png_to_base64(png_path: Path) -> str:
    if not png_path.exists():
        E(f'图表缺失: {png_path}')
        return ''
    with open(png_path, 'rb') as f:
        return 'data:image/png;base64,' + base64.b64encode(f.read()).decode('ascii')


def _pick_stat(stats: dict, key: str, default=0.0):
    """从 53 项取指标，key 缺失时告警并回退默认值。"""
    if key in stats:
        return stats[key]
    E(f'53 项中缺少指标 {key}（hikyuu 版本差异？），回退默认 {default}')
    return default


def build_view(result: BacktestResult, result_dir: Path) -> dict:
    """组装模板上下文（6 区块数据）。"""
    meta = result.meta
    # 指标卡 ×6：年化收益/夏普/最大回撤/胜率/盈亏比/交易次数
    cards = [
        {'label': '年化收益', 'value': f"{_pick_stat(result.stats, KEY_ANNUAL_RETURN):.2f}%",
         'unit': '%'},
        {'label': '年化夏普', 'value': f'{result.sharpe:.3f}', 'unit': ''},
        {'label': '最大回撤', 'value': f'{result.max_drawdown_mdd:.2f}', 'unit': '%',
         'note': '通过' if result.max_drawdown_consistent else '交叉验证不一致！'},
        {'label': '胜率', 'value': f"{_pick_stat(result.stats, KEY_WIN_RATE):.2f}", 'unit': '%'},
        {'label': '盈亏比', 'value': f"{_pick_stat(result.stats, KEY_PROFIT_LOSS_RATIO):.2f}", 'unit': ''},
        {'label': '交易次数', 'value': f"{int(_pick_stat(result.stats, KEY_TRADE_COUNT))}", 'unit': '次'},
    ]
    # 53 项统计表（保持 hikyuu 原始顺序）
    stat_rows = [{'name': k, 'value': v} for k, v in result.stats.items()]
    return {
        'meta': meta,
        'cards': cards,
        'funds_img': _png_to_base64(result_dir / cfg_mod.FUNDS_PNG),
        'drawdown_img': _png_to_base64(result_dir / cfg_mod.DRAWDOWN_PNG),
        'stat_rows': stat_rows,
        'trades': result.trades,
        'max_drawdown_consistent': result.max_drawdown_consistent,
        'max_drawdown_mdd': result.max_drawdown_mdd,
        'max_drawdown_self': result.max_drawdown_self,
    }


def render_html(result: BacktestResult, output: Path | None = None,
                result_dir: Path | None = None) -> Path:
    """渲染单文件 html 报告（图表 base64 内嵌，双击离线即看）。

    :param output: 输出路径；默认 config 的 report_dir/first_loop_report.html
    """
    from jinja2 import Environment, FileSystemLoader

    if result_dir is None:
        result_dir = cfg_mod.load_config().report_dir
    if output is None:
        output = result_dir / DEFAULT_REPORT_NAME
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH.parent)))
    template = env.get_template(TEMPLATE_PATH.name)
    html = template.render(**build_view(result, result_dir))
    output.write_text(html, encoding='utf-8')
    I(f'报告生成：{output}')
    return output


def run_report(result_dir: Path | None = None, output: Path | None = None) -> Path:
    """report 子命令：从落盘结果出 html 报告。"""
    from .backtest import load_result  # 延迟导入避免 backtest↔report 循环

    if result_dir is None:
        result_dir = cfg_mod.load_config().report_dir
    result = load_result(result_dir)
    return render_html(result, output=output, result_dir=result_dir)
