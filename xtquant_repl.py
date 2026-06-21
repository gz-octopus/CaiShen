#!python
# -*- coding: utf-8 -*-
"""CLI 工具，支持批处理模式和交互模式（REPL）"""

import click
import click_shell
from rich import print as pprint
from rich.console import Console, Group
from tdx_quant.tqcenter import tq
from xtquant import xtdata
from pathlib import Path
from datetime import datetime
import pandas as pd

from difoss_stock_util import *
from difoss_stock_util.color_log_util import *

from difoss_stock_util.metric_data.stock_instrument_detail import *
from cache_cmd import STOCKS, memory_cache

from mootdx.utils import to_data
from difoss_stock_util.xtquant_util import *
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.live import Live
from rich.panel import Panel
from rich.pretty import Pretty
from rich.text import Text
import threading
from typing import Dict, List, Optional, Any
import atexit
import contextlib
import time
from tdxdata_repl import cache_stock_name_of_market
from cache_cmd import get_stock_name, stocks_collector, df_collector, STOCKS

from stock_classify import analyze_stock_symbols, print_statistics

# --------------------------------------------------------------------------------
# Constants
ALL_PERIODS = [
    'tick', '1m', '5m', '15m', '30m', '1h', '1d', # level1 数据
    'l2quote', 'l2order', 'l2transaction', 'l2quoteaux', 'l2orderqueue', 'l2thousand', # level2 数据
]

# Global Variables
CONSOLE = Console()
CFG = None
PG_URL = None
CONFIG_PATH = 'config.yaml'  # 默认配置文件路径

ALL_MARKET_LIST = ['SH', 'SZ', 'BJ']

# --------------------------------------------------------------------------------
# Util Functions & Classes

def _cb_data(data):
    """获取数据时的回调"""
    global CONSOLE # type: rich.console.Console
    CONSOLE.print(f"=== data: {data}")

class ProgressManager:
    """进度管理器单例类"""

    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.console: Optional[Console] = None
        self._progress: Optional[Progress] = None
        self._live: Optional[Live] = None
        self._main_task_id: Optional[int] = None
        self._total_items: int = 0
        self._current_finished: int = 0
        self._progress_lock = threading.Lock()
        self._is_active: bool = False

        # 当前回调数据
        self._current_data: Dict[str, Any] = {}

        # 注册退出清理
        atexit.register(self.cleanup)

        self._initialized = True

    @classmethod
    @contextlib.contextmanager
    def init(cls, stock_list: List[str], console: Console, description: str = "下载K线数据"):
        """初始化进度管理器（作为上下文管理器使用）"""
        manager = cls()
        manager.console = console

        with manager._progress_lock:
            manager._setup_progress(description)

        try:
            yield manager
        finally:
            manager.cleanup()

    def _setup_progress(self, description: str):
        """设置进度条"""
        self._is_active = True
        self._current_finished = 0
        self._total_items = 0
        self._current_data = {}

        # 创建进度条 - 只有一个主进度条
        self._progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=self.console,
            expand=True
        )

        # 创建总体进度任务
        self._main_task_id = self._progress.add_task(
            f"[cyan]{description}",
            total=100,  # 用百分比
            completed=0
        )

        # 创建 Live 显示，包含进度条和调试信息
        self._live = Live(
            self._generate_display(),
            console=self.console,
            refresh_per_second=10,
            screen=False
        )
        self._live.start()

    def _generate_display(self):
        """生成显示内容（进度条 + 当前数据）"""
        if not self._progress:
            return Text("初始化中...")

        # 获取进度条的渲染内容
        progress_render = self._progress.make_tasks_table(self._progress.tasks)

        # 创建数据面板 - 原样打印当前数据
        data_panel = Panel(
            Pretty(self._current_data, indent_size=2),
            title="[bold bright_black]当前回调数据[/bold bright_black]",
            border_style="bright_black",
            padding=(0, 1)
        )

        return Group(progress_render, data_panel)

    @property
    def callback(self):
        """获取回调函数"""
        return self._cb_data

    def _cb_data(self, data: Dict[str, Any]):
        """回调函数处理进度更新

        数据格式: {'finished': 337, 'total': 37600, 'stockcode': '', 'message': '301085.SZ'}
        """
        with self._progress_lock:
            if not self._is_active or self._progress is None or self._live is None:
                return

            # 保存当前数据
            self._current_data = data.copy()

            finished = data.get('finished', 0)
            total = data.get('total', 0)
            current_stock = data.get('message', '')

            # 更新总数据量
            if total > 0:
                self._total_items = total
            self._current_finished = finished

            # 更新进度条
            if self._main_task_id is not None and self._total_items > 0:
                # 计算百分比进度
                percentage = (finished / self._total_items * 100) if self._total_items > 0 else 0

                # 更新进度条，同时显示当前股票信息
                description = f"[cyan]下载K线数据"
                if current_stock:
                    description += f" - [green]{current_stock}"
                description += f" [{finished}/{self._total_items}]"

                self._progress.update(
                    self._main_task_id,
                    completed=percentage,
                    description=description
                )

            # 更新 Live 显示
            self._live.update(self._generate_display())

            # 检查是否完成
            if finished >= self._total_items and self._total_items > 0:
                self._on_complete()

    def _on_complete(self):
        """下载完成处理"""
        self._is_active = False

        # 更新进度条为完成状态
        if self._progress and self._main_task_id:
            try:
                self._progress.update(
                    self._main_task_id,
                    completed=100,
                    description=f"[green]下载完成! 总计 {self._total_items} 条数据"
                )
            except:
                pass

            # 最后更新一次显示
            if self._live:
                self._live.update(self._generate_display())

    def cleanup(self):
        """清理进度条资源"""
        with self._progress_lock:
            if self._live:
                try:
                    # 最终更新
                    if self._progress:
                        self._live.update(self._generate_display())
                    time.sleep(0.1)  # 给最后一次更新一点时间
                    self._live.stop()
                except:
                    pass

            if self._progress:
                try:
                    self._progress.stop()
                except:
                    pass

            # 重置所有状态
            self._progress = None
            self._live = None
            self._main_task_id = None
            self._total_items = 0
            self._current_finished = 0
            self._is_active = False
            self._current_data = {}

            if self.console:
                self.console.print()  # 添加一个空行

