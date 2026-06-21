#!python
# encoding: utf-8

import click
from rich import print as pprint
from rich.pretty import Pretty
from rich.console import Console

from difoss_stock_util import *
from difoss_stock_util.color_log_util import *
from difoss_stock_util.util import read_yaml_config, print_locals
from difoss_stock_util.click_util import *

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import time
from typing import List, Dict, Callable

# --------------------------------------------------------------------------------
# 全局变量
CONSOLE = Console()
CFG = None

# --------------------------------------------------------------------------------
# Utils
TIMEFRAME_STR2INT = {
    "M1": mt5.TIMEFRAME_M1,
    "M2": mt5.TIMEFRAME_M2,
    "M3": mt5.TIMEFRAME_M3,
    "M4": mt5.TIMEFRAME_M4,
    "M5": mt5.TIMEFRAME_M5,
    "M6": mt5.TIMEFRAME_M6,
    "M10": mt5.TIMEFRAME_M10,
    "M12": mt5.TIMEFRAME_M12,
    "M15": mt5.TIMEFRAME_M15,
    "M20": mt5.TIMEFRAME_M20,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H2": mt5.TIMEFRAME_H2,
    "H4": mt5.TIMEFRAME_H4,
    "H3": mt5.TIMEFRAME_H3,
    "H6": mt5.TIMEFRAME_H6,
    "H8": mt5.TIMEFRAME_H8,
    "H12": mt5.TIMEFRAME_H12,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "N1": mt5.TIMEFRAME_MN1,
}

TIMEFRAMES = list(TIMEFRAME_STR2INT.keys())

def _timeframe_str2int(tf_str: str):
    return TIMEFRAME_STR2INT.get(tf_str)

from mt5_const import *

# --------------------------------------------------------------------------------
# 子命令

