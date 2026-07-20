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
from rich import console

from rich import print
import pandas as pd

import sys
import click
from typing import List, Dict, Optional
from pytdx.util.best_ip import select_best_ip
from simple_pytdx.api import Api
from enum import IntEnum, StrEnum, Enum

# ---------------------------------------------------------------------------------------------------
ALL_MARKET_LIST = ['SH', 'SZ']
ALL_SECURITY_TYPE_LIST = SecurityType.allows()
ALL_SECURITY_TYPE_CN_LIST = SecurityType.allows_cn()

# 可使用 -ping 功能调用 select_best_ip() 获取最佳 IP:PORT
IP = 'sztdx.gtjas.com'
PORT = 7709

CONSOLE = console.Console()
CFG = None
# ---------------------------------------------------------------------------------------------------
def get_market_enum(market_str: str) -> int:
    market_str = market_str.upper()
    if market_str == 'SZ':
        return Api.Market.SZ
    elif market_str == 'SH':
        return Api.Market.SH
    elif market_str == 'BJ':
        return Api.Market.BJ

    return None

def market_enum_to_str(market_enum: int) -> str:
    if market_enum == Api.Market.SZ:
        return 'SZ'
    elif market_enum == Api.Market.SH:
        return 'SH'
    elif market_enum == Api.Market.BJ:
        return 'BJ'
    return None