# --------------------------------------------------------------------------------
# 子命令

@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('-m', '--market', 'markets', multiple=True, callback=split_comma_upper,
            help='市场代码（可多次使用，自动转换大写，支持半角逗号分隔），如: -m SH -m SZ 或者 -m SH,SZ ')
@click.option('-d', '--diff', 'different', is_flag=True, help='对比其他库看缺失了哪只股票')
@click.option('--max-to-show', '-max', 'max_to_show', default=20, show_default=True, type=int, help='最多显示多少只股票')
@click.pass_context
def market(_ctx: click.Context,
    markets: list[str],
    different: bool,
    max_to_show: int,
    is_save_memory: bool,
    group_index: int,
):
    """市场相关功能"""
    if ('ALL' in markets) or (not markets):
        markets = ALL_MARKET_LIST

    CONSOLE = _ctx.obj['console'] # type: Console

    print_locals()

    try:
        if different: # 对比
            xt_stocks = []
            for market in markets:
                codes = get_market_stocks(market)

                if codes:
                    full_codes = [x.full_code for x in codes]
                    xt_stocks.extend(full_codes)

                CONSOLE.print(f"市场 {market} 有 {len(codes)} 只股票")

            tq_stocks = tq.get_stock_list()

            CONSOLE.print(f"xtquant 共返回 {len(xt_stocks)} 只股票，tq 共返回 {len(tq_stocks)} 只股票")
            if len(xt_stocks) != len(tq_stocks):
                dif = find_list_diff(xt_stocks, tq_stocks)
                CONSOLE.print(f"对比市场 {ALL_MARKET_LIST}，xtquant 与 tq_center 返回的两个结果差异: ")
                only_in_xt = dif.get('only_in_list1', [])
                only_in_tq = dif.get('only_in_list2', [])
                CONSOLE.print(f" 只存在于 xt 返回結果: ", end='')
                CONSOLE.print(Pretty(only_in_xt, max_length=max_to_show) if max_to_show > 0 else only_in_xt)
                CONSOLE.print(f" 只存在于 tq 返回結果: ", end='')
                CONSOLE.print(Pretty(only_in_tq, max_length=max_to_show) if max_to_show > 0 else only_in_tq)

            return

        codes_in_markets = set()
        for market in markets:
            codes = get_market_stocks(market)
            full_codes = [x.full_code for x in codes]
            codes_in_markets.update(full_codes)

            codes_with_name = [f"{x}|{get_stock_name(x)}" for x in full_codes]
            CONSOLE.print(f"市场 {market} 股票共 {len(full_codes)} 只：", end='')
            CONSOLE.print(Pretty(codes_with_name, max_length=max_to_show) if max_to_show > 0 else codes)

        if is_save_memory:
            return {'stocks': codes_in_markets}

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True,
            help='股票代码列表 (如: 688318.SH 或 688318)，支持半角逗号分隔')
