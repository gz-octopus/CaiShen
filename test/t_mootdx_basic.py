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

try:
    from color_log_util import *
    from rich_table import *
except ImportError:
    from difoss_stock_util.color_log_util import *
    from difoss_stock_util.rich_util import *

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

class SecurityType(Enum):
    """证券类型"""
    STOCK = "stock"
    STOCK_B = "stock_b"
    FUND = "fund"
    BOND = "bond"
    INDEX = "index"
    TDX_INDEX = "tdx_index"
    OPTION = "option"
    FUTURES = "futures"
    WARRANT = "warrant"
    REPO = "repo"
    OTHER = "other"

    def __init__(self, value: str):
        self._value_ = value

    def __str__(self) -> str:
        return self._value_

    @property
    def chinese_name(self) -> str:
        """中文名称"""
        return {
            SecurityType.STOCK: '股票',
            SecurityType.STOCK_B: 'B股',
            SecurityType.FUND: '基金',
            SecurityType.BOND: '债券',
            SecurityType.INDEX: '指数',
            SecurityType.TDX_INDEX: '通达信指数',
            SecurityType.OPTION: '期权',
            SecurityType.FUTURES: '期货',
            SecurityType.WARRANT: '权证',
            SecurityType.REPO: '回购',
            SecurityType.OTHER: '其他',
            None: '未知',
        }.get(self, '未知')

    @classmethod
    def chinese_name_2_en(cls, chinese_name: str) -> Optional[str]:
        """从中文设置"""
        return {
            '股票': SecurityType.STOCK.value,
            'B股': SecurityType.STOCK_B.value,
            '基金': SecurityType.FUND.value,
            '债券': SecurityType.BOND.value,
            '指数': SecurityType.INDEX.value,
            '通达信指数': SecurityType.TDX_INDEX.value,
            '期权': SecurityType.OPTION.value,
            '期货': SecurityType.FUTURES.value,
            '权证': SecurityType.WARRANT.value,
            '回购': SecurityType.REPO.value,
            '其他': SecurityType.OTHER.value,
            None: None,
        }.get(chinese_name, None)

    @classmethod
    @lru_cache(maxsize=1)
    def allows(cls) -> list[str]:
        """获取允许的证券类型列表"""
        return [cls.STOCK.value, cls.STOCK_B.value, cls.FUND.value, cls.BOND.value,
                cls.INDEX.value, cls.TDX_INDEX.value,
                cls.OPTION.value, cls.FUTURES.value, cls.WARRANT.value, cls.REPO.value,
                cls.OTHER.value]

    @classmethod
    @lru_cache(maxsize=1)
    def allows_cn(cls) -> list[str]:
        return [SecurityType(st).chinese_name for st in cls.allows()]


class ConfigParser:
    def __init__(self, config: Union[Dict, str]):
        self.config = config

    def _expand_value(self, value: Any) -> Any:
        """递归展开配置值中的环境变量"""
        if isinstance(value, str):
            # 支持 ${VAR} 和 $VAR 两种格式
            def replace_match(match):
                var_name = match.group(1) or match.group(2)

                # 支持默认值：${VAR:-default}
                if ':-' in var_name:
                    var_name, default_value = var_name.split(':-', 1)
                    return os.getenv(var_name, default_value)

                # 支持必需变量：${VAR:?error message}
                if ':?' in var_name:
                    var_name, error_msg = var_name.split(':?', 1)
                    value = os.getenv(var_name)
                    if value is None:
                        raise ValueError(f"必需的环境变量缺失: {error_msg or var_name}")
                    return value

                # 普通变量
                return os.getenv(var_name) or match.group(0)

            # 匹配 ${VAR} 或 $VAR
            pattern = r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)'
            return re.sub(pattern, replace_match, value)

        elif isinstance(value, dict):
            return {k: self._expand_value(v) for k, v in value.items()}

        elif isinstance(value, list):
            return [self._expand_value(item) for item in value]

        else:
            return value

    def parse(self) -> Dict:
        """解析配置"""
        return self._expand_value(self.config)


