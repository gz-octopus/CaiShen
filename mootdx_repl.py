#!python
# encoding: utf-8

import click
import click_shell
from rich import print as pprint
from rich import console
from rich.console import Console
from datetime import datetime

from difoss_stock_util import *
from difoss_stock_util.color_log_util import *



from mootdx.quotes import Quotes, StdQuotes, ExtQuotes
from mootdx.utils import FREQUENCY, get_frequency
from mootdx.reader import Reader, StdReader

# 旧版本的 pytdx
from pytdx.exhq import TdxExHq_API
from pytdx.util.best_ip import select_best_ip

from cache_cmd import cache_stock_name, get_stock_name, STOCKS
from cache_cmd import memory_cache  # 引入 mc 命令

# --------------------------------------------------------------------------------
# Global Variables

# --------------------------------------------------------------------------------
# 全局变量
CONSOLE = Console()
CFG = None
ALL_PERIODS = FREQUENCY  # NOTE: 注意：days 的 vol 比 day 大 100 倍
CONFIG_PATH = 'config.yaml'  # 默认配置文件路径

# --------------------------------------------------------------------------------
# Utils

# --------------------------------------------------------------------------------
# 子命令

# ======================
# 例子
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.pass_context
def _example(_ctx: click.Context,
    stocks: list[str]
):
    """"""
    _CSL = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            # TODO:
            _CSL.print(f"{full_code} :", )
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


@command_with_abbrev(abbrev='ip', context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.pass_context
def best_ip(_ctx: click.Context,
):
    """获取最佳IP地址"""
    _CSL = _ctx.obj['console'] # type: Console
    try:
        # 旧版本的 pytdx 内置的 ip 列表，可能不太准确了，后续可以考虑更新一下
        ip = select_best_ip('future')
        _CSL.print(f"最佳IP: {ip}")
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)

@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=['MHI2604'], required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--period', '-p', default='days', type=click.Choice(ALL_PERIODS, case_sensitive=False),
            help='K线周期')
@click.pass_context
def get_instrument_bars(_ctx: click.Context,
    stocks: list[str],
    period: str,
):
    """获取期货合约数量"""

    _CSL = _ctx.obj['console'] # type: Console
    _CFG = _ctx.obj['cfg'] # type: dict
    ip = _CFG.get('mootdx', {}).get('ip', '112.74.214.43')
    port = int(_CFG.get('mootdx', {}).get('port', 7727))
    frequency = get_frequency(period)

    print_locals()

    try:
        api = TdxExHq_API()
        with api.connect(ip, port):
            for stock in stocks:
                code, market = stock.split('.')

                # TODO: 目前在测试恒指数据，默认返回 4
                if not market:
                    market = 'HK'
                market_int = {'SH': 1, 'SZ': 0, 'HK': 4}.get(market.upper(), 4)

                if market_int is None:
                    CONSOLE.print(f"不支持的市场类型: {market} (仅支持 SH、SZ、HK)")
                    continue
                code = code.encode('utf-8')
                CONSOLE.print(f"正在获取 {stock} 的期货合约K线数据...")

                count = api.get_instrument_bars(frequency=frequency, market=market_int, code=code)
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)

# ---------------------------------------------------------------------------------------------
# 行情类信息
@click.command(short_help="获取K线数据", context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 688318.SH)')
# @click.option('--start-time', '-st', 'start_time', type=DATETIME, help='开始时间')
# @click.option('--end-time', '-et', 'end_time', type=DATETIME, default=datetime.now(), help='结束时间')
@click.option('--start', '-st', 'start', type=int, default=0, help='从第几条K开始（最后一个交易日为 0）')
@click.option('--count', '-c', 'count', type=int, default=20, help='每次获取条数【一次性最多获取 800 条】')
@click.option('--period', '-p', default='days', type=click.Choice(ALL_PERIODS, case_sensitive=False),
              help='K线周期')
@click.option('--dividend-type', '-dt', default='front', type=click.Choice(['none', 'front', 'back']), help='复权类型')
# @click.option('--count', '-c', default=-1, type=int, help='获取数据条数 (-1 表示全部)【注：一次性最多获取24000条，要获取完整分钟线需要多次分批获取】')
@click.option('--fill-data/--no-fill-data', default=True, help='是否填充缺失数据')
@click.option('--table/-no-table', '-t/-nt', 'show_table', is_flag=True, default=True, help='是否以表格显示结果（默认：是）')
@click.pass_context
def get_market_data(
    _ctx: click.Context,
    stocks: list[str],
    # start_time: datetime | None,
    # end_time: datetime | None,
    start: int,
    count: int,
    period: str,
    dividend_type: str,
    fill_data: bool,
    show_table: bool,
):
    """在线获取K线数据"""
    _CSL = _ctx.obj['console'] # type: Console

    # NOTE: mootdx 特有的，days 的 vol 比 1d 大 100 倍，成交量单位：手
    frequency = get_frequency(period)

    adjust = {
        'none': '',
        'front': 'before',
        'back': 'after',
    }.get(dividend_type, '')

    print_locals()

    try:
        std_client = _ctx.obj['std_client'] # type: StdQuotes
        for full_code in stocks:
            # TODO:
            feed = std_client.bars(symbol=full_code, frequency=frequency, start=start, offset=count, adjust=adjust)

            if show_table:
                print_dataframe(feed, title=f"股票数据 {full_code} （{period}）K线数据",
                                show_footer=True, printer=_CSL.print)
            else:
                _CSL.print(f"股票数据 {full_code} （{period}）K线数据:\n{feed}")
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