@click.pass_context
def stock(
    _ctx: click.Context,
    stocks: list[str]
):
    """股票相关功能"""
    # TODO: 待完善
    print_locals()
    try:
        pass
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)

# ---------------------------------------------------------------------------------------------
# 基础行情信息

@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True,
              default=STOCKS,
              help='股票代码列表 (如: 688318.SH)')
@click.option('--start-time', '-st', 'start_time', type=DATETIME, default=None, help='开始时间')
@click.option('--end-time', '-et', 'end_time', type=DATETIME, default=None, help='结束时间')
@click.option('--period', '-p', default='1d', help='K线周期',
              type=click.Choice(ALL_PERIODS))
@click.pass_context
def download_history_data(_ctx: click.Context,
    stocks: list[str],
    start_time: datetime | None,
    end_time: datetime | None,
    period: str,
):
    """下载历史数据(xtdata)"""
    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console

    with ProgressManager.init(stock_list=stocks, console=CONSOLE) as pm:
        try:
            # FUCK: 他妈的 xtdata 真是啰嗦！！
            params = dict(
                stock_list=stocks,
                period=period,
                callback=pm.callback,
            )
            if start_time:
                params['start_time'] = start_time or ''
            if end_time:
                params['end_time'] = end_time or ''

            xtdata.download_history_data2(**params)
        except Exception as e:
            CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(short_help="获取K线数据", context_settings={'help_option_names': ['-?', '--help', '-h']})
@df_collector
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
              default=STOCKS,
              required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--start-time', '-st', 'start_time', type=DATETIME, default=None, help='开始时间')
@click.option('--end-time', '-et', 'end_time', type=DATETIME, default=None, help='结束时间')
@click.option('--period', '-p', default='1d', help='K线周期',
              type=click.Choice(ALL_PERIODS))
@click.option('--dividend-type', '-dt', default='front', type=click.Choice(['none', 'front', 'back']), help='复权类型')
@click.option('--fields', '-f', multiple=True, callback=split_comma, help='返回字段列表')
@click.option('--count', '-c', default=-1, type=int, help='获取数据条数 (-1 表示全部)')
@click.option('--fill-data/--no-fill-data', '-fd/-no-fd', 'fill_data', default=True, help='是否填充缺失数据')
@click.option('--ex', '-ex', 'is_ex', is_flag=True, help='调用 get_market_data_ex()')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.pass_context
def get_market_data(_ctx: click.Context,
                    stocks: list[str],
                    start_time: datetime | None,
                    end_time: datetime | None,
                    period: str,
                    dividend_type: str,
                    fields: list[str],
                    count: int,
                    fill_data: bool,
                    is_ex: bool,
                    verbose: bool,
                    is_save_df: bool,
):
    """获取K线数据(xtdata)"""
    dt = DividendType.from_str(dividend_type) # type: DividendType
    adjust = {
        'none': None,
        'front': 'before',
        'back': 'after'
    }.get(dt.str_value, None) # 适配 mootdx 的复权定义

    print_locals()

    parameters = {
        'field_list': fields,
        'stock_list': stocks,
        'period': period,
        'count': count,
        'dividend_type': dt.str_value,
        'fill_data': fill_data,
    }
    if end_time:
        end_time = datetime.now()
        parameters.update({'end_time': end_time.strftime("%Y%m%d%H%M%S")})

    if count > 0:
        if start_time:
            parameters.update({'start_time': start_time.strftime("%Y%m%d%H%M%S")})

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        if is_ex:
            stock_2_df = xtdata.get_market_data_ex(**parameters)
        else:
            res = xtdata.get_market_data(**parameters)

            if verbose:
                CONSOLE.print(f"get_market_data RETURN: {res}")

            # DEBUG: 发现他妈的居然以 stock 作为 key，而不是 datetime
            # for k, v in res.items():
            #     print_dataframe(v, title=f'Key: {k}')

            stock_2_df = transform_data(res)
            
        if not stock_2_df:
            CONSOLE.print("无返回数据")
            return

        for code, stock_df in stock_2_df.items():
            print_dataframe(stock_df, title=f"股票数据 {code} （{period}）K线数据",
                            show_footer=True, printer=CONSOLE.print)
            
        return {'dfs': stock_2_df}
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)



