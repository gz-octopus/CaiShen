#!python
# encoding: utf-8
# author: DifossChen
#
from pytdx.hq import TdxHq_API
from pytdx.exhq import TdxExHq_API
# from simple_pytdx.api import *
from pprint import pprint
import traceback

from difoss_stock_util.color_log_util import *
from difoss_stock_util.click_util import *
from difoss_stock_util import SecurityCode, SecurityType, MarketType, read_yaml_config
from difoss_stock_util.rich_util import *
from difoss_stock_util.util import print_locals
from rich.console import Console

from rich import print
import pandas as pd

import sys
import click
from typing import List, Dict, Optional
from pytdx.util.best_ip import select_best_ip, ping as pytdx_ping
from simple_pytdx.api import Api
from enum import IntEnum, StrEnum, Enum
import datetime

from cache_cmd import (
    STOCKS,
    stocks_collector, blocks_collector, df_collector,
    memory_cache, data_frame, blocks_2_stocks,
)

# ---------------------------------------------------------------------------------------------------
ALL_MARKET_LIST = ['SH', 'SZ']
ALL_SECURITY_TYPE_LIST = SecurityType.allows()
ALL_SECURITY_TYPE_CN_LIST = SecurityType.allows_cn()

PERIOD_2_CATEGORY = {
    '1m': Api.KLineCategory.K1, # 1分钟线
    '5m': Api.KLineCategory.K5, # 5分钟线
    '15m': Api.KLineCategory.K15, # 15分钟线
    '30m': Api.KLineCategory.K30, # 30分钟线
    '60m': Api.KLineCategory.K60, # 60分钟线
    '1d': Api.KLineCategory.KDay, # 日线
    '1q': Api.KLineCategory.KSeason, # 季度线
    '1y': Api.KLineCategory.KYear, # 年线
    '1w': Api.KLineCategory.KWeek, # 周线
    '1mon': Api.KLineCategory.KMonth, # 月线
}

PERIODS = list(PERIOD_2_CATEGORY.keys())

# 可使用 -ping 功能调用 select_best_ip() 获取最佳 IP:PORT
STOCK_IP = 'sztdx.gtjas.com'
FUTURE_IP = '112.74.214.43'

STOCK_PORT = 7709
FUTURE_PORT = 7727

CONSOLE = Console()
CFG = None
# ---------------------------------------------------------------------------------------------------
def get_market_enum(market_str: str) -> Enum | None:
    market_str = market_str.upper()
    if market_str == 'SZ':
        return Api.Market.SZ
    elif market_str == 'SH':
        return Api.Market.SH
    elif market_str == 'BJ':
        return Api.Market.BJ

    return None

def market_enum_to_str(market_enum: Enum) -> str:
    if market_enum == Api.Market.SZ:
        return 'SZ'
    elif market_enum == Api.Market.SH:
        return 'SH'
    elif market_enum == Api.Market.BJ:
        return 'BJ'
    return None


def security_code_to_tuple(security_code: str | SecurityCode) -> Optional[tuple]:
    """将股票代码转换为 (market_enum, code) 元组"""
    try:
        if isinstance(security_code, SecurityCode):
            code = security_code
        else:
            code = SecurityCode(security_code)
        market_enum = get_market_enum(code.market_code)
        if market_enum is None:
            E(f"无法识别市场: {code.market_code}，股票代码: {security_code}")
            return None
        return (market_enum.value, code.short_code)
    except Exception as e:
        E(f"无法解析股票代码: {security_code}, 错误: {e}")
        return None

