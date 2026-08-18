# -*- coding: utf-8 -*-
"""strategy_research CLI 入口：python -m strategy_research，四子命令。

check      数据就绪校验：tdxw 进程 + 权息非空抽样比对
backtest   统一回测（--strategy 选策略；单标的 = 股票池 1 个标的的特例）
factor     因子评估：IC/ICIR + 分层回测，出 html 评估报告
report     从落盘回测结果出 html 报告

参数优先级：CLI 显式参数 > experiment config 文件 > 默认值。
experiment 文件示例见 strategy_research/experiments/*.yaml。
"""
from __future__ import annotations

from pathlib import Path

import click

from difoss_stock_util import E

from . import __version__, config as cfg_mod
from .run_event import ENTRIES
from .strategies import StrategyConfig

CONTEXT_SETTINGS = {'help_option_names': ['-?', '--help', '-h']}


def _load_experiment(path: Path | None) -> dict:
    """读取 experiment YAML（运行参数文件，进 git 可版本可 diff）。"""
    if path is None:
        return {}
    import yaml
    with open(path, encoding='utf-8') as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise click.BadParameter(f'experiment 文件格式异常: {path}')
    return raw


def _build_config(exp: dict, cli: dict) -> StrategyConfig:
    """合并参数：CLI 显式 > experiment 文件 > 默认值。"""
    params = {**exp, **{k: v for k, v in cli.items() if v is not None}}
    return StrategyConfig(**params)


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
@click.option('--config', '-c', 'exp_path', type=click.Path(path_type=Path), default=None,
              help='experiment 参数文件（YAML）')
@click.option('--strategy', '-s', default=None, help='策略 slug（factors/strategies 注册）')
@click.option('--topn', type=int, default=None, help='组合 TopN（默认 10）')
@click.option('--mf', type=click.Choice(['equal-weight', 'icir-weight']), default=None,
              help='因子合成方式')
@click.option('--norm', type=click.Choice(['zscore', 'quantile-uniform', 'minmax', 'nothing']),
              default=None, help='归一化方式')
@click.option('--adjust-mode', type=click.Choice(['month', 'query', 'day']), default=None,
              help='调仓模式（默认 month 月度）')
@click.option('--adjust-cycle', type=int, default=None, help='调仓周期（month 模式：每月第 N 日）')
@click.option('--start', default=None, help='回测起始日期')
@click.option('--end', default=None, help='回测结束日期')
@click.option('--init-cash', type=float, default=None, help='初始资金（默认 100 万）')
@click.option('--skip-check', is_flag=True, help='跳过数据就绪校验（不推荐，校验通过才允许回测）')
@click.option('--report', 'gen_report', is_flag=True, help='回测后自动出 html 报告')
def backtest(exp_path, strategy, topn, mf, norm, adjust_mode, adjust_cycle,
             start, end, init_cash, skip_check, gen_report):
    """统一回测：单标的择时与截面组合（单标的 = 股票池 1 个标的的特例）。"""
    from .backtest import run_backtest
    exp = _load_experiment(exp_path)
    cli_params = {'strategy': strategy, 'topn': topn, 'mf': mf, 'norm': norm,
                  'adjust_mode': adjust_mode, 'adjust_cycle': adjust_cycle,
                  'start': start, 'end': end, 'init_cash': init_cash}
    cfg = _build_config(exp, cli_params)
    try:
        result, out_dir = run_backtest(cfg, skip_check=skip_check, report=gen_report)
        click.echo(f'回测完成，产物目录：{out_dir}')
    except Exception:
        E('回测执行异常：')
        raise


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option('--factor', '-f', 'factor_name', default=None,
              help='只评估指定因子（不指定则评估全部）')
@click.option('--start', default=cfg_mod.DEFAULT_START, show_default=True, help='评估起始日期')
@click.option('--end', default=cfg_mod.DEFAULT_END, show_default=True, help='评估结束日期')
@click.option('--layers', type=int, default=10, show_default=True, help='分层回测层数')
@click.option('--entries', '-e', 'entries', multiple=True,
              type=click.Choice(ENTRIES), default=('d1_open',), show_default=True,
              help='事件研究入场变体（bool 因子用，可多选）：d1_open=D+1 开盘（基线）｜'
                   'd_close=D 收盘（尾盘，含 look-ahead 近似）｜d1_close=D+1 收盘｜'
                   'd1_dip=D+1 低吸（触及涨停 K 线实体中分价成交）')
def factor(factor_name, start, end, layers, entries):
    """因子评估：按因子类型自动分流（num：IC/ICIR + 分层；bool：事件研究）。"""
    from .run_factor import run_factor
    try:
        factor_path, event_path = run_factor(
            start=start, end=end, layers=layers, factor_name=factor_name, entries=entries)
        for p in (factor_path, event_path):
            if p:
                click.echo(f'因子评估完成：{p}')
    except Exception:
        E('因子评估异常：')
        raise


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.argument('result_dir', type=click.Path(path_type=Path))
@click.option('--output', '-o', type=click.Path(path_type=Path), default=None,
              help='报告输出路径（默认结果目录下 report.html）')
def report(result_dir, output):
    """从落盘回测结果出 html 报告（单文件自包含，图表 base64 内嵌）。"""
    from .report import run_report
    try:
        path = run_report(result_dir=result_dir, output=output)
        click.echo(f'报告已生成：{path}')
    except Exception:
        E('报告生成异常：')
        raise


if __name__ == '__main__':
    cli()