@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True,
            help='股票代码列表 (如: 688318.SH 或 688318)，支持半角逗号分隔')
@click.pass_context
def test(_ctx: click.Context,
    stocks: list[str],
):
    """获取合约基本信息（不校验证券代码，请自定带上市场代码）"""
    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True,
            help='股票代码列表 (如: 688318.SH 或 688318)，支持半角逗号分隔')
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma_lower, help='过滤返回的列名（大小写无关）')
@click.option('--by-db', '-db', 'is_by_db', is_flag=True, help='是否通过数据库查询')
@click.option('--date', '-d', 'date', type=DATETIME, help='在哪个日期查找数据库')
@click.pass_context
def get_instrument_detail(
    _ctx: click.Context,
    stocks: list[str],
    fields: list[str],
    is_by_db: bool,
    date: datetime,
):
    """获取合约基本信息"""
    if date:
        is_by_db = True

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console

    try:
        for full_code in stocks:
            if is_by_db:
                if not StockInstrumentDetail.is_inited():
                    StockInstrumentDetail.init_db(PG_URL)
                    click.echo("✅ PG数据库 初始化成功")
                detail = StockInstrumentDetail.get_latest_by_code(code=SecurityCode(full_code), when=date)  # type: StockInstrumentDetail | None
                detail = detail.to_dict() if detail else None
            else:
                detail = xtdata.get_instrument_detail(full_code)

            if detail:
                # 过滤并去掉空值字段
                if fields:
                    detail = {k:v for k,v in detail.items() if k.lower() in fields and v}
                else:
                    detail = {k:v for k,v in detail.items() if v}
                come_from = 'db' if is_by_db else 'xtdata'
                CONSOLE.print(f"从 {come_from} 中查得 {full_code} 的 InstrumentDetail: {detail}")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ---------------------------------------------------------------------------------------------
# 分类/板块成份股

