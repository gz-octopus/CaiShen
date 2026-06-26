#!python
# -*- coding: utf-8 -*-
# author: DifossChen
# version: v1.0.1
# changes:
# - v0.1.1 (2026-05-07): 初始版本，验证和使用 TdxQuant 的接口
# - v0.1.2 (2026-06-20): 【修复】修改 get_market_data 的 fill_data 的默认值为 False。
# 在观察 get_market_data 返回的 DataFrame 后，发现 002160 这只股票的近5天数据和实际不符：
# 返回日k时间： 20260612, 20260615, 20260616, 20260617, 20260618
# 实际日K时间应该是：2026-06-05, 2026-06-08, 2026-06-16, 2026-06-17, 2026-06-18
# 最后发现，get_market_data 在 fill_data（默认True）时会导致停牌的股票也会有数据（与现实不符）
#

import click
from tdx_quant.tqcenter import tq
from datetime import datetime
from rich import print as pprint
from rich.console import Console
from rich.pretty import Pretty
from rich.style import Style
from datetime import datetime

import re
import json
import pandas as pd
import numpy as np
from collections import defaultdict

from difoss_stock_util.tdx_util import *
from difoss_stock_util.rich_util import *
from difoss_stock_util.click_util import *
from difoss_stock_util.color_log_util import *
from difoss_stock_util.security_util import *
from difoss_stock_util.util import print_locals
from difoss_stock_util.stock_util import calc_belong_trading_day, calc_count_of_trading_days, TradingInfo
from difoss_stock_util.db_util import *
from datetime import time as datetime_time
from difoss_stock_util.tdx_util.tdx_quant_data_dictionary import *
from difoss_stock_util.time_util import TimeUtils
from typing import Optional, Dict, List
from tdx_quant_util import *
from sqlalchemy import text
from sqlalchemy.orm import Session
from time import sleep

from cache_cmd import (STOCKS,
                       stocks_collector, df_collector,
                       memory_cache, data_frame,
                       get_stock_name, cache_stock_name, is_st)

# ---------------------------------------------------------------------------------------------
# Constants
ALL_PERIODS = ['1m', '5m', '15m', '30m', '1h', '1d', '1w', '1mon', '1q', '1y',
    'tick'  # DEBUG
]


# ---------------------------------------------------------------------------------------------
def _fix_fields(fields: list[str], prefix='FN') -> list[str]:
    res = []
    for f in fields:
        if f.isdigit():
            res.append(f'{prefix}{int(f)}')
        else:
            res.append(f)
    return res

def _get(dict_or_str, key='Code'):
    if isinstance(dict_or_str, dict):
        return dict_or_str.get(key, None)
    elif isinstance(dict_or_str, str):
        return dict_or_str


def _show_return_fields_meaning(fields_meaning: pd.DataFrame, return_fields: list[str] = None, printer=None):
    if not return_fields:
        print_dataframe(fields_meaning, title='全部字段意义', show_index=False, printer=printer)
        return

    if not printer:
        printer = pprint

    meaning_index = fields_meaning.index.to_list()

    valid_fields = []
    missing_fields = []
    for f in return_fields:
        if f in meaning_index:
            valid_fields.append(f)
        else:
            missing_fields.append(f)
    if missing_fields:
        printer(f"字典暂无解释的字段: {missing_fields}")

    if valid_fields:
        print_dataframe(fields_meaning.loc[valid_fields], title="字段意义",
                        printer=printer)


def _xg_multi_result_dict2df(mul_res: dict,
                            fill_stock_name: bool = False,
                            field_be_counted: str = 'OUTPUT1',
                            return_start_date: Optional[str] = None, return_end_date: Optional[str] = None
) -> pd.DataFrame:
    """转换批量选股结果（dict→DataFrame）"""
    # 步骤 1: 遍历字典，收集符合条件的数据
    # 使用一个临时字典来存储每个日期对应的非零股票代码列表
    daily_nonzero_stocks = defaultdict(list)

    for stock_code, data in mul_res.items():
        # 跳过 'ErrorId' 这样的元数据键
        if not isinstance(data, dict) or field_be_counted not in data:
            continue

        for item in data[field_be_counted]:
            date_str = item['Date']
            date_yyyymmdd_int = int(date_str)
            if return_start_date and date_yyyymmdd_int < int(return_start_date):
                continue
            if return_end_date and date_yyyymmdd_int > int(return_end_date):
                continue
            value = item['Value']

            # 如果 Value 等于 "1"，则将该股票代码加入到对应日期的列表中
            if value and value == "1":
                daily_nonzero_stocks[date_str].append(stock_code)

    # 步骤 2: 将收集到的数据转换为 pandas DataFrame
    # 准备 DataFrame 的行数据
    df_data = []
    for date, stocks_list in daily_nonzero_stocks.items():
        stocks_with_name = [f"{x}|{get_stock_name(x, '')}" for x in stocks_list]
        if fill_stock_name:
            # debug
            # D(stocks_with_name=stocks_with_name)
            df_data.append({'Date': date, 'Count': len(stocks_list), 'Stocks_Name': stocks_with_name})
        else:
            df_data.append({'Date': date, 'Count': len(stocks_list), 'Stocks': stocks_list})

    # 创建 DataFrame
    result_df = pd.DataFrame(df_data)

    # 步骤 3 (可选): 为了更好的展示效果，可以按日期排序
    if not result_df.empty:
        result_df.sort_values(by='Date', inplace=True)
        # 重置索引，使输出更整洁
        result_df.reset_index(drop=True, inplace=True)

    return result_df

def _zb_multi_result_to_dataframe(mul_res: dict, index=['stock_code', 'date'], convert_datetime=False):
    """
    将tdx_quant的mul_res结果转换为pandas DataFrame

    Parameters:
    -----------
    mul_res : dict
        tdx_quant返回的多股票多指标结果

    Returns:
    --------
    pd.DataFrame
        转换后的DataFrame，包含stock_code、date和所有指标列
    """
    # 检查是否有错误
    if mul_res.get('ErrorId') != '0':
        print(f"API返回错误: ErrorId={mul_res.get('ErrorId')}")
        return pd.DataFrame()

    # 准备数据列表
    rows = []

    # 遍历每个股票
    for stock_code, stock_data in mul_res.items():
        if stock_code == 'ErrorId':
            continue
        if not isinstance(stock_data, dict):
            continue

        # 过滤出包含实际数据的指标（列表元素为带 'Date' 和 'Value' 键的 dict）
        # 排除纯描述性指标（如 ["主买净额(万)"]）
        def _is_data_indicator(indicator_data):
            return (
                isinstance(indicator_data, list)
                and len(indicator_data) > 0
                and isinstance(indicator_data[0], dict)
                and 'Date' in indicator_data[0]
            )

        data_indicators = {
            k: v for k, v in stock_data.items()
            if _is_data_indicator(v)
        }

        if not data_indicators:
            continue

        # 首先收集所有日期（从任意一个数据指标获取）
        first_indicator = next(iter(data_indicators.values()))
        dates = [item['Date'] for item in first_indicator]

        # 为每个日期创建一行数据
        for date_idx, date in enumerate(dates):
            row = {
                'stock_code': stock_code,
                'date': date
            }

            # 遍历所有数据指标
            for indicator_name, indicator_data in data_indicators.items():
                # 确保索引有效
                if date_idx < len(indicator_data):
                    row[indicator_name] = indicator_data[date_idx]['Value']
                else:
                    row[indicator_name] = None

            rows.append(row)

    # 创建DataFrame
    df = pd.DataFrame(rows)

    # 将日期列转换为datetime类型（可选）
    if convert_datetime:
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

    # 设置索引（可选）
    if index:
        df.set_index(keys=index, inplace=True)

    return df

def _zb_multi_result_to_pivot(df, index='date', columns='stock_code', values=None):
    """
    将转换后的DataFrame转换为透视表格式

    Parameters:
    -----------
    df : pd.DataFrame
        _zb_multi_result_to_dataframe 返回的DataFrame
    index : str
        透视表的索引列
    columns : str
        透视表的列
    values : str or list
        要透视的值列，如果为None则对所有数值列进行透视

    Returns:
    --------
    dict or pd.DataFrame
        如果values为None，返回每个指标的透视表字典
        否则返回单个透视表
    """
    if values is None:
        # 获取所有指标列（排除stock_code和date）
        indicator_cols = [col for col in df.columns if col not in ['stock_code', 'date']]

        # 为每个指标创建透视表
        pivot_dfs = {}
        for indicator in indicator_cols:
            pivot_df = df.pivot_table(
                index=index,
                columns=columns,
                values=indicator,
                aggfunc='first'
            )
            pivot_dfs[indicator] = pivot_df

        return pivot_dfs
    else:
        # 返回单个指标的透视表
        return df.pivot_table(
            index=index,
            columns=columns,
            values=values,
            aggfunc='first'
        )

