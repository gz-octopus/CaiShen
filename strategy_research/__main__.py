# -*- coding: utf-8 -*-
"""strategy_research CLI 入口：python -m strategy_research，四子命令。

check      数据就绪校验（tdxw 进程 + 权息非空抽样比对）
backtest   跑回测，结果落盘（JSON + 图表 PNG）
report     从回测结果出 html 报告
first-loop check → backtest → report 一键完整链路
"""
from __future__ import annotations

from pathlib import Path

import click

from difoss_stock_util import E

from . import __version__, config as cfg_mod

CONTEXT_SETTINGS = {'help_option_names': ['-?', '--help', '-h']}


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, prog_name='strategy_research')
def cli():
    """CaiShen 策略研究回测系统（hikyuu 2.8.1）：数据 → 因子 → 策略 → 回测 → 报告。"""


@cli.command(context_settings=CONTEXT_SETTINGS)
def check():
    """数据就绪校验：tdxw 进程 + 权息非空抽样比对，任一不过拒绝回测。"""
    try:
        from .check import run_check
        ok = run_check()
    except Exception:
        E('校验执行异常：')
        raise
    raise SystemExit(0 if ok else 1)


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option('--start', default=cfg_mod.DEFAULT_START, show_default=True, help='回测起始日期')
@click.option('--end', default=cfg_mod.DEFAULT_END, show_default=True, help='回测结束日期')
@click.option('--stock', '-s', default=cfg_mod.DEFAULT_STOCK, show_default=True, help='策略标的')
@click.option('--init-cash', type=float, default=None, help='初始资金（默认取 config.yaml，未配置 100 万）')
@click.option('--skip-check', is_flag=True, help='跳过数据就绪校验（不推荐，校验通过才允许回测）')
def backtest(start, end, stock, init_cash, skip_check):
    """跑回测：sh000001 MA(10)/MA(30) 金叉择时，结果落盘（JSON + 图表 PNG）。"""
    from .backtest import run_backtest
    try:
        run_backtest(start=start, end=end, stock_code=stock,
                     init_cash=init_cash, skip_check=skip_check)
    except Exception:
        E('回测执行异常：')
        raise


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option('--output', '-o', type=click.Path(path_type=Path), default=None,
              help='报告输出路径（默认 report_dir/first_loop_report.html）')
def report(output):
    """从落盘回测结果出 html 报告（单文件自包含，图表 base64 内嵌）。"""
    from .report import run_report
    try:
        path = run_report(output=output)
        click.echo(f'报告已生成：{path}')
    except Exception:
        E('报告生成异常：')
        raise


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option('--start', default=cfg_mod.DEFAULT_START, show_default=True, help='回测起始日期')
@click.option('--end', default=cfg_mod.DEFAULT_END, show_default=True, help='回测结束日期')
@click.option('--output', '-o', type=click.Path(path_type=Path), default=None,
              help='报告输出路径（默认 report_dir/first_loop_report.html）')
@click.option('--skip-check', is_flag=True, help='跳过数据就绪校验（不推荐，校验通过才允许回测）')
def first_loop(start, end, output, skip_check):
    """一键完整链路：数据就绪校验 → 回测 → html 报告。"""
    from .backtest import run_backtest
    from .report import render_html
    try:
        result = run_backtest(start=start, end=end, skip_check=skip_check)
        path = render_html(result, output=output)
        click.echo(f'第一闭环完成，报告已生成：{path}')
    except Exception:
        E('第一闭环执行异常：')
        raise


if __name__ == '__main__':
    cli()