@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('-s', '--sector', 'sectors', multiple=True, callback=split_comma, help='板块名称列表 (如: 电子信息)')
@click.option('-c', '--contains', 'contains', multiple=True, callback=split_comma, help='板块中包含的字串')
@click.option('-sc', '--stock-contains', 'stock_contains', multiple=True, callback=split_comma, help='个股（或交易标的）中包含的字串')
@click.option('--max-to-show', '-max', '-m', 'max_to_show', default=10, show_default=True, type=int, help='显示时的最大股票数量')
@click.option('--main-contract', '-mc', 'wanna_main_contract', type=int, help='只显示主力合约（期货/期权）为指定值的标的，-1 表示显示所有非主力合约')
@click.option('--category', '-cat', 'category', is_flag=True, help='多所有交易标的按照命名规则分类（如期货/期权/股票等），并显示分类统计结果')
@click.pass_context
def get_sector_list(_ctx: click.Context,
    sectors: list[str],
    contains: list[str], # 用于查找板块时过滤
    stock_contains: list[str], # 用于查找成份股时过滤
    max_to_show: int,
    wanna_main_contract: int,
    category: bool,
    is_save_memory: bool,
    group_index: int,
):
    """获取A股板块代码列表"""
    global CONSOLE
    if max_to_show <= 0:
        max_to_show = None

    try:
        if sectors:
            stocks_in_sectors = {} # type: Dict[str, list]  # 记录 每个板块对应的股票列表
            futures = set()
            future_options = set()
            for sector in sectors:
                stocks_in_sector = xtdata.get_stock_list_in_sector(sector_name=sector)

                stocks_in_sectors[sector] = stocks_in_sector
                CONSOLE.print(f"板块 {sector} 包含：", end='')
                CONSOLE.print(Pretty(stocks_in_sector, max_length=max_to_show) if max_to_show else list(stocks_in_sector))
                CONSOLE.print(f"共 {len(stocks_in_sector)} 只 交易标的")

                for stock in stocks_in_sector:
                    try:
                        sc = SecurityCode(stock)
                    except Exception as e:
                        CONSOLE.print(f"无法解析交易标的 {stock} 的代码，跳过期货/期权类型判断")
                        continue

                    if sc.is_futures:
                        futures.add(stock)
                    elif sc.is_futures_option:
                        future_options.add(stock)
            if futures:
                CONSOLE.print(f"在上述板块中发现期货交易标的 {len(futures)} 个：", end='')
                CONSOLE.print(Pretty(futures, max_length=max_to_show) if max_to_show else list(futures))
            if future_options:
                CONSOLE.print(f"在上述板块中发现期货期权交易标的 {len(future_options)} 个：", end='')
                CONSOLE.print(Pretty(future_options, max_length=max_to_show) if max_to_show else list(future_options))


            if stock_contains:
                stocks_in_filtered_sectors = {} # type: Dict[str, list]
                for sector in sectors:
                    for stock in stocks_in_sector:
                        for c in stock_contains:
                            if c in stock:
                                if sector not in stocks_in_filtered_sectors:
                                    stocks_in_filtered_sectors[sector] = []
                                stocks_in_filtered_sectors[sector].append(stock)
                                break
                    CONSOLE.print(f"板块 {sector} 中包含 {stock_contains} 的交易标的: ", end='')
                    CONSOLE.print(Pretty(stocks_in_filtered_sectors.get(sector, []), max_length=max_to_show))
                    CONSOLE.print(f"共 {len(stocks_in_filtered_sectors.get(sector, []))} 只 交易标的")

            if wanna_main_contract is not None:

                main_contract_2_stock = {} # type: Dict[str, set]
                is_trading_stocks = set()
                is_recent_stocks = set()

                for sector in sectors:
                    for stock in stocks_in_sector:
                        try:
                            detail = xtdata.get_instrument_detail(stock_code=stock)
                            if detail and isinstance(detail, dict):
                                main_contract = detail.get('MainContract', 0)
                                is_trading = detail.get('IsTrading', False)
                                is_recent = detail.get('IsRecent', False)
                                if main_contract:
                                    if str(main_contract) not in main_contract_2_stock:
                                        main_contract_2_stock[str(main_contract)] = set()
                                    main_contract_2_stock[str(main_contract)].add(stock)
                                if is_trading:
                                    is_trading_stocks.add(stock)
                                if is_recent:
                                    is_recent_stocks.add(stock)

                        except Exception as e:
                            CONSOLE.print(f"无法解析交易标的 {stock} 的代码，跳过主力合约判断")
                            continue

                if main_contract < 0:
                    CONSOLE.print(f"期货/期权 交易标的 MainContract 统计结果：{main_contract_2_stock}")
                else:
                    wanna_stocks = main_contract_2_stock.get(str(wanna_main_contract), set())
                    CONSOLE.print(f"主力合约 MainContract = {wanna_main_contract} 的标的有 {len(wanna_stocks)} ：{wanna_stocks}")
                CONSOLE.print(f"共 {len(main_contract_2_stock)} 个不同的 MainContract 值")
                CONSOLE.print(f"在上述板块中发现正在交易(IsTrading=True)的标的 {len(is_trading_stocks)} 个：", end='')
                CONSOLE.print(Pretty(is_trading_stocks, max_length=max_to_show) if max_to_show else list(is_trading_stocks))
                CONSOLE.print(f"在上述板块中发现 IsRecent=True 的标的 {len(is_recent_stocks)} 个：", end='')
                CONSOLE.print(Pretty(is_recent_stocks, max_length=max_to_show) if max_to_show else list(is_recent_stocks))

            if category:
                for sector in stocks_in_sectors.keys():
                    res = analyze_stock_symbols(sector=sector)
                    print_statistics(res, console=CONSOLE)

        else:
            # 不指定板块时获取全部板块列表并显示
            sectors = xtdata.get_sector_list()
            CONSOLE.print(f"{sectors}")

        sectors_filtered = []
        if contains:
            for sector in sectors:
                for c in contains:
                    if c in sector:
                        sectors_filtered.append(sector)
                        break

            CONSOLE.print(f"板块代码列表（过滤含有 {contains} ）: {sectors_filtered}\n{len(sectors_filtered)} / {len(sectors)} 个板块")

        if is_save_memory:
            stocks_to_saved = set()
            for sector in sectors_filtered or sectors: # 如果有过滤条件则用过滤后的板块列表，否则用全部板块列表
                stocks_in_sector = xtdata.get_stock_list_in_sector(sector_name=sector)
                if stocks_in_sector:
                    stocks_to_saved.update(stocks_in_sector)

            return {'stocks': stocks_to_saved}

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, default=STOCKS,
            help='股票代码列表 (如: 688318.SH 或 688318)，支持半角逗号分隔')