def _zb_multi_result_dataframe_stock_first(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    将长格式的DataFrame转换为以股票为第一层，日期为第二层的DataFrame字典

    Parameters:
    -----------
    df : pd.DataFrame
        _zb_multi_result_to_dataframe 转换出来的长格式DataFrame
        必须包含 'stock_code' 和 'date' 列

    Returns:
    --------
    dict
        键为股票代码，值为该股票的DataFrame，行索引为date，列名为指标名称
    """
    if df.empty:
        return {}

    # 获取所有指标列（排除stock_code和date）
    indicator_cols = [col for col in df.columns if col not in ['stock_code', 'date']]

    # 按股票代码分组
    stock_dfs = {}

    for stock_code in df['stock_code'].unique():
        # 筛选该股票的数据
        stock_data = df[df['stock_code'] == stock_code].copy()

        # 设置日期为索引
        stock_data.set_index('date', inplace=True)

        # 只保留指标列
        stock_data = stock_data[indicator_cols]

        # 按日期排序
        stock_data.sort_index(inplace=True)

        stock_dfs[stock_code] = stock_data

    return stock_dfs


def _trans_xg_data_to_date2stocks(data: dict, dates: list[str],
                                field_be_counted: str = 'OUTPUT1',
                                is_with_name: bool = False) -> pd.DataFrame:
    # 1. 构造 DataFrame：直接使用构造函数，避免循环 append
    # 这样生成的 df 列为股票代码，索引为日期
    columns = {}
    skipped = []
    for code, val in data.items():
        values = val.get(field_be_counted)
        if values is None:
            columns[code] = [None] * len(dates)
        elif len(values) != len(dates):
            skipped.append(code)
            W(f"股票 {code} 的数据长度 ({len(values)}) 与交易日数量 ({len(dates)}) 不匹配，已跳过")
        else:
            columns[code] = values

    if skipped:
        W(f"共跳过 {len(skipped)} 只数据长度不匹配的股票: {skipped}")

    df = pd.DataFrame(columns, index=pd.to_datetime(dates))

    # 2. 将数据转换为数值，并将非 1 的值（即 '0' 或 None）统一处理为 0
    # 这样方便后续计算 count
    df = df.apply(pd.to_numeric, errors='coerce').fillna(0)

    # 3. 统计与生成结果
    # 计算每一行（日期）中值为 1 的股票列表
    def get_stocks_info(row):
        codes = row.index[row == 1].tolist()
        if is_with_name:
            names = [get_stock_name(code) for code in codes]
            return codes, names
        return codes, None

    # 计算基础统计
    counts = df.sum(axis=1).astype(int)

    # 提取 info
    info = df.apply(get_stocks_info, axis=1)

    # 3. 构造最终 DataFrame
    result_data = {
        'date': df.index,
        'count': counts,
        'stocks': [x[0] for x in info]
    }

    if is_with_name:
        result_data['stocks with name'] = [
            [f"{c}|{n}" for c, n in zip(codes, names)] if names else codes
            for codes, names in info
        ]

    result_df = pd.DataFrame(result_data).reset_index(drop=True)

    return result_df


def _trans_data_2_stocks_pandas(df: pd.DataFrame) -> Dict[str, list]:
    # 转换为字典
    date_to_stocks = {}
    for date in df.columns:
        # 找出该日期值为'1'的股票
        stocks_with_one = df[df[date] == 1].index.tolist()
        if stocks_with_one:
            date_to_stocks[date] = stocks_with_one

    return date_to_stocks

# ---------------------------------------------------------------------------------------------
# 刷新功能
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.pass_context
def refresh_cache(_ctx: click.Context):
    """刷新行情缓存
    刷新后5分钟内取最新report和k线数据不会触发刷新
    """
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        result = tq.refresh_cache()
        CONSOLE.print(f"✅ 缓存刷新成功, result: {result}")

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--period', '-p', default='1d', type=click.Choice(ALL_PERIODS), show_default=True, help='K线周期')
@click.pass_context
def refresh_kline(_ctx: click.Context, stocks: list[str], period: str):
    """刷新K线缓存
    目前仅支持1m 5m 1d三种类型数据 不建议一次更新太多，会堵塞策略和客户端
    """
    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.refresh_kline(stock_list=stocks, period=period)
        CONSOLE.print(res)
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--time', '-t', 'time_list', multiple=True, callback=split_comma_datetime, help='')
@click.option('--data', '-d', 'data_list', multiple=True, callback=split_comma, help='数据列表（每个字段以“|”分隔）')
@click.pass_context
def send_bt_data(_ctx: click.Context,
                 stocks: list[str],
                 time_list: list[datetime],
                 data_list: list[str],
                 ):
    """往客户端发送指定股票的回测数据"""
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            bt_data = tq.send_bt_data(stock_code=full_code,
                                    time_list = [x.strftime('%Y%m%d%H%M%S') for x in time_list],
                                    data_list=[d.split('|') for d in data_list],
                                    count=len(data_list)),
            
            CONSOLE.print(f"发送 {full_code} 的回测数据，返回: {bt_data}")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


def _categorize_securities(data: list[dict]) -> pd.DataFrame:
    processed_data = []

    for item in data:
        code = item['Code']
        s_code = SecurityCode(code)
        sec_type = s_code.security_type.chinese_name if s_code.security_type else "Unknown"

        processed_data.append({
            'code': f"{code}|{item['Name']}",
            'type': sec_type
        })

    # 转换为 DataFrame
    df = pd.DataFrame(processed_data)

    # 按 type 归类：聚合 code 和计算数量
    result_df = df.groupby('type').agg(
        count=('code', 'count'),
        codes=('code', list)
    ).reset_index()

    return result_df


@command_with_abbrev(abbrev='gmsi', context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--key-word', '-k', '-s', 'key_word', help='关键词')
@click.pass_context
def get_match_stkinfo(_ctx: click.Context, key_word: str):
    """检索证券信息"""
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_match_stkinfo(key_word)
        if not res:
            CONSOLE.print(f'关键字 [yellow]{key_word}[/yellow]，查无数据')
            return
        display_df = _categorize_securities(res)
        print_dataframe(display_df, title=f'含有 [yellow]{key_word}[/yellow] 的证券信息')
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# todo:
def get_trackzs_etf_info():
    pass

# ---------------------------------------------------------------------------------------------
# 行情类信息
@click.command(short_help="获取K线数据", context_settings={'help_option_names': ['-?', '--help', '-h']})
@df_collector
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True,
              default=STOCKS,
              help='股票代码列表 (如: 688318.SH)')
@click.option('--start-time', '-st', 'start_time', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', 'end_time', type=DATETIME, default=datetime.now(), help='结束时间')
@click.option('--period', '-p', default='1d', help='K线周期 (1d/1w/1m/5m/15m/30m/60m等)',
              type=click.Choice(ALL_PERIODS))
@click.option('--dividend-type', '-dt', default='front', type=click.Choice(['none', 'front', 'back']), help='复权类型')
@click.option('--fields', '-f', multiple=True, callback=split_comma, help='返回字段列表 (如: Open, Close)')
@click.option('--count', '-c', default=-1, type=int, help='获取数据条数 (-1 表示全部)【注：一次性最多获取24000条，要获取完整分钟线需要多次分批获取】')
@click.option('--fill-data/--no-fill-data', '-fd/-no-fd', 'fill_data', help='是否填充缺失数据')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.option('--save-db/--no-save-db', '-sdb', 'is_save_db', is_flag=True, help='是否保存到数据库')
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
                    verbose: bool,
                    is_save_db: bool,
                    is_save_df: bool,
                    **kwargs, # 这样一来，就不用手动添加 df_collector 的变量了。
):
    """获取K线数据"""
    start_time = start_time.strftime('%Y%m%d%H%M%S') if start_time else None
    end_time = end_time.strftime('%Y%m%d%H%M%S') if end_time else None

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    CFG = _ctx.obj['cfg'] # type: dict
    db_url = CFG.get('db_url')

    try:
        dict_df = tq.get_market_data(
            field_list=fields,
            stock_list=stocks,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            period=period,
            fill_data=fill_data
        ) # type: Dict[str, pd.DataFrame]

        if verbose:
            CONSOLE.print(f"{dict(stock_list=stocks, typeOfres=type(dict_df), res=dict_df)}")

        if dict_df and len(dict_df) > 0:
            if period == 'tick':
                CONSOLE.print(f"df: {dict_df}")
                return

            # DEBUG:
            # for k, v in dict_df.items():
            #     print_dataframe(v, title=f'Key: {k}')

            stock_2_df = transform_field_to_stock_fast(dict_df)

            for code, stock_df in stock_2_df.items():

                if not is_save_df:
                    # 保存到 df 中，就不打印了
                    print_dataframe(stock_df, title=f"股票数据 {code} （{period}）K线数据",
                                    show_footer=True, printer=CONSOLE.print)
                if is_save_db:
                    save_to_db(stock_df, code, period, CONSOLE, db_url)

            return {'dfs': stock_2_df}

        else:
            CONSOLE.print("[red]❎ 返回空数据[/red]")

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)



def save_to_db(df: pd.DataFrame, code: str, period: str,
               console: Console, db_url: str):
    """保存数据到数据库"""
    from difoss_stock_util.metric_data.history_data_1d import HistoryData1D
    # from difoss_stock_util.metric_data.history_data_1m import HistoryData1M

    HistoryData1D.init_db(db_url)

    s_code = SecurityCode(code)

    if df.empty:
        return

    if period == '1d':
        with HistoryData1D.get_session() as session:
            execute_batch_insert(df, s_code.short_code, s_code.market_code, session)
            HistoryData1D.batch_insert()
    else:
        console.print(f"暂不支持保存周期为 {period} 的数据到数据库")

    # elif period == '1m':
    #     HistoryData1M.insert_from_dataframe(df, code, 'SH', replace_existing=True)


def execute_batch_insert(df: pd.DataFrame,
                        exchange_id: str,
                        instrument_id: str,
                        db_session: Session,
                        batch_size: int = 1000):
    """
    使用原生SQL批量插入（最高性能）
    """
    # 1. 定义 SQL 语句 (请根据您的数据库表结构调整字段名)
    # 假设表名为 market_data
    sql = text("""
        INSERT INTO market_data (ExchangeID, InstrumentID, trade_date, open, close, high, low, volume, amount, suspend_flag)
        VALUES (:ExchangeID, :InstrumentID, :trade_date, :open, :close, :high, :low, :volume, :amount, :suspend_flag)
    """)

    # 准备数据
    records = []
    for idx, row in df.iterrows():
        # 获取日期（可能在索引或列中）
        if isinstance(idx, pd.Timestamp):
            trade_date = idx.date()
        elif 'INDEX' in row:
            trade_date = pd.to_datetime(row['INDEX']).date()
        else:
            trade_date = pd.to_datetime(row.name).date()

        records.append({
            'ExchangeID': exchange_id,
            'InstrumentID': instrument_id,
            'trade_date': trade_date,
            'open': row.get('Open', None),
            'close': row.get('Close', None),
            'high': row.get('High', None),
            'low': row.get('Low', None),
            'volume': row.get('Volume', None),
            'amount': row.get('Amount', None),
            'suspend_flag': False
        })

    # 2. 执行批量插入
    try:
        # 使用 bulk_insert_mappings 性能更高，或者使用 session.execute
        # 下面是通用的 SQLAlchemy 执行方式
        for i in range(0, len(records), batch_size):
            batch = records[i:i+batch_size]
            db_session.execute(sql, batch)

        db_session.commit() # 在循环外 commit，性能更优
        print(f"成功插入 {len(records)} 条记录到数据库")
        return len(records)

    except Exception as e:
        db_session.rollback()
        print(f"批量插入失败: {e}")
        raise


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma, required=True, help='股票代码列表 (如: 688318.SH)')
@click.pass_context
def get_market_snapshot(_ctx: click.Context,
    stocks: list[str]
):
    """获取市场快照数据
    调用会触发客户端刷新数据，耗时过长请耐心等待
    总成交额为万位，其他无特殊说明均为个位
    """
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        for stock in stocks:
            code = SecurityCode(stock.upper())
            market_snapshot = tq.get_market_snapshot(stock_code = code.full_code)
            CONSOLE.print(f"{code.full_code} 的市场快照数据:", market_snapshot)
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名 (如: J_zgb——总股本；ActiveCapital——流通股本)')
@click.pass_context
def get_stock_info(_ctx: click.Context,
    stocks: list[str],
    fields: list[str],
):
    """获取基础财务数据（不需要下载专业财务数据）
    股本 资产 负债 利润 现金流量等数据均为万位
    """
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        return_fields = []
        for full_code in stocks:
            fdc = tq.get_stock_info(stock_code=full_code, field_list=fields)
            CONSOLE.print(f"{full_code} 基础财务数据:", fdc)

            if (not return_fields) and fdc is not None and isinstance(fdc, dict):
                return_fields = list(fdc.keys())

        _show_return_fields_meaning(STOCK_INFO_DATAFRAME, return_fields)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 688318.SH)')
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名（可以是中文或英文，默认支持模糊匹配）')
@click.option('--translate', '-t', 'translate', is_flag=True, help='是否翻译字段含义（仅限于已知字段）')
@click.option('--list-field', '-l', 'list_field', is_flag=True, help='仅列出可用字段')
@click.option('--join-one-table', '-j', 'join_one_table', is_flag=True, help='是否连接同一表格输出')
@click.pass_context
def get_more_info(_ctx: click.Context,
    stocks: list[str],
    fields: list[str],
    translate: bool,
    list_field: bool,
    join_one_table: bool,
):
    """获取股票更多信息"""
    CONSOLE = _ctx.obj['console'] # type: Console

    # 如果含有中文，则在说明中查找，否则在 key 中查找
    matched_fields = []
    if fields: # 如果指定字段，采用模糊匹配
        for f in fields:
            _en_key = []
            if has_chinese(f):
                _en_key = [k for k, v in GMI_KEY_2_CN.items() if f in v]
            else:
                _en_key = [k for k in GMI_KEY_2_CN.keys() if f in k]

            if _en_key:
                matched_fields.extend(_en_key)

        if not matched_fields:
            CONSOLE.print(f"没有找到匹配的字段，无法列出字段意义")
            return

    if list_field:
        if matched_fields:
            _show_return_fields_meaning(GMI_INFO_DATAFRAME, matched_fields, printer=CONSOLE.print)

        else:
            _show_return_fields_meaning(GMI_INFO_DATAFRAME, printer=CONSOLE.print)

        return

    try:
        return_fields = []

        stocks_info_list = [] # type: List[dict]

        for full_code in stocks:
            res = tq.get_more_info(full_code, field_list=matched_fields)

            if translate:
                # 翻译后，不会再显示字段意义表，因为 key 已经直接是中文了
                res = {GMI_KEY_2_CN.get(k, k): v for k, v in res.items()}
            else:
                # 记录返回的 key
                if (not return_fields) and res is not None and isinstance(res, dict):
                    return_fields = list(res.keys())

            if join_one_table:
                stocks_info_list.append(res)
            else:
                CONSOLE.print(f"get_more_info({full_code} {get_stock_name(full_code)}): {res}")

        if join_one_table and stocks_info_list:
            df = pd.DataFrame(stocks_info_list, index=stocks)
            print_dataframe(df, title="股票更多信息", show_footer=True, printer=CONSOLE.print)

        if return_fields:
            _show_return_fields_meaning(GMI_INFO_DATAFRAME, return_fields)
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
              default=STOCKS, help='股票代码列表 (如: 688318.SH)')
@click.option('--start-time', '-st', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', type=DATETIME, help='结束时间')
@click.pass_context
def get_divide_factors(_ctx: click.Context,
    stocks: list[str],
    start_time: datetime | None,
    end_time: datetime | None,
):
    """获取分红送配数据"""
    # 参数预处理: get_divid_factors() 不允许 start_time, end_time 为 None
    start_time = start_time.strftime("%Y%m%d") if start_time else ''
    end_time = end_time.strftime("%Y%m%d") if end_time else ''

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            df = tq.get_divid_factors(stock_code=full_code, start_time=start_time, end_time=end_time)
            print_dataframe(df, title=f"{full_code} 分红配送数据",
                            show_footer=True, printer=CONSOLE.print)
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)



@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--date', '-d', 'dates', multiple=True, callback=split_comma, default=[], help='日期（数组以逗号“,”分隔）')
@click.pass_context
def get_gb_info(_ctx: click.Context,
    stocks: list[str],
    dates: list[str],
):
    """获取每天的股本数据"""
    date_list = []
    if not dates:
        date_list = [datetime.now().strftime('%Y%m%d')]
    for _date_str in dates:
        _date = TimeUtils.str_to_datetime(_date_str)
        if _date:
            date_list.append(_date.strftime('%Y%m%d'))

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        count = len(date_list)
        if count:
            for full_code in stocks:
                res = tq.get_gb_info(stock_code=full_code, date_list=date_list, count=count)
                CONSOLE.print(f"get_gb_info({full_code}): {res}")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)



@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='可转债代码列表 (如: 123265.SZ)')
@click.pass_context
def get_cb_info(_ctx: click.Context,
    stocks: list[str]
):
    """获取可转债基础数据"""
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        for stock in stocks:
            code = SecurityCode(stock.upper())
            cb_info = tq.get_cb_info(stock_code = code.full_code)
            CONSOLE.print(f"{code.full_code} {code.security_type.value} 的可转债基础数据:", cb_info)
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--type', '-t', 'ipo_type', type=click.IntRange(0, 2), default=0, help='IPO类型 (0:新股, 1:新发债, 2:所有)')
@click.option('--date', '-d', 'ipo_date', type=click.IntRange(0, 1), default=0, help='IPO日期范围 (0:今天, 1:今天及以后)')
@click.pass_context
def get_ipo_info(_ctx: click.Context,
    ipo_type: int,
    ipo_date: int,
):
    """获取新股申购信息（不包含历史）"""

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        ipo_info = tq.get_ipo_info(ipo_type, ipo_date)

        ipo_type_tip = '所有新股申购信息' if (ipo_type == 0) else '所有新发债信息'
        ipo_date_tip = '今天' if (ipo_date == 0) else '今天及以后'
        CONSOLE.print(f"{ipo_date_tip}{ipo_type_tip}:", ipo_info)
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ---------------------------------------------------------------------------------------------
# 财务类数据

@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名 (如: announce_time:公告日期；FN238/238:总股本[纯数值默认自动添加 FN 前缀])')
@click.option('--start-time', '-st', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', type=DATETIME, help='结束时间')
@click.option('--report-type', '-rt', 'report_type', default='report_time', type=click.Choice(['report_time', 'announce_time']), help='筛选报告类型（report_time：按截止日期；announce_time：公告日期）')
@click.pass_context
def get_financial_data(_ctx: click.Context,
    stocks: list[str],
    fields: list[str],
    start_time: datetime | None,
    end_time: datetime | None,
    report_type: str,
):
    """获取专业财务数据（需要先在客户端下载）"""
    field_list = _fix_fields(fields, 'FN')
    start_time = start_time.strftime('%Y%m%d%H%M%S') if start_time else None
    end_time = end_time.strftime('%Y%m%d%H%M%S') if end_time else None

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        fn_data = tq.get_financial_data(
            stock_list=stocks,
            field_list=field_list,
            start_time=start_time,
            end_time=end_time,
            report_type=report_type
        )

        return_fields = []
        for full_code, df in fn_data.items():
            if isinstance(df, pd.DataFrame):
                if not return_fields:
                    return_fields = df.columns.to_list()
                print_dataframe(df, title=f"{full_code} 专业财务数据",
                                printer=CONSOLE.print)

        _show_return_fields_meaning(FINANCIAL_DATAFRAME, return_fields)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名 (如: announce_time:公告日期；FN238/238:总股本[纯数值默认自动添加 FN 前缀])')
@click.option('--start-time', '-st', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', type=DATETIME, help='结束时间')
@click.pass_context
def get_gpjy_value(_ctx: click.Context,
    stocks: list[str],
    fields: list[str],
    start_time: datetime | None,
    end_time: datetime | None,
):
    """获取股票交易数据"""
    field_list = _fix_fields(fields, 'GP')
    start_time = start_time.strftime('%Y%m%d%H%M%S') if start_time else None
    end_time = end_time.strftime('%Y%m%d%H%M%S') if end_time else None

    print_locals()

    # return

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_gpjy_value(stocks, field_list, start_time, end_time)
        CONSOLE.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(GPJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名 (如: announce_time:公告日期；FN238/238:总股本[纯数值默认自动添加 FN 前缀])')
@click.option('--year', '-y', 'year', default=0, help='指定年份')
@click.option('--mmdd', '-md', 'mmdd', default=0, help='指定月日')
@click.pass_context
def get_gpjy_value_by_date(_ctx: click.Context,
    stocks: list[str],
    fields: list[str],
    year: int,
    mmdd: int,
):
    """获取指定日期股票交易数据"""
    field_list = _fix_fields(fields, 'GP')

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_gpjy_value_by_date(stocks, field_list, year, mmdd)
        CONSOLE.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(GPJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名 (如: announce_time:公告日期；FN238/238:总股本[纯数值默认自动添加 FN 前缀])')
@click.option('--start-time', '-st', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', type=DATETIME, help='结束时间')
@click.pass_context
def get_bkjy_value(_ctx: click.Context,
    stocks: list[str],
    fields: list[str],
    start_time: datetime | None,
    end_time: datetime | None,
):
    """获取板块交易数据"""
    field_list = _fix_fields(fields, 'BK')
    start_time = start_time.strftime('%Y%m%d%H%M%S') if start_time else None
    end_time = end_time.strftime('%Y%m%d%H%M%S') if end_time else None

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_bkjy_value(stocks, field_list, start_time, end_time)
        CONSOLE.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(BKJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名 (如: announce_time:公告日期；FN238/238:总股本[纯数值默认自动添加 FN 前缀])')
@click.option('--year', '-y', 'year', default=0, help='指定年份')
@click.option('--mmdd', '-md', 'mmdd', default=0, help='指定月日')
@click.pass_context
def get_bkjy_value_by_date(_ctx: click.Context,
    stocks: list[str],
    fields: list[str],
    year: int,
    mmdd: int,
):
    """获取指定日期板块交易数据"""
    field_list = _fix_fields(fields, 'BK')

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_bkjy_value_by_date(stocks, field_list, year, mmdd)
        CONSOLE.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(BKJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名 (如: SC1/1: 融资融券 沪深京融资余额(万元) 沪深京融券余额(万元)[纯数值默认自动添加 SC 前缀])')
@click.option('--start-time', '-st', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', type=DATETIME, help='结束时间')
@click.pass_context
def get_scjy_value(_ctx: click.Context,
    fields: list[str],
    start_time: datetime | None,
    end_time: datetime | None,
):
    """获取市场交易数据"""
    field_list = _fix_fields(fields, 'SC')

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_scjy_value(field_list, start_time, end_time)
        CONSOLE.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0 and isinstance(res, dict):
            return_fields = list(res.keys())

        _show_return_fields_meaning(SCJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名 (如: SC1/1: 融资融券 沪深京融资余额(万元) 沪深京融券余额(万元)[纯数值默认自动添加 SC 前缀])')
@click.option('--year', '-y', 'year', default=0, help='指定年份')
@click.option('--mmdd', '-md', 'mmdd', default=0, help='指定月日')
@click.pass_context
def get_scjy_value_by_date(_ctx: click.Context,
    fields: list[str],
    year: int,
    mmdd: int,
):
    """获取指定日期市场交易数据"""
    field_list = _fix_fields(fields, 'SC')

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_scjy_value_by_date(field_list, year, mmdd)
        CONSOLE.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0 and isinstance(res, dict):
            return_fields = list(res.keys())

        _show_return_fields_meaning(SCJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--field', '-f', 'fields', multiple=True, callback=split_comma, help='返回列名 (如: GO1/1:发行价(元)[纯数值默认自动添加 GO 前缀])')
@click.pass_context
def get_gp_one_data(_ctx: click.Context,
    stocks: list[str],
    fields: list[str],
):
    """获取股票的单个财务数据"""
    field_list = _fix_fields(fields, 'GO')

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_gp_one_data(stocks, field_list) # type: dict[dict]
        CONSOLE.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(GP_ONE_DATA_DATAFRAME, return_fields)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)

# ---------------------------------------------------------------------------------------------
# 分类/板块成份股

        import pandas as pd

# ---------------------------------------------------------------------------------------------
# 分类/板块成份股
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('-c', '--contains', 'contains', multiple=True, callback=split_comma, help='包含的字串')
@click.option('-v', '--verbose', 'is_verbose', is_flag=True, help='是否打印详细信息')
@click.pass_context
def get_sector_list(_ctx: click.Context,
    contains: list[str],
    is_verbose: bool,
    is_save_memory: bool,
    group_index: int,
):
    """获取A股板块代码列表（通达信板块、概念、行业等88开头的板块）"""
    CONSOLE = _ctx.obj['console']
    # 管道模式：当本命令处于管道非末段（左侧/中间），后面有下游命令时，
    # 即使没有 -sm 也应该遍历板块获取成份股并返回，供下一段消费
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    try:
        # 获取数据并转换为 DataFrame
        sectors = tq.get_sector_list(list_type=1)  # 始终获取详细信息以供后续过滤
        df = pd.DataFrame(sectors)

        if contains:
            # 使用 pandas 向量化模糊匹配：构建一个布尔掩码
            # 逻辑：只要 Name 列中包含 contains 列表中的任意一个字符串即匹配
            pattern = '|'.join(contains)
            mask = df['Name'].str.contains(pattern, na=False)
            df_filtered = df[mask].copy()

            print_dataframe(df_filtered, title=f'含有 {contains} 的板块（{len(df_filtered)} / {len(df)}）', printer=CONSOLE.print)

            if is_save_memory or is_verbose or _is_pipe_producer:
                stocks_in_filtered_sectors = set()

                # 直接遍历过滤后的 DataFrame
                for _, row in df_filtered.iterrows():
                    sector_code = row['Code']
                    res = tq.get_stock_list_in_sector(block_code=sector_code, block_type=0, list_type=1)

                    if is_verbose:
                        CONSOLE.print(f"板块 [yellow]{sector_code}[/yellow] ({row['Name']}) 中含有 {len(res)} 只个股：", end='')
                        CONSOLE.print([f"{r.get('Code')}|{r.get('Name')}" for r in res if isinstance(r, dict)])

                    if (is_save_memory or _is_pipe_producer) and res:
                        stocks_in_filtered_sectors.update([_get(x) for x in res if x])

                if is_save_memory or _is_pipe_producer:
                    return {'stocks': stocks_in_filtered_sectors}

        else:
            print_dataframe(df, title='板块列表（全量）', print=CONSOLE.print)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('--block-code', '-b', 'block_code', help='板块代码（88XXXX.SH）或板块名称')
# 2026-03-20: 更新函数：get_stock_list_in_sector新增block_type=2，可取对应期货代码
@click.option('--futures-code', '-f', 'futures_code', help='期货板块名称（如: 沪铜、铁矿石等）')
@click.option('--user-block-abbrev', '-u', 'user_block_abbrev', help='客户端中预先定义好的板块【简称】')
@click.option('--list-type', '-t', 'list_type', default=1, help='返回数据类型（0：只返回代码，1：返回代码和名称）')
@click.option('--max-to-show', '-max', 'max_to_show', default=20, show_default=True, type=int, help='最多显示多少只股票')
@click.pass_context
def get_stock_list_in_sector(
    _ctx: click.Context,
    block_code: str,
    futures_code: str,
    user_block_abbrev: str,
    list_type: int,
    is_save_memory: bool,
    group_index: int,
    max_to_show: int,
    **kwargs,
):
    """根据板块代码（SecurityType: TDX_INDEX）获取其成份股列表
    注：block_code 从 get_sector_list 获取
    """

    block_name = None

    if block_code:
        block_type = 0

        _block_vec = block_code.split('.')
        if _block_vec[0].isdigit and len(_block_vec[0]) == 6:
            _code = SecurityCode(block_code)
            if _code.security_type != SecurityType.TDX_INDEX:
                E(f"参数 block_code 不是通达信板块代码", block_code=block_code)
                return
            block_name = _code.full_code
        else:
            block_name = block_code
    elif user_block_abbrev:
        block_type = 1
        block_name = user_block_abbrev
    elif futures_code:
        block_type = 2
        block_name = futures_code
    else:
        E('参数 -b 或 -cb 必须有一个带值')
        return

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    try:
        stocks_result = set()
        res = tq.get_stock_list_in_sector(block_code=block_name,
                                        block_type=block_type,
                                        list_type=list_type)
        CONSOLE.print(f"板块 [yellow]{block_name}[/yellow] 中含有 {len(res)} 只个股：", end='')
        CONSOLE.print(Pretty(res, max_length=max_to_show) if (res and max_to_show > 0) else res)

        if is_save_memory or _is_pipe_producer:
            if res and isinstance(res, list):
                stocks_result.update(set([_get(x) for x in res if x]))

            return {'stocks': stocks_result}

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


_MARKET_2_NAME = {
    '0': '自选股',
    '1': '持仓股',
    '5': '所有A股',
    '6': '上证指数成份股',
    '7': '上证主板',
    '8': '深证主板',
    '9': '重点指数',
    '10': '所有板块指数',
    '11': '缺省行业板块',
    '12': '概念板块',
    '13': '风格板块',
    '14': '地区板块',
    '15': '缺省行业分类+概念板块',
    '16': '研究行业一级',
    '17': '研究行业二级',
    '18': '研究行业三级',
    '21': '含H股',
    '22': '含可转债',
    '23': '沪深300',
    '24': '中证500',
    '25': '中证1000',
    '26': '国证2000',
    '27': '中证2000',
    '28': '中证A500',
    '30': 'REITs',
    '31': 'ETF基金',
    '32': '可转债',
    '33': 'LOF基金',
    '34': '所有可交易基金',
    '35': '所有沪深基金',
    '36': 'T+0基金',
    '49': '金融类企业',
    '50': '沪深A股',
    '51': '创业板',
    '52': '科创板',
    '53': '北交所',
    '101': '国内期货',
    '102' : '港股',
    '103' : '美股',
    '91': 'ETF追踪的指数',
    '92': '国内期货主力合约',
}

_MARKET_NAME_DF = pd.DataFrame(
    [(code, name) for code, name in _MARKET_2_NAME.items()],
    columns=['市场代码', '市场名称']
)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('--market', '-m', 'markets', multiple=True, callback=split_comma, help='市场代码 或 市场名称（可使用 -l/-a 查询）')
@click.option('--market-name-contain', '-mc', 'market_name_contains', multiple=True, callback=split_comma, help='列出含有指定字符的市场名称（默认为所有市场）以及对应的市场代码')
@click.option('--stock-name-contain', '-sc', 'stock_name_contains', multiple=True, callback=split_comma, help='列出含有指定字符的股票名称（默认为所有股票）')
@click.option('--list-all', '-a', '-l', 'list_all', is_flag=True, help='列出所有市场以及对应的数值')
@click.option('--list-type', '-t', 'list_type', default=1, show_default=True, help='返回数据类型（0：只返回代码，1：返回代码和名称）')
@click.option('--without-st', '-nst', 'without_st', is_flag=True, help='排除ST')
@click.option('--max-to-show', '-max', 'max_to_show', default=20, show_default=True, type=int, help='最多显示多少只股票')
@click.pass_context
def get_stocks(_ctx: click.Context,
    markets: list[str],
    market_name_contains: list[str],
    stock_name_contains: list[str],
    list_all: bool,
    list_type: int,
    without_st: bool,
    max_to_show: int,
    is_save_memory: bool,
    group_index: int,
):
    """获取系统分类成份股（通过指定 市场代码 或 市场名称）"""
    print_locals()
    CONSOLE = _ctx.obj['console'] # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    try:
        if not (markets or market_name_contains) or list_all:
            print_dataframe(_MARKET_NAME_DF, title="市场代码-名称对应表", printer=CONSOLE.print)
            return

        if market_name_contains:
            df_filtered = check_text_in_column(_MARKET_NAME_DF, '市场名称', market_name_contains)
            print_dataframe(df_filtered, title=f"含有{market_name_contains}的市场", printer=CONSOLE.print)
            return

        if markets:
            stocks_result = set()

            for market in markets:
                if market.isdigit(): # 兼容市场代码
                    market_name = _MARKET_2_NAME.get(market)
                else:  # 兼容市场名称
                    market_name = market
                if market_name:
                    res = tq.get_stock_list(market=market, list_type=(1 if (without_st or stock_name_contains) else list_type))
                    if res and len(res) > 0:
                        old_len = len(res)

                        # 补充股票（或期货）名称到缓存（如果返回结果包含名称的话）
                        if isinstance(res[0], dict):
                            cache_stock_name({ x.get('Code'): x.get('Name') for x in res })

                        if without_st:
                            res = [x for x in res if 'ST' not in x.get('Name').upper()]

                        if stock_name_contains:
                            res = [x for x in res if any(contain_str in x.get('Name', '') for contain_str in stock_name_contains)]

                            CONSOLE.print(f"市场【代码：{market} 名称：{market_name}】 共 {old_len} 只个股，筛选后剩余 {len(res)} 只：", end='')
                        else:
                            CONSOLE.print(f"市场【代码：{market} 名称：{market_name}】 共 {len(res)} 只个股：", end='')

                        CONSOLE.print(Pretty(res, max_length=max_to_show) if max_to_show > 0 else res)

                        if (is_save_memory or _is_pipe_producer) and isinstance(res, list):
                            stocks_result.update([_get(x) for x in res if x])

            if is_save_memory or _is_pipe_producer:
                I(stocks_result_LEN=len(stocks_result))
                return {'stocks': stocks_result}  # 返回就会被 stocks_collector 添加到 cache_cmd.STOCKS 中

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# 衍生快捷命令 --------------

# ---------------------------------------------------------------------------------------------


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--account', '-a', 'account', required=True, help='资金账号')
@click.option('--stock', '-s', 'stock', required=True, help='股票代码(如: 688318.SH)')
@click.option('--order-type', '-t', 'order_type', type=int, required=True, help='委托类型')
@click.option('--order-volume', '-v', 'order_volume', type=int, required=True, help="委托数量，股票以'股'为单位，债券以'张'为单位")
@click.option('--price-type', '-pt', 'price_type', type=int, required=True, help='报价类型')
@click.option('--price', '-p', 'price', type=float, required=True, help='委托价格')
@click.option('--strategy-name', '-sn', 'strategy_name', required=True, help='策略名称')
@click.option('--order-remark', '-or', 'order_remark', default="", help='委托备注')
@click.pass_context
def order_stock(_ctx: click.Context,
    account: str,
    stock: str,
    order_type: int,
    order_volume: int,
    price_type: int,
    price: float,
    strategy_name: str,
    order_remark: str = "",
):
    """下单接口【暂无实际功能】"""
    code = SecurityCode(stock)
    full_code = code.full_code
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        res = tq.order_stock(account=account, stock_code=full_code,
            order_type=order_type, order_volume=order_volume,
            price_type=price_type, price=price,
            strategy_name=strategy_name, order_remark=order_remark)

        CONSOLE.print(f"下单 {full_code} 结果: {res}")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)

# ---------------------------------------------------------------------------------------------
# 自选股/自定义板块
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('-c', '--contains', 'contains', multiple=True, callback=split_comma, help='包含的字串')
@click.option('-v', '--verbose', 'is_verbose', is_flag=True, help='是否打印详细信息')
@click.option('-max', '--max-to-show', 'max_to_show', default=20, show_default=True, type=int, help='最多显示多少只股票（仅 is_verbose=True 时有效）')
@click.pass_context
def get_user_sector(
    _ctx: click.Context,
    contains: list[str], # 用于查找
    is_verbose: bool,
    max_to_show: int,
):
    """获取自定义板块列表"""
    CONSOLE = _ctx.obj['console'] # type: Console

    try:
        sectors = tq.get_user_sector() # type: list[str, dict]

        sectors_filtered = []
        if sectors and isinstance(sectors, list):
            if contains:
                for x in sectors:
                    name = x.get('Name', '')
                    for contain_str in contains:
                        if contain_str in name:
                            sectors_filtered.append(x)
                            break

                if sectors_filtered:
                    CONSOLE.print(f"自定义板块（过滤含有 {contains} ）共 {len(sectors_filtered)} / {len(sectors)} 个。" )
                else:
                    CONSOLE.print(f"未发现包含 {contains} 的自定义板块。")
                    return
            else:
                CONSOLE.print(f"自定义板块，共 {len(sectors)} 个。")

            sector_detail_infos = []
            for sector_info in sectors_filtered if sectors_filtered else sectors:
                _code = sector_info.get('Code', '')
                _stocks_in_sector = tq.get_stock_list_in_sector(block_code=_code, block_type=1, list_type=1)
                _stocks_num = len(_stocks_in_sector) if _stocks_in_sector else 0

                _detail_info = {**sector_info, 'stock.num': _stocks_num}
                if is_verbose:
                    _detail_info.update({"Stocks": [f"{stock.get('Code', '')} {stock.get('Name', '')}" for stock in _stocks_in_sector]})
                sector_detail_infos.append(_detail_info)

            # 创建 DataFrame 并按 stock.num 排序
            df = pd.DataFrame(sector_detail_infos)
            df_sorted = df.sort_values(by='stock.num', ascending=False)
            print_dataframe(df_sorted, f'自定义板块概要{f"（过滤含有 {contains} 的板块）" if sectors_filtered else ""}',
                            printer=CONSOLE.print)
        else:
            CONSOLE.print(f"未发现自定义板块")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)



@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('--action', '-a', 'action', type=click.Choice(['get', 'send', 'remove', 'remove-st', 'clear', 'create', 'delete', 'rename', 'diff'], case_sensitive=False),
              default='get', show_default=True, help='操作类型：获取(get)、添加个股(send)、删除个股（remove）、删除板块中的ST个股（remove-st)、清空(clear)、创建(create)、删除(delete)、重命名(rename)')
@click.option('--abbrev', '-abb', 'abbrev', help='自定义板块简称')
@click.option('--name', '-n', 'name', help='自定义板块名称')
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码(如: 688318.SH)，仅在 action=send 时有效')
@click.option('--show-on-tdx', '-show', 'show_on_tdx', is_flag=True, help='是否在通达信客户端中显示添加个股的结果（仅 action=send 有效）')
@click.option('--max-to-show', '-max', 'max_to_show', default=20, show_default=True, type=int, help='最多显示多少只股票')
@click.option('--abbrev1', '-abb1', 'abbrev1', help='对比新板块简称（仅 仅 -a diff 时有效）')
@click.option('--abbrev2', '-abb2', 'abbrev2', help='对比旧板块简称（仅 仅 -a diff 时有效）')
@click.option('--name1', '-n1', 'name1', help='对比新板块名称（仅 仅 -a diff 时有效）')
@click.option('--name2', '-n2', 'name2', help='对比旧板块名称（仅 仅 -a diff 时有效）')
@click.option('--with-name', '-wn', 'is_with_name', is_flag=True, help='股票代码是否带上股票名称')
@click.pass_context
def user_sector(
    _ctx: click.Context,
    action: str,
    abbrev: str,
    name: str,
    stocks: list[str],
    show_on_tdx: bool,
    max_to_show: int,
    abbrev1: str,
    abbrev2: str,
    name1: str,
    name2: str,
    is_with_name: bool,
    is_save_memory: bool,
    group_index: int,
):
    """获取自定义板块中的股票列表（需要先使用 get_user_sector 获取板块列表）"""
    CONSOLE = _ctx.obj['console'] # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    action = action.lower()

    print_locals()

    try:
        # 先获得原有的用户自定义板块列表，进行一些基础的校验和准备工作（如：板块名称和代码的映射关系等），后续再根据不同的 action 进行不同的操作
        sectors = tq.get_user_sector() # type: list[str, dict]
        sectors_code2name = {}
        sectors_name2code = {}
        if sectors and isinstance(sectors, list):
            for sector_info in sectors:
                _code = sector_info.get('Code', '')
                _name = sector_info.get('Name', '')
                sectors_code2name.update({_code: _name})
                sectors_name2code.update({_name: _code})

        # 获取自定义板块 ----------------------------------------------------------------------
        if action == 'get':
            filtered_sectors = []
            if abbrev:
                filtered_sectors.extend([{'Code': c, 'Name': n} for c, n in sectors_code2name.items() if abbrev in c])
                CONSOLE.print(f"匹配到的板块（包含 {abbrev} 的板块名称）：{filtered_sectors}")
            if name:
                filtered_sectors.extend([{'Code': c, 'Name': n} for c, n in sectors_code2name.items() if name in n])
                CONSOLE.print(f"匹配到的板块（包含 {name} 的板块名称）：{filtered_sectors}")

            if abbrev or name:

                stocks_in_filtered_sectors = set()

                CONSOLE.print(f"已匹配到的板块列表 {len(filtered_sectors)} / {len(sectors)}: {filtered_sectors}")

                for f_sector in filtered_sectors:
                    _code = f_sector['Code']

                    _stocks = tq.get_stock_list_in_sector(block_code=_code, block_type=1, list_type=0)

                    CONSOLE.print(f"板块代码 {_code} 内有 {len(_stocks)} 只个股:", end='')
                    if is_with_name:
                        stocks_with_name = [f"{code}|{get_stock_name(code)}" for code in _stocks]
                        CONSOLE.print(Pretty(stocks_with_name, max_length=max_to_show) if max_to_show > 0 else stocks_with_name)
                    else:
                        CONSOLE.print(Pretty(_stocks, max_length=max_to_show) if max_to_show > 0 else _stocks)

                    if show_on_tdx:
                        tq.send_user_block(block_code=_code, stocks=_stocks, show=True) # 把最后一个显示在客户端

                    if is_save_memory or _is_pipe_producer:
                        stocks_in_filtered_sectors.update(set([_get(x) for x in _stocks if x]))

                if is_save_memory or _is_pipe_producer:
                        return {'stocks': stocks_in_filtered_sectors}
            else:
                CONSOLE.print(f"自定义板块列表（共 {len(sectors)} 个）: ", end='')
                CONSOLE.print(Pretty(sectors))

            # 当 action == get 时，-sm 参数可存储板块中的个股到 cache_cmd.STOCKS 中，供后续命令使用
            if is_save_memory or _is_pipe_producer:
                stocks_in_sectors = set()
                for sector_info in sectors:
                    _code = sector_info.get('Code', '')
                    _stocks_in_sector = tq.get_stock_list_in_sector(block_code=_code, block_type=1, list_type=0)
                    if _stocks_in_sector and isinstance(_stocks_in_sector, list):
                        stocks_in_sectors.update(set([_get(x) for x in _stocks_in_sector if x]))

                return {'stocks': stocks_in_sectors}

        # 往指定自定义板块中添加成份股
        elif action == 'send':
            if abbrev:
                code = abbrev
            elif name:
                code = sectors_name2code.get(name)
                if not code:
                    W(f"未找到匹配的板块名称（自定义板块名称包含 {name} 的板块名称），个股将添加到临时条件股", name=name)

            name = sectors_code2name.get(code, '临时条件股')

            tq.send_user_block(block_code=code, stocks=stocks, show=show_on_tdx)

            CONSOLE.print(f"已将 {len(stocks)} 只个股添加到自定义板块【代码：{code} 名称：{name}】中")

        elif action == 'remove' or action == 'remove-st':
            if abbrev:
                code = abbrev
            elif name:
                code = sectors_name2code.get(name)
                if not code:
                    E(f"未找到匹配的板块名称（自定义板块名称包含 {name} 的板块名称），无法删除个股", name=name)
                    return

            name = sectors_code2name.get(code)
            _stocks = tq.get_stock_list_in_sector(block_code=code, block_type=1, list_type=0) or []

            if action == 'remove':
                if stocks:
                    remained_stocks = set(_stocks) - set(stocks)
                    tq.send_user_block(block_code=code, stocks=list(remained_stocks), show=show_on_tdx)
                    CONSOLE.print(f"已从自定义板块【代码：{code} 名称：{name}】中删除 {len(stocks)} 只个股，剩余 {len(remained_stocks)} 只个股: ", end='')
                    CONSOLE.print(Pretty(list(remained_stocks), max_length=max_to_show) if max_to_show > 0 else list(remained_stocks))
                else:
                    CONSOLE.print(f"[pink] 未指定需要从板块中删除的个股，请带上 -s 参数指定要删除的个股 [/pink]")
                    CONSOLE.print(f"自定义板块【代码：{code} 名称：{name}】中共有 {len(_stocks)} 只个股: ", end='')
                    CONSOLE.print(Pretty(_stocks, max_length=max_to_show) if max_to_show > 0 else _stocks)
            elif action == 'remove-st':
                # 获取板块中的个股列表，过滤掉名称中包含 ST 的个股后再发送到客户端
                st_stocks = []
                keep_stocks = []
                for stock_code in _stocks:
                    if is_st(stock_code):
                        st_stocks.append(stock_code)
                    else:
                        keep_stocks.append(stock_code)

                tq.clear_sector(block_code=code)  # 先清空原有板块中的个股
                tq.send_user_block(block_code=code, stocks=keep_stocks, show=show_on_tdx)  # 再把过滤掉 ST 后的个股发送到客户端

                CONSOLE.print(f"已从自定义板块【代码：{code} 名称：{name}】中删除 ST 的个股共 {len(_stocks) - len(keep_stocks)} 只: ", end='')
                CONSOLE.print(Pretty(st_stocks, max_length=max_to_show) if max_to_show > 0 else st_stocks)


        elif action == 'clear':
            filtered_sectors = []
            if abbrev:
                filtered_sectors.extend([{'Code': c, 'Name': n} for c, n in sectors_code2name.items() if abbrev in c])
                CONSOLE.print(f"匹配到的板块（包含 {abbrev} 的板块名称）：{filtered_sectors}")
            if name:
                filtered_sectors.extend([{'Code': c, 'Name': n} for c, n in sectors_code2name.items() if name in n])
                CONSOLE.print(f"匹配到的板块（包含 {name} 的板块名称）：{filtered_sectors}")

            clear_all = False
            for sector_info in filtered_sectors:
                if not isinstance(sector_info, dict):
                    continue
                name = sector_info.get('Name', '')
                code = sector_info.get('Code', '')
                # 定义选项以及它们对应的值
                choices = {"y": "yes", "n": "no", "a": "all"}
                # 获取用户输入, 并验证它是否在我们定义的选项内
                answer = click.prompt(
                    f"删除板块 {name} ? (y/n/a)",
                    type=click.Choice(list(choices.keys()), case_sensitive=False),
                    default="n", show_choices=True
                )
                # 根据用户选择执行业务逻辑
                if answer == "n":
                    click.secho("用户取消操作. ", style=Style(color="red"))
                    return
                elif answer == "y" or clear_all:
                    tq.delete_sector(block_code=code)
                    click.secho("❌ 成功删除自定义板块", style=Style(color="green"))
                    # 这里执行单个任务的逻辑
                elif answer == "a":
                    CONSOLE.print("⚠️ 接下来删除余下的自定义板块", style=Style(color="yellow", bold=True))
                    clear_all = True

                click.confirm(f"确定要清空自定义板块【代码：{code} 名称：{name}】中的个股吗？", abort=True)

                CONSOLE.print(f"已清空自定义板块【代码：{code} 名称：{name}】中的个股")

        elif action == 'diff':
            if abbrev1:
                code1 = abbrev1
            if abbrev2:
                code2 = abbrev2

            if name1:
                code1 = sectors_name2code.get(name1)

            if name2:
                code2 = sectors_name2code.get(name2)

            if not (code1 and code2):
                E("进行板块对比时，参数 -abb1 （或 -n1） 和 -abb2（或-n2） 都必须提供")
                return

            stocks1 = set(tq.get_stock_list_in_sector(block_code=code1, block_type=1, list_type=0) or [])
            stocks2 = set(tq.get_stock_list_in_sector(block_code=code2, block_type=1, list_type=0) or [])

            only_in_1 = stocks1 - stocks2
            only_in_2 = stocks2 - stocks1
            in_both = stocks1 & stocks2

            CONSOLE.print(f"仅在 {abbrev1} 中的个股（共 {len(only_in_1)} 只）: ", end='')
            CONSOLE.print(Pretty(list(only_in_1), max_length=max_to_show) if max_to_show > 0 else list(only_in_1))

            CONSOLE.print(f"仅在 {abbrev2} 中的个股（共 {len(only_in_2)} 只）: ", end='')
            CONSOLE.print(Pretty(list(only_in_2), max_length=max_to_show) if max_to_show > 0 else list(only_in_2))

            CONSOLE.print(f"同时在 {abbrev1} 和 {abbrev2} 中的个股（共 {len(in_both)} 只）: ", end='')
            CONSOLE.print(Pretty(list(in_both), max_length=max_to_show) if max_to_show > 0 else list(in_both))


    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ---------------------------------------------------------------------------------------------
# 通用函数
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--start-time', '-st', 'start_time', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', 'end_time',  type=DATETIME, help='结束时间')
@click.option('--count', '-c', 'count', default=-1, type=int, help='返回最近的count个交易日')
@click.pass_context
def get_trading_dates(
    _ctx: click.Context,
    start_time: datetime | None,
    end_time: datetime | None,
    count: int,

):
    """获取交易日列表"""
    start_time = start_time.strftime('%Y%m%d') if start_time else ''
    end_time = end_time.strftime('%Y%m%d') if end_time else ''

    print_locals()

    CONSOLE = _ctx.obj['console']  # type: Console

    try:
        res = tq.get_trading_dates(market='SH', start_time=start_time, end_time=end_time, count=count)
        CONSOLE.print(f"{res}")
        return res

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)

# ---------------------------------------------------------------------------------------------
# 调用通达信公式
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@df_collector
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 688318.SH)')
@click.option('--formula-type', '-t', 'formula_type', required=True,
              type=click.Choice(['zb', 'xg', 'exp'], case_sensitive=False), default='zb', show_default=True,
              help='技术指标zb/条件选股xg/专家系统exp')
@click.option('--count', '-c', 'count',  default=20, type=int, help='获取数据条数（最大值为24000，count为-1时为获取对应股票全部K线）')
@click.option('--period', '-p', 'period', default='1d', type=click.Choice(ALL_PERIODS), show_default=True, help='K线周期')
@click.option('--dividend-type', '-d', 'dividend_type', default=1, show_default=True, help='0不复权 1前复权 2后复权')
@click.option('--name', '-n', 'name', help='公式名称（空时列出所有可用的公式名称供参考，-l 参数时可用于查找）')
@click.option('--arg', '-a', 'args', multiple=True, callback=split_comma, help='公式参数（多个以逗号分隔，或者用多个参数带入）')
@click.option('--xsflag', '-x', 'xs_flag', type=int, default=0, help='数据精度（最大可返回8位小数。）')
@click.option('--max-to-show', '-max', 'max_to_show', default=300, show_default=True, type=int, help='最多显示多少条数据')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
# 2026-05-22 新接口: formula_get_all, formula_get_info
@click.option('--list-all', '-l', 'list_all', is_flag=True, help='列出所有可用的公式名称')
# 2026-6-13 新参数：过滤 OUTPUT 开头的指标字段
@click.option('--keep-output', '-ko', 'is_keep_output', is_flag=True, help='是否保留【技术指标】中的 OUTPUT 开头的字段')
@click.option('--jump-tdx', '-j', 'jump_tdx', is_flag=True, help='跳转通达信界面（以获得L2指标数据）')
@click.option('--with-name', '-wn', 'is_with_name', is_flag=True, help='股票代码是否带上股票名称')
@click.pass_context
def formula(
    _ctx: click.Context,
    formula_type: str,
    stocks: list[str],
    count: int,
    period: str,
    dividend_type: int,
    name: str,
    args: list[str],
    xs_flag: int,
    max_to_show: int,
    verbose: bool,
    list_all: bool,
    is_keep_output: bool,
    jump_tdx: bool,
    is_with_name: bool,
    **kwargs,
):
    """调用通达信公式进行计算（技术指标zb/条件选股xg/专家系统exp）公式"""
    dividend_type_str = {0: 'none', 1: 'front', 2:'back'}.get(dividend_type, None)
    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console

    if not stocks:
        CONSOLE.print("⚠️ 股票列表为空，请使用 -s/--stock （或在 memory-cache 命令中缓存）指定。")
        return

    _ft_name = {
        'zb': '技术指标',
        'xg': '条件选股',
        'exp': '专家系统'
    }.get(formula_type)

    _ft_int = {'zb': 0, 'xg': 1, 'exp': 2}.get(formula_type)

    try:
        if list_all or not name:
            # 当没有指定公式名称时，列出所有可用的公式名称供用户参考
            res = tq.formula_get_all(formula_type=_ft_int)

            total_formula_num = len(res) if res and isinstance(res, list) else 0

            if name:
                # 筛选 acCdoe, acName 中包含 name 字符串的公式
                res = [x for x in res if name in x.get('acCode', '') or name in x.get('acName', '')]

            _all_formula_df = pd.DataFrame(res)

            title = f"所有{('含有 [yellow]' + name + '[/yellow] 的') if name else ''} {_ft_name} 公式"
            if name:
                title += f"（共 {len(res)} / {total_formula_num} 个）"

            if res:
                print_dataframe(_all_formula_df, title=title, table_max_rows=max_to_show, printer=CONSOLE.print)
            else:
                CONSOLE.print(f"未找到合符条件的 {_ft_name} 公式。")

            if verbose:
                for formula_info in res:
                    _f_name = formula_info.get('acName', '')
                    _f_code = formula_info.get('acCode', '')
                    formula_detail_info = tq.formula_get_info(formula_type=_ft_int, formula_code=_f_code)
                    CONSOLE.print(f"{_ft_name} 公式 {_f_name}（{_f_code}）的详细信息:")
                    CONSOLE.print(Pretty(formula_detail_info))

            return

        # 获取交易日用于组装数据
        trading_dates = tq.get_trading_dates(market='SH', start_time='', end_time='', count=count)
        CONSOLE.print(f"len(trading_dates) = {len(trading_dates)}")
        if verbose:
            CONSOLE.print(f"trading_dates = ", end='')
            CONSOLE.print(Pretty(trading_dates, max_length=max_to_show))

        code_2_value = {}
        code_2_df = {}

        # for _, full_code in enumerate_with_progress(stocks, console=CONSOLE):
        for _, full_code in enumerate(stocks):
            # NOTICE: 通达信缺陷：L2 数据需要软件先跳转（触发界面拉取后）才能获取，不然全是 0 值
            if jump_tdx:
                jump_res = tq.exec_to_tdx(url=f"http://www.treeid/code_{full_code[:6]}") # 界面跳转
                # CONSOLE.print(f"跳转返回： {jump_res}")
                sleep(2)

            formula_set_res = tq.formula_set_data_info(stock_code=full_code, stock_period=period, count=count, dividend_type=dividend_type)
            # if verbose:
            if isinstance(formula_set_res, dict):
                if int(formula_set_res.get('ErrorId', '-1')) != 0:
                    CONSOLE.print(f"[ERROR] formula_set_res(): {formula_set_res}")
                    break # 失败了就没必要进行下一步了

            formula_arg = ','.join(args)
            if formula_type == 'zb':
                # -n MACD -a 12,26,9
                formula_res = tq.formula_zb(formula_name=name, formula_arg=formula_arg, xsflag=xs_flag)
            elif formula_type == 'xg':
                formula_res = tq.formula_xg(formula_name=name, formula_arg=formula_arg)
            elif formula_type == 'exp':
                formula_res = tq.formula_exp(formula_name=name, formula_arg=formula_arg)

            if verbose:
                CONSOLE.print(f"{full_code} {get_stock_name(full_code)} 在技术指标 {name} 值: {json.dumps(formula_res, indent=2, ensure_ascii=False)}")

            if formula_type != 'zb':  # 【技术指标】才需要过滤 OUTPUT 开头的数据，其他指标默认都过滤
                is_keep_output = True

            value_of_res = {}
            if formula_res and isinstance(formula_res, dict) and int(formula_res.get('ErrorId', -1)) == 0:
                value_of_res = formula_res.get('Value', {})
                if value_of_res and isinstance(value_of_res, dict):
                    if not is_keep_output:
                        # 过滤 OUTPUT 开头的值
                        value_of_res = {k:v for k,v in value_of_res.items() if not str(k).startswith("OUTPUT")}
                    code_2_value.update({full_code: value_of_res})

            # 处理并统计结果
            if formula_type in ('zb', 'xg'):
                # 处理 技术指标 结果

                if value_of_res and len(value_of_res) > 0:
                    value_of_res_VALUES_LIST = list(value_of_res.values())
                    cnt_of_res = len(value_of_res_VALUES_LIST[0])

                    if verbose:
                        CONSOLE.print(f"指标有{len(value_of_res)}个数，涵盖 {cnt_of_res} 天")

                    if cnt_of_res < count:
                        CONSOLE.print(f"⚠️ 返回指标天数 < 请求的数量({count})")

                    # 有效数据个数 = 交易日和指标返回结果的最小值
                    valid_cnt = min(cnt_of_res, len(trading_dates))
                    # 1. 构建 DataFrame
                    # 这里 index 已经是 datetime 类型，列是指标数值
                    # trading_dates 和 value_of_res 都一样，越临近的交易日数据越往后
                    df = pd.DataFrame(value_of_res, index=pd.to_datetime(trading_dates[-cnt_of_res:]))

                    # 假设 df 是你已经构建好的 DataFrame
                    # 1. 定义什么叫“无效行”：全部为 None、空字符串或数值 0
                    # 将所有可能的情况统一转化为 True (无效)
                    is_invalid_row = (df.isna()) | (df == 0) | (df == '')

                    # 2. 找到这些无效行在 DataFrame 中的累计状态
                    # cumall() 会判断：从第一行开始，直到遇到第一行 False（有效数据）之前，前面的行都标记为 True
                    # 比如：[True, True, False, True, False] -> [True, True, False, False, False]
                    valid_mask = is_invalid_row.all(axis=1).cumprod().astype(bool)

                    # 3. 过滤掉那些在有效数据出现之前的“无效行”
                    df_cleaned = df[~valid_mask]

                    if verbose:
                        if not df.empty:
                            print_dataframe(df, title=f"{full_code} {get_stock_name(full_code)} 在技术指标 {name} 的输出（未过滤空值）",
                                            table_max_rows=max_to_show, printer=CONSOLE.print)

                    # 3. 后续打印或处理使用 df_cleaned
                    if formula_type == 'zb' or verbose: # 指标公式（除非 verbose）不显示
                        if not df_cleaned.empty:
                            print_dataframe(df_cleaned, title=f"{full_code} {get_stock_name(full_code)} 在技术指标 {name} 的输出（已过滤空值）",
                                            table_max_rows=max_to_show, printer=CONSOLE.print)

                    if not df_cleaned.empty:
                        code_2_df[full_code] = df_cleaned
                    else:
                        code_2_df[full_code] = df
        # DEBUG:
        if verbose:
            CONSOLE.print(f"code_2_value = {code_2_value}")

            CONSOLE.print(f"res_df = ", end='')
            CONSOLE.print(Pretty(res_df))

        if formula_type == 'zb':
            return {'dfs': code_2_df}
        if formula_type == 'xg':
            # NOTICE: 选股公式，输出都是 OUTPUT1 中，被选中的 str(OUTPUT1) == "1"
            res_df = _trans_xg_data_to_date2stocks(code_2_value, trading_dates, field_be_counted='OUTPUT1', is_with_name=is_with_name)

            print_dataframe(res_df, title='选股结果', flatten_list=True,
                            exclude_cols=['stocks'] if is_with_name else [], printer=CONSOLE.print)
            # return {'stocks': code_2_df.keys()}
        elif formula_type == 'exp':
            res_df = _trans_xg_data_to_date2stocks(code_2_value, trading_dates, field_be_counted='ENTERLONG', is_with_name=is_with_name)
            print_dataframe(res_df, title='专家系统 买入信号（ENTERLONG）统计结果',
                            exclude_cols=['stocks'] if is_with_name else [], printer=CONSOLE.print)

            res_df = _trans_xg_data_to_date2stocks(code_2_value, trading_dates, field_be_counted='EXITLONG', is_with_name=is_with_name)
            print_dataframe(res_df, title='专家系统 卖出信号（EXITLONG）统计结果',
                            exclude_cols=['stocks'] if is_with_name else [], printer=CONSOLE.print)



        # stocks_on_date = _trans_xg_data_to_date2stocks(df)
        # for date, stocks in stocks_on_date.items():
        #     if stocks:  # 只显示有股票的日期
        #         print(f"{date}: {stocks} (共{len(stocks)}只股票)")
        #     else:
        #         print(f"{date}: []")

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)




@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@df_collector
@stocks_collector
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 688318.SH)')
@click.option('--formula-type', '-t', 'formula_type', required=True,
            type=click.Choice(['zb', 'xg'], case_sensitive=False), default='zb', show_default=True,
            help='技术指标zb/条件选股xg')
# 选股公式和参数
@click.option('--name', '-n', 'name', required=True, help='公式名称')
@click.option('--arg', '-a', 'args', multiple=True, callback=split_comma, help='公式参数（多个以逗号分隔，或者用多个参数带入）')
# 返回时间和数量
@click.option('--return-count', '-rc', 'return_count', type=int, default=-1, help='设置每个返回值的返回数')
@click.option('--return-start-time', '-rst', 'return_start_time', type=DATETIME, help='设置每个返回值的返回开始时间')
@click.option('--return-end-time', '-ret', 'return_end_time', type=DATETIME, help='设置每个返回值的返回结束时间')
# K线参数
@click.option('--count', '-c', 'count', default=-1, type=int,
            help='''count为截取最新交易日开始往前的n条K线，当count参数不为0时，start_time 和 end_time 失效
count = -1 时，获取所有数据，
count = -2 时，使用无序列数据
当 count = 0 时，start_time 和 end_time 生效，指定K线为对应时间段内
count 最大值为 24000，count为 -1 时为获取对应股票全部K线''')
@click.option('--start-time', '-st', 'start_time', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', 'end_time', type=DATETIME, help='结束时间')

@click.option('--period', '-p', 'period', default='1d', type=click.Choice(ALL_PERIODS), show_default=True, help='K线周期')
@click.option('--dividend-type', '-d', 'dividend_type', type=click.Choice([0, 1, 2]), default=1, show_default=True, help='0不复权 1前复权 2后复权')
@click.option('--xs-flag', '-x', 'xs_flag', type=int, default=0, help='数据精度（最大可返回8位小数。）')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
# 用于处理输出指标列名
@click.option('--field-exclusion', '-fe', 'field_exclusions', multiple=True, callback=split_comma,
              help='需要从输出中剔除的指标列名（可多选）')
@click.option('--field-regex-exclusion', '-fre', 'field_regex_exclusions', multiple=True, callback=split_comma,
              default=[r'^OUTPUT\d+'], help='需要从输出中剔除的指标列名的正则表达式（可多选）')
@click.option('--field-inclusion', '-fi', 'field_inclusions', multiple=True, callback=split_comma,
              help='需要从输出中包含的指标列名（可多选）')
@click.option('--field-regex-inclusion', '-fri', 'field_regex_inclusions', multiple=True, callback=split_comma,
              help='需要从输出中包含的指标列名的正则表达式（可多选）')
@click.option('--with-name', '-wn', 'is_with_name', is_flag=True, help='股票代码是否带上股票名称')
@click.option('--zb-output-style', '-os', 'output_style',
              type=click.Choice(['long', 'field', 'stock'], case_sensitive=False), default='stock',
              help='选择输出结果的样式')
@click.option('-zb-sum-col', '-sc', 'sum_columns', multiple=True, callback=split_comma, help='需要统计sum的列（可多选），仅 -t zb 生效')
@click.option('--save-user-sector', '-sus', 'is_save_user_sector', is_flag=True, help='是否将选股结果保存到自定义板块中（仅 -t xg 生效）')
@click.pass_context
def formula_multi(
    _ctx: click.Context,
    stocks: list[str],
    formula_type: str,
    name: str,
    args: list[str],

    # 返回多少个周期
    return_count: int,
    # 用于过滤返回的日期范围
    return_start_time: datetime | None,
    return_end_time: datetime | None,

    # K线范围
    count: int,
    start_time: datetime | None,
    end_time: datetime | None,

    period: str,
    dividend_type: int,
    xs_flag: int,
    verbose: bool,
    field_exclusions: list[str],
    field_regex_exclusions: list[str],
    field_inclusions: list[str],
    field_regex_inclusions: list[str],
    is_with_name: bool,
    output_style: str,
    sum_columns: list[str],
    is_save_user_sector: bool,
    is_save_memory: bool,
    group_index: int,
    is_save_df: bool,
    **kwargs,
):
    """批量通达信选股公式"""
    # 注：无需使用formula_set_data和formula_set_data_info提前设置，formula_set_data和formula_set_data_info的设置也对批量调用不生效

    start_time = start_time.strftime('%Y%m%d%H%M%S') if start_time else None
    end_time = end_time.strftime('%Y%m%d%H%M%S') if end_time else None

    if start_time or end_time:
        count = 0

    print_locals()

    CONSOLE = _ctx.obj['console'] # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    try:
        formula_arg = ','.join(args)

        if formula_type == 'xg':
            # 批量调用选股公式 -----------------------------------------------------------------------------------------
            mul_res = tq.formula_process_mul_xg(
                formula_name=name,
                formula_arg=formula_arg,
                return_count=return_count,
                return_date=True, # TODO: 为了简化选股结果，需要带上日期
                stock_list=stocks,
                stock_period=period,
                dividend_type=dividend_type,
                # K线数据范围
                start_time=start_time,
                end_time=end_time,
                count=count,
            )
            if verbose:
                D(mul_res=mul_res)

            mul_res_df = _xg_multi_result_dict2df(mul_res, fill_stock_name=is_with_name)

            if return_start_time or return_end_time:
                mul_res_df = mul_res_df[(mul_res_df['Date'] >= return_start_time.strftime('%Y-%m-%d')) & (mul_res_df['Date'] <= return_end_time.strftime('%Y-%m-%d'))]

            print_dataframe(mul_res_df, title=f"批量调用选股公式结果", printer=CONSOLE.print)

            stocks_on_date = set()
            if is_save_user_sector or is_save_memory:
                for row in mul_res_df.itertuples():
                    date = getattr(row, 'Date', None)
                    if is_with_name:
                        stocks_with_name = getattr(row, 'Stocks_Name', [])
                        stocks = [x.split('|')[0] for x in stocks_with_name if isinstance(x, str)]
                    else:
                        stocks = getattr(row, 'Stocks', [])

                    if date and stocks:
                        args_str = f"_{'_'.join(formula_arg)}" if formula_arg else ""
                        usr_block_name = f"{name}{args_str}.{date}"

                        if is_save_user_sector:
                            block_code=convert_block_name_2_code(usr_block_name)
                            I(block_code=block_code, usr_block_name=usr_block_name)
                            create_res = tq.create_sector(block_code=block_code, block_name=usr_block_name)
                            I(create_res=create_res)
                            tq.send_user_block(block_code=block_code, stocks=stocks, show=True)

                            CONSOLE.print(f"{date} 选出 {len(stocks)} 只股票，存于自定义板块 [yellow]{usr_block_name}[/yellow] 内。")

                    if is_save_memory or _is_pipe_producer:
                        stocks_on_date.update(stocks)

                if is_save_memory or _is_pipe_producer:
                    return {'stocks': stocks_on_date}  # 返回就会被 stocks_collector 添加到 cache_cmd.STOCKS 中

        elif formula_type == 'zb':
            # 批量调用指标公式 -----------------------------------------------------------------------------------------
            mul_res = tq.formula_process_mul_zb(
                formula_name=name,
                formula_arg=formula_arg,
                return_count=return_count,
                return_date=True,
                # 返回指标精度（最大8）
                xsflag=xs_flag,
                stock_list=stocks,
                stock_period=period,
                dividend_type=dividend_type,
                # K线数据范围
                start_time=start_time,
                end_time=end_time,
                count=count,
            )
            if verbose:
                CONSOLE.print(f"批量调用指标公式结果: ", end='')
                CONSOLE.print(Pretty(mul_res, max_length=200))

                # 把完整的结果保存到文件中
                with open(f"RESULT-{'.'.join(stocks)}-zb_{name}({formula_arg}).json", 'w+', encoding='utf-8') as F:
                    F.write(json.dumps(mul_res, ensure_ascii=False, indent=2))
                    F.flush()

            # 方法1：转换为长格式DataFrame
            df_long = _zb_multi_result_to_dataframe(mul_res, index=None)

            # 检查转换后的DataFrame是否为空
            if df_long.empty:
                CONSOLE.print(f"[yellow]公式 {name} 返回的数据为空[/yellow]")
                return

            # 处理 exclude/include fields
            required_cols = ['stock_code', 'date'] # 必要的列（始终保留）

            for fe in (field_exclusions or []):
                df_long = df_long.loc[:, ~df_long.columns.str.contains(fe, na=False)]
            for fre in (field_regex_exclusions or []):
                df_long = df_long.loc[:, ~df_long.columns.str.contains(fre, regex=True, na=False)]

            # 处理 field_inclusions（包含）
            if field_inclusions:
                matched_cols = []
                for fi in field_inclusions:
                    matched = df_long.columns[df_long.columns.str.contains(fi, na=False)].tolist()
                    matched_cols.extend(matched)

                # 确保必要的列和匹配的列都存在
                cols_to_keep = []
                for col in set(required_cols + matched_cols):
                    if col in df_long.columns:
                        cols_to_keep.append(col)

                if cols_to_keep:
                    df_long = df_long[cols_to_keep]
                else:
                    print("警告: 没有找到匹配的列，保留所有列")

            # 处理 field_regex_inclusions（正则包含）
            if field_regex_inclusions:
                matched_cols = []
                for fri in field_regex_inclusions:
                    matched = df_long.columns[df_long.columns.str.contains(fri, regex=True, na=False)].tolist()
                    matched_cols.extend(matched)

                cols_to_keep = list(set(required_cols + matched_cols))
                # 只保留实际存在的列
                cols_to_keep = [col for col in cols_to_keep if col in df_long.columns]
                df_long = df_long[cols_to_keep]

            if output_style == 'long':
                print_dataframe(df_long, title="方法1：长格式DataFrame", sum_cols=sum_columns, printer=CONSOLE.print)
            elif output_style == 'field':
                # 方法2：转换为透视表（每个指标一个表）
                CONSOLE.print("透视表格式（每个指标一个表）")
                pivot_dfs = _zb_multi_result_to_pivot(df_long)
                for indicator, pivot_df in pivot_dfs.items():
                    print_dataframe(pivot_df, title=f"指标: {indicator}", sum_cols=sum_columns, printer=CONSOLE.print)
            elif output_style == 'stock':
                # 方法3：转换为以股票为第一层的DataFrame
                CONSOLE.print("以股票为第一层的DataFrame")
                stock_dfs = _zb_multi_result_dataframe_stock_first(df_long)
                for stock_code, stock_df in stock_dfs.items():
                    print_dataframe(stock_df, title=f"{stock_code}|{get_stock_name(stock_code,'')} 在 [yellow]{name}[/yellow] 指标的值", sum_cols=sum_columns, printer=CONSOLE.print)

                # TODO:
                if is_save_df:
                    return {'dfs': stock_dfs}
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ---------------------------------------------------------------------------------------------
# 订阅/取消订阅 行情

SUBSCRIBED_STOCKS = set()

@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 688318.SH)')
@click.option('--unsubscribe', '-u', 'is_unsubscribe', is_flag=True, help='是否取消订阅（默认为订阅）')
@click.pass_context
def subscribe_hq(_ctx: click.Context,
    stocks: list[str],
    is_unsubscribe: bool,
):
    """订阅行情"""
    CONSOLE = _ctx.obj['console'] # type: Console
    if not stocks:
        CONSOLE.print("[yellow]请至少指定一只股票进行订阅/取消订阅[/yellow]")
        return

    global SUBSCRIBED_STOCKS

    try:
        if is_unsubscribe:
            tq.unsubscribe_hq(stock_list=stocks)
            SUBSCRIBED_STOCKS.difference_update(stocks)
            CONSOLE.print(f"已取消订阅股票: {stocks}，当前订阅列表: {SUBSCRIBED_STOCKS}")
            return

        tq.subscribe_hq(stock_list=stocks, callback=lambda data: CONSOLE.print(f"行情更新: {data}"))
        SUBSCRIBED_STOCKS.update(stocks)
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)




@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.pass_context
def _example(_ctx: click.Context,
    stocks: list[str],
):
    """"""
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            # TODO:
            CONSOLE.print(f"{full_code} :", )
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS, help='股票代码列表 (如: 688318.SH)')
@click.pass_context
def test(_ctx: click.Context,
    stocks: list[str],
):
    """（测试）"""
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        formula_name = 'UPN'
        # 批量调用UPN 选股公式
        mul_xg_res = tq.formula_process_mul_xg(
            formula_name='UPN',
            formula_arg='3',
            return_count=30,
            return_date=True,
            stock_list=['688318.SH','600519.SH','000001.SZ'],
            stock_period='1d',
            count=5,
            dividend_type=1)
        CONSOLE.print(f"批量调用 {formula_name} 选股公式，结果: {mul_xg_res}")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