# ---------------------------------------------------------------------------------------------------
@command_with_abbrev(abbrev='ip', context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--type', '-t', 'src_type', type=click.Choice(['stock', 'future']), default='stock', help='选择数据源类型')
@click.option('--check', '-c', 'is_check', is_flag=True, help='只检测配置文件中的 IP 的连通性')
@click.pass_context
def ping(_ctx: click.Context,
         src_type: str,
         is_check: bool,
):
    """检测服务器连通性"""
    global CFG, CONSOLE
    try:
        best_ip = None
        best_port = 0

        if is_check:
            tdx_cfg = CFG.get('pytdx', {}) # type: dict
            addresses = []

            if src_type == 'stock':
                addresses = tdx_cfg.get('stock_addresses', []) # type: list[str]
            else:
                addresses = tdx_cfg.get('future_addresses', []) # type: list[str]

            fast_delay = datetime.timedelta(seconds=10)

            for addr in addresses:
                ip, port = addr.split(':') if ':' in addr else (addr, 7709)
                port = int(port)
                delay_dt = pytdx_ping(ip=ip, port=port, type_=src_type)
                ok = delay_dt < datetime.timedelta(0, 9, 0) if delay_dt else False
                CONSOLE.print(f"{'✅' if ok else '❌'} ping(ip={ip}, port={port}), 延时： {delay_dt}")
                if ok:
                    if delay_dt < fast_delay:
                        best_addr = ip
        else:
            best_addr = select_best_ip(src_type)
            if best_addr:
                best_ip = best_addr.get('ip')
                best_port = best_addr.get('port')

        if best_ip and best_port:
            CONSOLE.print(f"把 IP 设置为最优IP: {best_ip}:{best_port}")

            _ctx.obj[f'{src_type}_best_ip'] = best_ip
            _ctx.obj[f'{src_type}_best_port'] = best_port


    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.option('-s', '--stock', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 000001.SZ)')
@click.option('--start', '-st', 'start_date', type=DATETIME, default='20260101', show_default=True, help='起始日期 YYYYMMDD')
@click.option('--end', '-et', 'end_date', type=DATETIME, default=datetime.datetime.now(), show_default=True, help='结束日期 YYYYMMDD，默认今天')
@click.pass_context
def get_k_data(_ctx: click.Context, stocks: list[str],
               start_date: str, end_date: str,
               ):
    """获取K线（日k）数据"""
    global CFG, CONSOLE
    start_date_str = start_date.strftime('%Y-%m-%d') if (start_date and isinstance(start_date, datetime.datetime)) else ''
    end_date_str = end_date.strftime('%Y-%m-%d') if (end_date and isinstance(end_date, datetime.datetime)) else ''

    print_locals()

    hq_api = _ctx.obj.get('hq_api', None) # type: TdxHq_API
    if not hq_api:
        E("行情API未初始化，请先连接服务器")
        return
    try:
        for stock in stocks:
            code = SecurityCode(stock)
            market_enum = get_market_enum(code.market_code)
            k_lines = hq_api.get_k_data(code=code.short_code, start_date=start_date_str, end_date=end_date_str)
            if isinstance(k_lines, pd.DataFrame):
                df = k_lines
            else:
                df = hq_api.to_df(k_lines)
            print_dataframe(df, title=f"{stock} 日K线数据")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.pass_context
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 000001.SZ)')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='显示详细信息')
def get_security_quotes(
    _ctx: click.Context,
    stocks: list[str],
    verbose: bool,
    ):
    """获取五档行情"""
    global CFG, CONSOLE
    hq_api = _ctx.obj.get('hq_api', None) # type: TdxHq_API
    try:
        code_tuples = [security_code_to_tuple(stock) for stock in stocks]
        print_locals()
        quotes = hq_api.get_security_quotes(code_tuples)
        df = hq_api.to_df(quotes)
        df = df.loc[:, (df != 0).any(axis=0)] # 删除 df 中 value 全部是 0 的列
        if verbose:
            CONSOLE.print(df)
        else:
            print_dataframe(df, title="五档行情数据")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 000001.SZ)')
@click.option('--period', '-p', 'period', type=click.Choice(PERIOD_2_CATEGORY.keys()), default='1d', help='周期')
@click.option('--start', '-st', 'start', type=int, default=0, help='起始第几根K')
@click.option('--count', '-c', 'count', type=int, default=100, help='数量')
@click.pass_context
def get_security_bars(
    _ctx: click.Context,
    stocks: list[str],
    period: str,
    start: int,
    count: int,
):
    """获取K线数据（在线）"""
    global CFG, CONSOLE
    hq_api = _ctx.obj.get('hq_api', None) # type: TdxHq_API
    try:
        for stock in stocks:
            code = SecurityCode(stock)
            bar = hq_api.get_security_bars(category=PERIOD_2_CATEGORY[period],
                                     market=get_market_enum(code.market_code).value,
                                     code=code.short_code, start=start, count=count)
            CONSOLE.print(bar)
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)