@click.option('--fields', '-f', multiple=True, callback=split_comma, help='返回字段列表')
@click.option('--start-time', '-st', 'start_time', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', 'end_time', type=DATETIME, default=datetime.now(), help='结束时间')
@click.option('--count', '-c', default=-1, type=int, help='获取数据条数 (-1 表示全部)')
@click.pass_context
def get_l2_quote(_ctx: click.Context,
    stocks: list[str],
    fields: list[str],
    start_time: datetime | None,
    end_time: datetime | None,
    count: int,
):
    """获取level2行情快照数据"""
    global CONSOLE
    
    start_time = start_time.strftime('%Y%m%d%H%M%S') if start_time else ''
    end_time = end_time.strftime('%Y%m%d%H%M%S') if end_time else ''
    
    print_locals(printer=CONSOLE.print)

    try:
        res = xtdata.get_l2_order(field_list=fields, stock_code=stocks, start_time=start_time, end_time=end_time, count=count)
        CONSOLE.print(f"get_l2_order: {res}")

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.pass_context
def _download_sector_data(_ctx: click.Context,
):
    """下载板块分类信息【未成功】"""
    global CONSOLE
    # res = xtdata.download_sector_data()
    # DEBUG: 展开 download_sector_data 内的内容并添加 callback 观察
    with ProgressManager.init([], CONSOLE, "下载板块分类信息") as pm:
        xtdata.download_history_data2([], (2009, 86400000), callback=pm.callback)
    # CONSOLE.print(f"返回: {res}")


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.pass_context
def _example(_ctx: click.Context,
    stocks: list[str]
):
    """"""
    # CONSOLE = _ctx.obj['console'] # type: Console
    try:
        for full_code in stock:
            # TODO:
            CONSOLE.print(f"{full_code} :", )
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ======================
# 初始化
# ======================
def init(_ctx: click.Context):
    global CFG, CONSOLE, PG_URL, CONFIG_PATH

    print_locals()

    _ctx.ensure_object(dict)
    _ctx.obj['config_path'] = CONFIG_PATH
    _ctx.obj['console'] = CONSOLE
    if not CFG:
        CFG = read_yaml_config(CONFIG_PATH)
    _ctx.obj['cfg'] = CFG

    pg_cfg = CFG.get('postgresql', {})
    PG_URL = generate_engine_url_str(**pg_cfg)

    try:
        xtdata.enable_hello = False
        tq.initialize(__file__)
        click.echo("✅ TQ 初始化成功")
        cache_stock_name_of_market()
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)
        raise # 初始化出问题必须退出


# ======================
# main（根据参数决定模式）
# ======================
if __name__ == '__main__':
    repl_cli_main(doc='xtquant数据工具', prompt='xtquant> ', on_init=init, find_caller_cmds=True, console=CONSOLE)