@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('-c', '--contains', 'contains', multiple=True, callback=split_comma, help='name 中包含的字串')
@click.option('-g', '--group', 'group', default=None, help='分组名称（支持 * 通配符）')
@with_field_filter_options(en2cn_map=SYMBOL_INFO_EN_2_CN, cn2en_map=SYMBOL_INFO_CN_2_EN)
@click.option('-max', '--max-to-show', 'max_to_show', default=20, show_default=True, type=int, help='最多显示多少只股票')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.pass_context
def symbols_get(_ctx: click.Context,
                contains: list[str],
                group: str,
                max_to_show: int,
                verbose: bool,
                **kwargs,
):
    """列出所有交易品种（及数量）"""
    CONSOLE = _ctx.obj['console'] # type: Console

    symbols = mt5.symbols_get(group=group)
    if not symbols:
        CONSOLE.print("未获取到任何交易品种，可能是连接问题或分组名称错误。")
        return
    
    if verbose:
        CONSOLE.print(f"📖 symbols_get(group='{group}') 返回: {symbols}")

    print(f"总品种数: {len(symbols)}")

    if contains:
        symbols = [s for s in symbols if any(c in s.name for c in contains)]
        CONSOLE.print(f"过滤后品种数: {len(symbols)}")


    # 使用装饰器注入的 helper 来处理 list[dict] 的字段筛选/翻译
    symbol_dicts = [s._asdict() for s in symbols]  # type: List[dict]

    list_field_filter = _ctx.obj.get('list_field_filter') if hasattr(_ctx, 'obj') else None \
        # type: Callable[[List[dict], bool], List[dict]]
    if list_field_filter:
        symbol_dicts = list_field_filter(symbol_dicts)

    CONSOLE.print(f"交易品种列表{'（过滤后）' if contains else ''}:", end='')
    CONSOLE.print(Pretty(symbol_dicts, max_length=max_to_show) if (symbol_dicts and max_to_show > 0) else symbol_dicts)

    return symbols


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--symbol', '-s', 'symbols', multiple=True, callback=split_comma, default=["XAGUSD."], required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--period', '-p', '-t', 'period', type=click.Choice(TIMEFRAMES, case_sensitive=False),  default=TIMEFRAMES[0], help='周期')
@click.option('--count', '-c', 'count', type=int, default=100, help='获取多少条K线')
@click.option('--save', '-save', 'is_save', is_flag=True, help='是否保存')
@click.pass_context
def fetch_deep_history(
    _ctx: click.Context,
    symbols: list[str],
    period: str,
    count: int,
    is_save: bool,
):
    """获取历史数据"""
    CONSOLE = _ctx.obj['console'] # type: Console
    
    period = period.upper()

    timeframe = _timeframe_str2int(period)

    if not timeframe:
        CONSOLE.print("⚠️ [red]周期不能为空[/red]")
        return

    # 2. 激活品种
    for symbol in symbols:
        mt5.symbol_select(symbol, True)

        all_chunks = []
        start_index = 0
        chunk_size = min(1000, count)  # 每次最多拉取 1000 条

        CONSOLE.print(f"开始分页拉取 {symbol} 历史数据...")

        while start_index < count:
            # copy_rates_from_pos(品种, 周期, 起始索引, 数量)
            # 索引 0 是最旧的吗？不，0 是最新的（当前 K 线），索引越大越久远
            rates = mt5.copy_rates_from_pos(symbol, timeframe, start_index, chunk_size)

            if rates is None or len(rates) == 0:
                CONSOLE.print(f"⚠️ 在索引 {start_index} 处无法获取更多数据，可能已达服务器上限。")
                break

            df_chunk = pd.DataFrame(rates)
            all_chunks.append(df_chunk)

            # 打印进度
            current_earliest = pd.to_datetime(df_chunk['time'].min(), unit='s')
            CONSOLE.print(f"已拉取索引 [{start_index} 至 {start_index + len(rates)}]，最远到达: {current_earliest}")

            # 增加起始位置，准备拉取更老的数据
            start_index += len(rates)

            # 如果拉到的数量少于请求的数量，说明到头了
            if len(rates) < chunk_size:
                print("到达数据末尾。")
                break

            # 给终端一点喘息时间去解压数据
            time.sleep(0.1)

        # 3. 合并数据
        if not all_chunks:
            CONSOLE.print("⚠️ 未获取到任何数据")
            return

        df = pd.concat(all_chunks)

        # 4. 转换时间并清洗
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.rename(columns={'tick_volume': 'volume'}, inplace=True)
        df = df[['time', 'open', 'high', 'low', 'close', 'volume']]

        # 去重（防止分页重叠）并按时间正序排列
        df = df.drop_duplicates(subset=['time']).sort_values('time')
        df.set_index('time', inplace=True)

        CONSOLE.print(f"🍾 获取成功")
        CONSOLE.print(f"总条数: {len(df)}")
        CONSOLE.print(f"时间跨度: {df.index.min()} 至 {df.index.max()}")
        print_dataframe(df, title=f"{symbol} 数据（周期:{period}）", )
        
        if is_save:
            # 5. 保存
            time_range_str4fn = f"{df.index.min()}→{df.index.max()}".replace(' ', '_').replace(':','')
            output_path = f"{time_range_str4fn}_{symbol}_{period}.parquet"
            df.to_parquet(output_path, engine='pyarrow', compression='snappy')
            CONSOLE.print(f"💾 数据已存至: {output_path}")


# ======================
# 例子
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.pass_context
def _example(_ctx: click.Context,
    stocks: list[str]
):
    """"""
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            # TODO:
            CONSOLE.print(f"{full_code} :", )
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# --------------------------------------------------------------------------------
# 常规函数
# ======================
# 初始化
def init(_ctx: click.Context):
    global CFG, CONSOLE

    config_path = 'config.yaml' # TODO：添加参数进行更新配置文件即可，无需在 repl/cli 入口参数填写。

    _ctx.ensure_object(dict)
    _ctx.obj['config_path'] = config_path
    _ctx.obj['console'] = CONSOLE
    if not CFG:
        CFG = read_yaml_config(config_path)
    _ctx.obj['cfg'] = CFG

    try:
        # 1. 初始化
        if not mt5.initialize():
            print(f"❌ MT5 初始化失败, 错误码 = {mt5.last_error()}")
            return
        click.echo("✅ MT5 初始化成功")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


def destroy(_ctx: click.Context):
    mt5.shutdown()


# ======================
# main（根据参数决定模式）
if __name__ == '__main__':
    repl_cli_main(doc='MT5 数据工具', prompt='mt5> ', on_init=init, on_destroy=destroy, console=CONSOLE)