# ---------------------------------------------------------------------------------------------------
@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.option('-m', '--market', 'markets', multiple=True, callback=split_comma, help='市场')
@click.option('-a', '--all', 'all_markets', is_flag=True, help='查询所有市场')
@click.option('-t', '--security-type', 'security_types', multiple=True, callback=split_comma, help='股票类型')
@click.pass_context
def get_security_list(
    _ctx: click.Context,
    markets: list[str],
    all_markets: bool,
    security_types: list[str],
):
    """获取股票列表"""
    global CFG, CONSOLE
    hq_api = _ctx.obj.get('hq_api', None) # type: TdxHq_API
    try:
        if all_markets or "ALL" in markets:
            markets = ALL_MARKET_LIST

        if not security_types:
            security_types = [SecurityType.STOCK]

        for market in markets:
            market_int = get_market_enum(market).value
            stock_list = hq_api.get_security_list(market_int)
            df = hq_api.to_df(stock_list)
            print_dataframe(df, title=f"{market} 股票列表")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@command_with_abbrev(abbrev='cqcx', context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 000001.SZ)')
@click.pass_context
def get_xdxr_info(
    _ctx: click.Context,
    stocks: list[str]
):
    """获取除权除息信息"""
    global CFG, CONSOLE
    hq_api = _ctx.obj.get('hq_api', None) # type: TdxHq_API
    if not hq_api:
        E("行情API未初始化，请先连接服务器")
        return
    try:
        for stock in stocks:
            code = SecurityCode(stock)
            market = get_market_enum(code.market_code)
            data = hq_api.get_xdxr_info(market, code.short_code)
            print(f"股票 {stock} 的除权除息信息（共 {len(data) if data else 0} 条）：")
            for i, datum in enumerate(data):
                if i == 0:
                    I(type=type(datum))
                CONSOLE.print(datum)
            print()
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.option('--type', '-t', 'src_type', type=click.Choice(['stock', 'future']), default='stock', help='选择数据源类型')
@click.option('--ip', '-i', 'ip', help='IP')
@click.option('--port', '-p', 'port', type=int, help='端口')
@click.pass_context
def connect(_ctx: click.Context,
    src_type: str,
    ip: str,
    port: int,
    ):
    """连接服务器"""
    global CONSOLE, STOCK_IP, STOCK_PORT
    print_locals(printer=CONSOLE.print)

    _ctx.ensure_object(dict)

    if src_type == 'stock':
        ip = ip or _ctx.obj.get(f'{src_type}_best_ip', STOCK_IP)
        port = port or _ctx.obj.get(f'{src_type}_best_port', STOCK_PORT)
        hq_api = TdxHq_API()
        if hq_api.connect(ip=ip, port=port):
            CONSOLE.print(f'连接股票服务器失败：ip={ip}')
            return
        _ctx.obj['hq_api'] = hq_api
    else:
        ip = ip or _ctx.obj.get(f'{src_type}_best_ip', FUTURE_IP)
        port = port or _ctx.obj.get(f'{src_type}_best_port', FUTURE_PORT)
        ex_hq_api = TdxExHq_API()
        if ex_hq_api.connect(ip=ip, port=port):
            CONSOLE.print(f'连接扩展服务器失败：ip={ip}')
            return
        _ctx.obj['ex_hq_api'] = ex_hq_api


# --------------------------------------------------------------------------------
# 常规函数
# ======================
# 初始化
def init(_ctx: click.Context):
    global CFG, CONSOLE, STOCK_IP, STOCK_PORT

    _ctx.ensure_object(dict)
    _ctx.obj['console'] = CONSOLE
    if not CFG:
        CFG = read_yaml_config()
    _ctx.obj['cfg'] = CFG

    try:
        # xtdata.enable_hello = False
        # tq.initialize(__file__)
        hq_api = TdxHq_API(multithread=True)
        hq_api.connect(ip=STOCK_IP, port=STOCK_PORT)
        _ctx.obj['hq_api'] = hq_api

        click.echo("✅ 行情API初始化成功")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


if __name__ == '__main__':
    repl_cli_main(on_init=init, prompt='pytdx> ', console=CONSOLE)