# ---------------------------------------------------------------------------------------------------
@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.argument('stocks', nargs=-1, callback=split_comma, required=False)
@click.option('-p', '--ping', is_flag=True, help="寻找最快的通达信服务器")
@click.option('-c', '--count', type=int, default=10, help='查找多少条k线')
@click.option('-v', '--verbose', is_flag=True, help='详细模式')
@click.option('-l', '--limit', default=10, show_default=True, help='个数限制')
@click.option('-m', '--market', 'markets', multiple=True, callback=split_comma, help='市场')
@click.option('-a', '--all', 'all_markets', is_flag=True, help='查询所有市场')
@click.option('-t', '--security-type', 'security_types', multiple=True, callback=split_comma, help='股票类型')
@click.option('-s', '--start', 'starts', multiple=True, callback=split_comma, help='股票代码开头')
@click.option('-cqcx', '-xdxr', 'is_cqcx', is_flag=True, help='查询除权除息')
def main(
    stocks: list[str],
    ping: bool,
    count: int,
    verbose: bool,
    limit: int,
    markets: list[str],
    all_markets: bool,
    security_types: list[str],
    starts: list[str],
    is_cqcx: bool
):

    I(**{k:v for k,v in locals().items() if v}, _level='PARAMETER')

    # 预处理参数 ----------------------------------------------------------------------------------
    if all_markets or "ALL" in markets:
        markets = ALL_MARKET_LIST

    # 股票代码不足 6位，归入 starts
    for stock in stocks:
        if len(stock) < 6:
            starts.append(stock)
            stocks.remove(stock)

    # 默认只显示股票
    if not security_types:
        security_types = [SecurityType.STOCK]

    # 支持中文名称作为参数
    st_list = []
    for st in security_types:
        if st in ALL_SECURITY_TYPE_LIST:
            st_list.append(SecurityType(st))
        elif st in ALL_SECURITY_TYPE_CN_LIST:
            st_list.append(SecurityType(SecurityType.chinese_name_2_en(st)))
    security_types.extend(st_list) # type: List[SecurityType]

    I("预处理后的参数：", **{k:v for k,v in locals().items() if v}, _level='PARAMETER')

    if ping:
        best_ip_port = select_best_ip()
        if best_ip_port and isinstance(best_ip_port, dict):
            I("最快的通达信服务器是：", ip=best_ip_port.get('ip'), port=best_ip_port.get('port'))
        else:
            E("无法连接通达信所有服务器，请检查网络")
        return


    with Api((IP, PORT)) as api:

        # 用于记录所有股票详情
        all_stock_records: List[Dict] = []

        # for m in markets:
        #     mt = MarketType(m)
        #     market_enum = Api.Market(mt.int)
        #     I(m=m, mt=mt, int=mt.int, market_enum=market_enum)
        #     stock_count = api.get_stocks_count(market_enum)
        #     market_str = MarketType(market_enum).str
        #     # market_str = MarketType.from_int(market_enum.value).str
        #     I(market=market_str, get_stocks_count=stock_count, _level="RESULT")
        # exit(1)

        for market in markets:  # e.g., [Api.Market.SH, Api.Market.SZ]
            mt = MarketType(market)
            market_enum = Api.Market(mt.int)
            market_str = mt.str
            stock_count = api.get_stocks_count(market_enum)
            I(market=market_str, get_stocks_count=stock_count, _level="RESULT")

            batch_i = 0
            done = 0

            while done < stock_count:

                stock_list: List[dict] = api.get_stocks_list(market_enum, done)
                # I(f"第 {batch_i + 1} 批：", len_stock_list=len(stock_list), _level="RESULT")
                done += len(stock_list)
                batch_i += 1

                for stock_detail in stock_list:
                    code = SecurityCode(stock_detail['股票代码'], market_str)

                    # 确定类型
                    sec_type = code.security_type
                    if sec_type is None:
                        E("无法识别: ", **stock_detail, market={market_str})
                        continue

                    if sec_type not in security_types:
                        continue

                    # 添加“类型”字段
                    stock_detail['类型'] = sec_type.chinese_name
                    stock_detail['市场'] = market_str  # 可选：显式记录市场

                    # 删除不理解的字段
                    stock_detail.pop('reserved_bytes1')
                    stock_detail.pop('reserved_bytes2')

                    # 保存整条记录
                    all_stock_records.append(stock_detail)

        # 转为 DataFrame
        df = pd.DataFrame(all_stock_records)

        if not df.empty:
            # 打印每个市场的类型分布
            for market in df['市场'].unique():
                market_df = df[df['市场'] == market]
                type_counts = market_df['类型'].value_counts().to_dict()
                print(f"市场: {market}", type_counts)

            # 打印 df中 股票代码 列以 {starts} 开头的股票信息（如：92、83、00、60 等）
            if starts:
                df = df[df['股票代码'].str.startswith(tuple(starts))]

            print(f"获取到 {len(df)} 条股票信息: {df}")
        else:
            print("未获取到任何股票信息")


        for short_code in stocks:
            code = SecurityCode(short_code)
            market = get_market_enum(code.market_code)
            D(f"get_k_line()", code=code)
            for k in api.get_k_line(Api.KLineCategory.KDay, market, short_code, 0, count):
                T(**k, _level="RESULT")

            # BUG: 此函数有bug，请按照 pytdx 项目修复
            # 但 pytdx 已经出现了 GetSecurityQuotesCmd 的抽象类，
            # 对比起来， simple_pytdx 还是沿用逐个装包解包的方式，显然很落后。
            # TODO: 后续可以把 simple_pytdx 中 api 相关的枚举和有用的方法迁移到 pytdx 中。
            # D(f"get_stock_quotes()", code=code)
            # for k in api.get_stock_quotes([(market, short_code)]):
            #     T(**k, _level="RESULT")

            print("获取财务信息:", api.get_finance_info(market, short_code))

            if is_cqcx:
                for data in api.get_xdxr_info(market, short_code):
                    # T(**data)
                    print(data['日期'], data['类型'], end=' ')
                    del data['日期']
                    del data['类型']
                    for k, v in data.items():
                        print(f'{k}: {v}, ', end='')
                print()


# --------------------------------------------------------------------------------
# 常规函数
# ======================
# 初始化
def init(_ctx: click.Context):
    global CFG, CONSOLE

    _ctx.ensure_object(dict)
    _ctx.obj['console'] = CONSOLE
    if not CFG:
        CFG = read_yaml_config()
    _ctx.obj['cfg'] = CFG

    try:
        # xtdata.enable_hello = False
        # tq.initialize(__file__)
        click.echo("✅ 初始化成功")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


if __name__ == '__main__':
    repl_cli_main(on_init=init, console=CONSOLE)