@click.command(short_help="获取K线数据（本地）", context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 688318.SH)')
# @click.option('--start-time', '-st', 'start_time', type=DATETIME, help='开始时间')
# @click.option('--end-time', '-et', 'end_time', type=DATETIME, default=datetime.now(), help='结束时间')
# @click.option('--start', '-st', 'start', type=int, default=0, help='从第几条K开始（最后一个交易日为 0）')
# @click.option('--count', '-c', 'count', type=int, default=20, help='每次获取条数【一次性最多获取 800 条】')
@click.option('--period', '-p', default='1d', type=click.Choice(['1d', '1m', '5m'], case_sensitive=False),
              help='K线周期')
@click.option('--dividend-type', '-dt', default='front', type=click.Choice(['none', 'front', 'back']), help='复权类型')
# @click.option('--count', '-c', default=-1, type=int, help='获取数据条数 (-1 表示全部)【注：一次性最多获取24000条，要获取完整分钟线需要多次分批获取】')
# @click.option('--fill-data/--no-fill-data', default=True, help='是否填充缺失数据')
@click.option('--table/-no-table', '-t/-nt', 'show_table', is_flag=True, default=True, help='是否以表格显示结果（默认：是）')
@click.pass_context
def get_market_data_local(
    _ctx: click.Context,
    stocks: list[str],
    # start_time: datetime | None,
    # end_time: datetime | None,
    # start: int,
    # count: int,
    # offset: int,
    period: str,
    dividend_type: str,
    # fill_data: bool,
    show_table: bool,
):
    """读取股票本地行情数据"""
    _CSL = _ctx.obj['console'] # type: Console
    
    adjust = {
        'none': '',
        'front': 'before',
        'back': 'after',
    }.get(dividend_type, '')

    print_locals()

    try:
        std_reader = _ctx.obj['std_reader'] # type: StdReader
        for full_code in stocks:
            # TODO:
            if period == '1d':
                feed = std_reader.daily(symbol=full_code, adjust=adjust)
            elif period == '1m':
                feed = std_reader.minute(symbol=full_code)
            elif period == '5m':
                feed = std_reader.minute(symbol=full_code, suffix=6)
            else:
                E(f"本地数据不支持周期 {period}")
                return

            if show_table:
                print_dataframe(feed, title=f"股票数据 {full_code} （{period}）K线数据",
                                show_footer=True, printer=_CSL.print)
            else:
                _CSL.print(f"股票数据 {full_code} （{period}）K线数据:\n{feed}")
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)



@click.command(short_help="查询（历史）分笔成交", context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 688318.SH)')
@click.option('--start', '-st', 'start', type=int, default=0, help='从第几条K开始（最后一个交易日为 0）')
@click.option('--count', '-c', 'count', type=int, default=20, help='每次获取条数【一次性最多获取 800 条】')
@click.option('--history', '-h', 'is_history', is_flag=True, help='历史数据')
@click.option('--date', '-d', 'date', type=DATETIME, default=datetime.now(), help='日期(仅当 -h/--history 时有效)')
@click.pass_context
def transaction(_ctx: click.Context,
    stocks: list[str],
    start: int,
    count: int,
    is_history: bool,
    date: datetime,
):
    """查询（历史）分笔成交"""
    _CSL = _ctx.obj['console'] # type: Console
    date = date.strftime('%Y%m%d')

    print_locals()

    try:
        std_client = _ctx.obj['std_client'] # type: StdQuotes
        for full_code in stocks:
            if is_history:
                df = std_client.transactions(symbol=full_code, start=start, offset=count, date=date)
            else:
                df = std_client.transaction(symbol=full_code, start=start, offset=count)

            print_dataframe(df, title=f"{full_code} 的分笔{'历史' if is_history else ''}成交")
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)

# --------------------------------------------------------------------------------
# 常规函数
# ======================
# 初始化
def init(_ctx: click.Context):
    global CFG, CONSOLE, CONFIG_PATH

    _ctx.ensure_object(dict)
    _ctx.obj['config_path'] = CONFIG_PATH
    _ctx.obj['console'] = CONSOLE
    if not CFG:
        CFG = read_yaml_config(CONFIG_PATH)
    _ctx.obj['cfg'] = CFG

    tdx_root = CFG.get('tdx', {}).get('base_dir', 'C:/new_tdx')
    _ctx.obj['tdx_root'] = tdx_root
        
    moo_tdx_cfx = CFG.get('mootdx', {})
    IP = moo_tdx_cfx.get('ip', 'sztdx.gtjas.com')
    PORT = int(moo_tdx_cfx.get('port', 7709))


    try:
        # xtdata.enable_hello = False
        # tq.initialize(__file__)
        std_client = Quotes.factory(best_ip=True, valid_server=True, market='std', multithread=True)
        # std_client = Quotes.factory(ip=IP, port=PORT, market='std', multithread=True)
        
        _ctx.obj['std_client'] = std_client
        CONSOLE.print(f"best ip = {std_client.bestip}")

        std_reader = Reader.factory(market='std', tdxdir=tdx_root)
        _ctx.obj['std_reader'] = std_reader

        click.echo("✅ MOOTDX 初始化成功")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ======================
# main（根据参数决定模式）
if __name__ == '__main__':
    repl_cli_main(doc='mootdx数据工具', prompt='mootdx> ', on_init=init, console=CONSOLE)
