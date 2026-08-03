#!python
# encoding: utf-8
# author: DifossChen
#


import click
from rich import print, console
from pathlib import Path

from mootdx.reader import Reader, StdReader, ExtReader
from mootdx.quotes import Quotes
import numpy as np
import pandas as pd

from difoss_stock_util.color_log_util import *
from difoss_stock_util.rich_util import *
from difoss_stock_util.security_util import SecurityType, SecurityCode
from difoss_stock_util import read_yaml_config, split_comma

# -----------------------------------------------------------------------------------
# Constants
ALL_MARKETS = ['SZ', 'SH'] # mootdx 暂时不支持 'BJ'
ALL_PERIODS = ['1d', '5m', '1m']

# -----------------------------------------------------------------------------------
# Global Variables
CONSOLE = console.Console()

# -----------------------------------------------------------------------------------
# Util

from typing import Callable, Any, Optional, Dict, Union
import time
import yaml, re, os
from functools import lru_cache
from enum import Enum


def market_2_enum(market: str) -> int:
    return {
        'SZ': 0,
        'SH': 1,
    }.get(market.upper(), -1)


def print_df(df: pd.DataFrame, title: str = "DataFrame 表格", limit: int = 100, is_cn: bool = True, **args):
    if 'show_index' not in args:
        args['show_index'] = True
    if 'show_footer' not in args:
        args['show_footer'] = True

    if is_cn:
        df.rename({
            'open': '开盘价',
            'close': '收盘价',
            'high': '最高价',
            'low': '最低价',
            'volume': '成交量',
            'amount': '成交额',
        }, inplace=True)
    if limit > 0 and limit < df.shape[0]:
        df = df.head(limit)
    print_dataframe(df, "日K（离线）", **args)
    
# -----------------------------------------------------------------------------------
@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.argument('stocks', nargs=-1, callback=split_comma)
@click.option('-m', '--market', 'market', default='SH', help='市场: SH, SZ')
@click.option('-p', '--period', 'periods', multiple=True, callback=split_comma, default=['1d'])
@click.option('-o/-no', '--online', 'is_online', is_flag=True, default=False, help='查询在线数据')
@click.option('-c/-nc', '--cache', 'is_cache', is_flag=True, default=False,
    help='查询通达信本地缓存，需手动先在通信达【选项】【盘后数据下载】')
@click.option('-l', '--limit', default=100, show_default=True, help='个数限制')
def main(
    stocks: list[str],
    market: str,
    periods: list[str],
    is_online: bool,
    is_cache: bool,
    limit: int
):

    I(**{k:v for k,v in locals().items() if v}, _level='PARAMETER')

    CFG = read_yaml_config('../config.yaml')
    TDX_DIR = CFG.get('tdx', {}).get('base_dir', 'C:/new_tdx')
    T0002_DIR = Path(TDX_DIR, 'T0002')

    try:
        client = Quotes.factory(market='std', multithread=True, heartbeat=True) # 用于线上行情
        reader = Reader.factory(market='std', tdxdir=TDX_DIR)                   # 用于离线数据

        market = market.upper()
        if market not in ALL_MARKETS:
            raise ValueError(f"不支持的市场: {market}")
        market_enum = market_2_enum(market)

        security_count = client.stock_count(market_enum)
        I("统计结果", 市场=market, 证券产品总数量=security_count)
        securities_df = client.stocks(market_enum)

        type_col = []
        for row in securities_df.itertuples():
            security_type = SecurityCode.guess_security_type(row.code, market)
            type_col.append(security_type.value)
        securities_df['type'] = type_col # 把证券类型添加到 DataFrame 中

        type_counts = securities_df['type'].value_counts().to_dict()
        stocks_df = securities_df[securities_df['type'].isin([SecurityType.STOCK.value])]
        print(f"类型分布: {type_counts}")
        print_dataframe(stocks_df, title="在线股票数据")

        if is_online:
            for stock in stocks:
                if '1d' in periods:
                    # 通达信离线数据（需要在通达信中点击菜单【选项】【盘后数据下载】，成功后，才能使用数据）
                    df = reader.daily(symbol=stock)
                    print_df(df, title=f"{stock} 日K（离线）", limit=limit)

                    # 通达信线上行情读取
                    df_online = client.bars(symbol=stock)
                    print_df(df_online, title=f"{stock} 日K（线上）", limit=limit)

                if '1m' in periods:
                    df = reader.minute(symbol=stock, suffix=1)
                    print_df(df, title=f"{stock} 1分钟K（离线）", limit=limit)

                    df_online = client.bars(symbol=stock, timeframe='1m')
                    print_df(df_online, title=f"{stock} 1分钟K（线上）", limit=limit)

                if '5m' in periods:
                    df = reader.minute(symbol=stock, suffix=5)
                    print_df(df, title=f"{stock} 5分钟K（离线）", limit=limit)

                    df_online = client.bars(symbol=stock, timeframe='5m')
                    print_df(df_online, title=f"{stock} 5分钟K（线上）", limit=limit)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