def read_yaml_config(cfg_filepath='config.yaml') -> Optional[dict]:
    """读取yaml配置文件（支持环境变量）"""
    with open(cfg_filepath, 'r') as stream:
        try:
            cfg_str = stream.read()
            cfg_dict = yaml.safe_load(cfg_str)
            parser = ConfigParser(cfg_dict)
            return parser.parse()

        except yaml.YAMLError as e:
            print(e)
    return None


def split_comma(_ctx, param, value) -> list[str]:
    """将逗号分隔的字符串拆分为列表，同时支持多个值"""
    if not value:
        return []

    result = set()

    if isinstance(value, str):
        value = [value]

    for item in value:
        # D(item=item, value=value)
        # 如果值中包含逗号，进一步分割
        if isinstance(item, str) and ',' in item:
            result.update([v.strip() for v in item.split(',') if v.strip()])
        else:
            result.add(item)
    return list(result)

def market_2_enum(market: str) -> int:
    return {
        'SZ': 0,
        'SH': 1,
    }.get(market.upper(), -1)

def guess_security_type(short_code: str, market: str) -> Optional[SecurityType]:
    """根据证券代码和市场推测交易标的类型

    Returns:
        SecurityType: 推测的交易标的类型

    References:
        pytdx/reader/daily_bar_reader.py: get_security_type(self, fname)
    """
    head5 = short_code[:5]
    head3 = short_code[:3]
    head2 = short_code[:2]
    len_short_code = len(short_code)

    if market == 'SZO' and  len_short_code == 8 and head5 in ["90005", "90006"]:
        return SecurityType.OPTION  # 深圳期权

    if market == 'HK' and len_short_code == 5:
        return SecurityType.STOCK  # 港股

    if market == 'SZ':
        if head2 in ["00", "30"]:
            return SecurityType.STOCK  # A股
        elif head2 in ["20"]:
            return SecurityType.STOCK_B  # B股
        elif head2 in ["39"]:
            return SecurityType.INDEX  # 指数
        elif head2 in ["51", "16", "18"]:
            return SecurityType.FUND   # 基金
        elif head2 in ["07", "08",
                        "10", "11", "12", "13", "14", "15", "19",
                        "37", "38",
                        "50", "52", "56"]:
            return SecurityType.BOND   # 债券
        elif head2 in ["99"]:
            return SecurityType.INDEX  # 指数
    elif market == 'SH':
        if head2 in ["60", "68"]:
            return SecurityType.STOCK  # A股科创板
        elif head2 in ["90"]:
            return SecurityType.STOCK_B  # B股
        elif head2 in ["00", "99"]:
            return SecurityType.INDEX  # 指数
        elif head2 in ["88",]:
            return SecurityType.TDX_INDEX  # 通达信指数
        elif head2 in ["51", "52"]: # , "53", "54", "55", "56", "57", "58", "59"
            return SecurityType.FUND   # 基金
        elif head2 in ["00", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19",
                        "20", "23", "24", "27",
                        "50", "53",
                        "78"]:
            return SecurityType.BOND   # 债券
        elif head3 in ["010", "018", "019", "020", "231"]:
            return SecurityType.BOND   # 债券（国债）
        elif head2 in ["55", "71"]:
            return SecurityType.BOND   # 债券
        elif head2 in ["56", "58"]:
            return SecurityType.FUND   # 基金
        elif head2 in ["36", "73", "75", "79"]:
            return SecurityType.OTHER  # 其他
    elif market == 'BJ':
        if head2 in ["92"]:
            return SecurityType.STOCK
        elif head2 in ["89"]:
            return SecurityType.INDEX

    return None


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

    CFG = read_yaml_config('mini_config.yaml')
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
            security_type = guess_security_type(row.code, market)
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
