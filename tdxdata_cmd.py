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
# - v1.3.7 (2026-06-26)
#【添加】在 difoss_stock_util 支持子命令管道功能后，代码适配性修改

import click
from tdx_quant.tqcenter import tq
from rich import print as pprint
from rich.console import Console
from rich.pretty import Pretty
from rich.style import Style
from datetime import datetime, timedelta

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
from difoss_stock_util.util import print_locals, trace_function
from difoss_stock_util.stock_util import calc_belong_trading_day, calc_previous_trading_day, calc_count_of_trading_days, TradingInfo, is_st_stock
from difoss_stock_util.db_util_lazy_loading import *
from difoss_stock_util.metric_data.stock_metrics import StockMetrics
from difoss_stock_util.metric_data.market_data import MarketData
from datetime import time as datetime_time
from difoss_stock_util.tdx_util.tdx_quant_data_dictionary import *
from difoss_stock_util.time_util import TimeUtils
from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import enumerate_with_progress, progress_print
from typing import Optional, Dict, List
from tdx_quant_util import *
from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session
from time import sleep, time

from cache_cmd import (STOCKS,
                       stocks_collector, blocks_collector, df_collector,
                       memory_cache, data_frame, blocks_2_stocks,
                       get_stock_name, cache_stock_name, is_st)

# ---------------------------------------------------------------------------------------------
# Constants
ALL_PERIODS = ['1m', '5m', '15m', '30m', '1h', '1d', '1w', '1mon', '1q', '1y',
    'tick'  # DEBUG
]
ALL_DB_LIST = ['pg', 'postgresql', 'sqlite']
DB_TYPE = 'pg'  # 全局默认数据库类型，可通过 db 命令的 --set-db-type 修改


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

    # 过滤掉"有效数据出现之前的无效行"（与 formula 函数行为一致）
    # 逻辑：对于每只股票，从开头逐行检查，如果某行所有指标值均为 NaN/0/空字符串，
    # 则视为"无效前导行"并删除，直到遇到第一个至少有一列有效值的行。
    if not df.empty:
        indicator_cols = [c for c in df.columns if c not in ('stock_code', 'date')]
        if indicator_cols:
            def _filter_invalid_leading_rows(group_df: pd.DataFrame) -> pd.DataFrame:
                """过滤单只股票的有效数据出现之前的无效行"""
                if group_df.empty:
                    return group_df
                # 标记所有指标值均为 NaN、0（数值或字符串）、空字符串的行
                is_invalid_row = (
                    group_df[indicator_cols].isna()
                    | (group_df[indicator_cols] == 0)
                    | (group_df[indicator_cols] == '0')
                    | (group_df[indicator_cols] == '')
                )
                # cumprod: 一旦遇到第一个非全无效行（值为 False/0），后续全部为 False
                valid_mask = is_invalid_row.all(axis=1).cumprod().astype(bool)
                return group_df[~valid_mask]

            # 逐股票分组过滤（避免 groupby.apply 的 include_groups 兼容问题）
            filtered_dfs = []
            for _, group_df in df.groupby('stock_code', sort=False):
                filtered = _filter_invalid_leading_rows(group_df)
                if not filtered.empty:
                    filtered_dfs.append(filtered)
            df = pd.concat(filtered_dfs, ignore_index=True) if filtered_dfs else df.iloc[0:0]

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
    _CSL = _ctx.obj['console'] # type: Console
    try:
        result = tq.refresh_cache()
        _CSL.print(f"✅ 缓存刷新成功, result: {result}")

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--period', '-p', default='1d', type=click.Choice(ALL_PERIODS), show_default=True, help='K线周期')
@click.pass_context
def refresh_kline(_ctx: click.Context, stocks: list[str], period: str):
    """刷新K线缓存
    目前仅支持1m 5m 1d三种类型数据 不建议一次更新太多，会堵塞策略和客户端
    """
    print_locals()

    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.refresh_kline(stock_list=stocks, period=period)
        _CSL.print(res)
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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
    _CSL = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            bt_data = tq.send_bt_data(stock_code=full_code,
                                    time_list = [x.strftime('%Y%m%d%H%M%S') for x in time_list],
                                    data_list=[d.split('|') for d in data_list],
                                    count=len(data_list)),

            _CSL.print(f"发送 {full_code} 的回测数据，返回: {bt_data}")
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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
    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_match_stkinfo(key_word)
        if not res:
            _CSL.print(f'关键字 [yellow]{key_word}[/yellow]，查无数据')
            return
        display_df = _categorize_securities(res)
        print_dataframe(display_df, title=f'含有 [yellow]{key_word}[/yellow] 的证券信息')
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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
                    cache_df: bool,
                    **kwargs, # 这样一来，就不用手动添加 df_collector 的变量了。
):
    """获取K线数据"""
    start_time = start_time.strftime('%Y%m%d%H%M%S') if start_time else None
    end_time = end_time.strftime('%Y%m%d%H%M%S') if end_time else None

    print_locals()

    _CSL = _ctx.obj['console'] # type: Console
    _CFG = _ctx.obj['cfg'] # type: dict

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
            _CSL.print(f"{dict(stock_list=stocks, typeOfres=type(dict_df), res=dict_df)}")

        if dict_df and len(dict_df) > 0:
            if period == 'tick':
                _CSL.print(f"df: {dict_df}")
                return

            # DEBUG:
            # for k, v in dict_df.items():
            #     print_dataframe(v, title=f'Key: {k}')

            stock_2_df = transform_field_to_stock_fast(dict_df)

            for code, stock_df in stock_2_df.items():

                if not cache_df:
                    # 保存到 df 中，就不打印了
                    print_dataframe(stock_df, title=f"股票数据 {code} （{period}）K线数据",
                                    show_footer=True, printer=_CSL.print)
                if is_save_db:
                    _save_to_db(stock_df, code, 'history_data_1d', _CSL, _CFG, db_type=DB_TYPE)

            _dt_map = {'none': 0, 'front': 1, 'back': 2}
            return {'dfs': stock_2_df, '_source': 'market_data',
                    'period': period, 'dividend_type': _dt_map.get(dividend_type, 1)}

        else:
            _CSL.print("[red]❎ 返回空数据[/red]")

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)



# ---------------------------------------------------------------------------------------------
# 共享的 K 线数据入库辅助函数（供 get_market_data --save-db 和 db 命令共用）

def _assemble_db_url(db_type: str, cfg: dict) -> str:
    """根据 db_type 从 cfg 组装数据库连接 URL"""
    if db_type == 'sqlite':
        db_cfg = cfg.get('sqlite', {'drivername': 'sqlite', 'database': ':memory:'})
    elif db_type in ('pg', 'postgresql'):
        db_cfg = cfg.get('postgresql', {})
    else:
        raise ValueError(f"不支持的 db_type: {db_type}")
    if not db_cfg:
        raise ValueError(f"config.yaml 中缺少 {db_type} 数据库配置")
    return generate_engine_url_str(**db_cfg)


# 表名 → ORM 模型类 的映射（支持按需扩展）
def _get_model_for_table(table_name: str):
    """根据表名获取对应的 ORM 模型类"""
    _TABLE_MODEL_MAP = {
        'history_data_1d': ('difoss_stock_util.metric_data.history_data_1d', 'HistoryData1D'),
    }
    info = _TABLE_MODEL_MAP.get(table_name)
    if not info:
        return None
    import importlib
    module = importlib.import_module(info[0])
    return getattr(module, info[1])


def _df_row_to_record(date_idx, row: pd.Series, exchange_id: str, instrument_id: str) -> dict:
    """将 DataFrame 的一行转换为数据库记录 dict"""
    trade_date = date_idx.date() if isinstance(date_idx, pd.Timestamp) else pd.to_datetime(date_idx).date()
    return {
        'ExchangeID': exchange_id,
        'InstrumentID': instrument_id,
        'trade_date': trade_date,
        'open': float(row['Open']) if pd.notna(row.get('Open')) else None,
        'close': float(row['Close']) if pd.notna(row.get('Close')) else None,
        'high': float(row['High']) if pd.notna(row.get('High')) else None,
        'low': float(row['Low']) if pd.notna(row.get('Low')) else None,
        'volume': int(row['Volume']) if pd.notna(row.get('Volume')) else 0,
        'amount': float(row['Amount']) if pd.notna(row.get('Amount')) else None,
        'suspend_flag': False,
    }


def _save_kline_to_db_table(dfs: dict, table_name: str, db_type: str, cfg: dict,
                             is_replace: bool, console: Console) -> int:
    """通用 K 线数据入库（支持管道和内部调用）

    Args:
        dfs: {stock_code: DataFrame} 格式，DataFrame 索引为日期，列含 Open/Close/High/Low/Volume/Amount
        table_name: 目标数据库表名（如 history_data_1d）
        db_type: 数据库类型（pg / postgresql / sqlite）
        cfg: config.yaml 配置字典
        is_replace: 是否替换已存在的记录
        console: Rich Console 实例

    Returns:
        成功插入的总记录数
    """
    model_cls = _get_model_for_table(table_name)
    if not model_cls:
        console.print(f"[red]不支持的表名: {table_name}[/red]")
        return 0

    db_url = _assemble_db_url(db_type, cfg)
    model_cls.init_db(db_url)
    total_inserted = 0

    for code, df in dfs.items():
        if df.empty:
            continue

        s_code = SecurityCode(code)
        exchange_id = s_code.market_code
        instrument_id = s_code.short_code

        # 构建记录列表
        records = [_df_row_to_record(idx, row, exchange_id, instrument_id)
                   for idx, row in df.iterrows()]

        if not records:
            continue

        # 批量插入
        with model_cls.get_session() as session:
            for i in range(0, len(records), 1000):
                batch = records[i:i + 1000]
                try:
                    session.bulk_insert_mappings(model_cls, batch)
                    session.commit()
                    total_inserted += len(batch)
                except Exception as e:
                    session.rollback()
                    if is_replace:
                        # 逐条 upsert
                        for record in batch:
                            try:
                                session.add(model_cls(**record))
                                session.commit()
                                total_inserted += 1
                            except Exception:
                                session.rollback()
                    else:
                        # 尝试逐条插入（跳过重复键）
                        for record in batch:
                            try:
                                session.add(model_cls(**record))
                                session.commit()
                                total_inserted += 1
                            except Exception:
                                session.rollback()

    console.print(f"✅ 成功插入 {total_inserted} 条记录到 [yellow]{table_name}[/yellow]")
    return total_inserted


def _save_to_db(df: pd.DataFrame, code: str, table_name: str,
                console: Console, cfg: dict, db_type: str = None, is_replace: bool = False):
    """保存单只股票的 K 线数据到数据库（供 get_market_data --save-db 内部调用）"""
    if db_type is None:
        db_type = DB_TYPE
    _save_kline_to_db_table({code: df}, table_name, db_type, cfg, is_replace, console)


# ---------------------------------------------------------------------------------------------
# 数据库表查询辅助
def _query_table_stocks(db_url: str, table_name: str, console: Console,
                        trade_date: str | None = None) -> set:
    """查询指定表中所有唯一的股票代码（全码格式：603358.SH）

    - stock_metrics / market_data: 利用 (symbol, period, time DESC) 索引
    - history_data_1d: 由 ExchangeID + InstrumentID 拼接
    - trade_date: 可选，限定日期（YYYYMMDD），大幅缩小扫描范围
    """
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            if table_name in ('stock_metrics', 'market_data'):
                if trade_date:
                    # 限单日：索引 (symbol, period, time DESC) 配合 time 范围过滤
                    sql = text(f"""
                        SELECT DISTINCT symbol FROM {table_name}
                        WHERE TIME = :trade_date
                        ORDER BY symbol
                    """)
                    rows = conn.execute(sql, {'trade_date': trade_date}).fetchall()
                else:
                    rows = conn.execute(text(
                        f"""SELECT DISTINCT symbol FROM {table_name}
                        ORDER BY symbol
                    """)).fetchall()
                stocks = {str(r[0]) for r in rows}
            elif table_name == 'history_data_1d':
                if trade_date:
                    sql = text("""
                        SELECT DISTINCT "ExchangeID", "InstrumentID"
                        FROM history_data_1d
                        WHERE trade_date = :trade_date
                        ORDER BY "ExchangeID", "InstrumentID"
                    """)
                    rows = conn.execute(sql, {'trade_date': trade_date}).fetchall()
                else:
                    rows = conn.execute(text(
                        'SELECT DISTINCT "ExchangeID", "InstrumentID" FROM history_data_1d ORDER BY "ExchangeID", "InstrumentID"'
                    )).fetchall()
                stocks = set()
                for r in rows:
                    exc = str(r[0])
                    ins = str(r[1])
                    code = SecurityCode(ins + '.' + exc)
                    stocks.add(code.full_code)
            else:
                rows = conn.execute(
                    text(f"SELECT DISTINCT symbol FROM {table_name}")
                ).fetchall()
                stocks = {str(r[0]) for r in rows}
    except Exception as e:
        console.print(f"[red]查询 {table_name} 失败: {e}[/red]")
        return set()
    console.print(f"📋 [yellow]{table_name}[/yellow] 中共有 [green]{len(stocks)}[/green] 只股票"
                  + (f"（日期: {trade_date}）" if trade_date else ""))
    return stocks


# ---------------------------------------------------------------------------------------------
# 数据库保存命令（管道友好）
@command_with_abbrev(abbrev='db', context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('--table', '-t', 'table_name', default=None,
              help='目标数据库表名（如: history_data_1d / stock_metrics / market_data）。'
                   '不指定时自动推断：formula 来源 → stock_metrics，其他 → history_data_1d')
@click.option('--replace', '-r', 'is_replace', is_flag=True,
              help='替换已存在的记录（默认跳过重复键）')
@click.option('--list-stocks', '-ls', 'list_stocks', is_flag=True,
              help='列出 -t 指定表中的所有股票代码（而非写入数据），可管道给下游')
@click.option('--date', '-d', 'date', type=DATETIME, default=datetime.now(),
              help='日期（仅 -ls 时生效，过滤指定日期的数据，默认不过滤）')
@click.option('--db-type', '-db', 'db_type',
              default=None,
              type=click.Choice(ALL_DB_LIST, case_sensitive=False),
              help=f'数据库类型（默认: {DB_TYPE}，可通过 --set-db-type 修改全局默认值）')
@click.option('--set-db-type', '-sdb', 'set_db_type',
              type=click.Choice(ALL_DB_LIST, case_sensitive=False),
              help='修改全局默认的数据库类型（持久生效于当前 REPL 会话）')
@click.pass_context
def db(_ctx: click.Context, table_name: str, is_replace: bool,
       list_stocks: bool, date: datetime | None,
       db_type: str, set_db_type: str,
       cache_stocks: bool, stock_group_index: int):
    """将管道传入的数据保存到数据库表（缩写: db）

    -t 不指定时自动推断：
      formula / formula_multi 来源 → stock_metrics
      get_market_data 等其他来源 → history_data_1d

    用法示例：
        gmd -c 100 -s 600000.SH | db                    # → history_data_1d
        f -t zb -n MACD -s 603337.SH | db               # → stock_metrics
        gmd -c 100 -s 600000.SH | db -t stock_metrics   # 显式覆盖
        db -t stock_metrics -ls                          # 列出 stock_metrics 中所有股票
        db -t history_data_1d -ls | fcf -zm-min 1000      # 管道：有K线数据的股 → 资金筛选
        db --set-db-type sqlite                          # 修改全局默认数据库类型
    """
    print_locals()

    global DB_TYPE
    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    # ── 处理 --set-db-type ──
    if set_db_type:
        DB_TYPE = set_db_type
        _CSL.print(f"✅ 全局默认数据库类型已设为: [yellow]{DB_TYPE}[/yellow]")

    # ── 解析 db_type ──
    if db_type is None:
        db_type = DB_TYPE

    # ── --list-stocks：列出表中所有股票代码 ──
    if list_stocks:
        if not table_name:
            _CSL.print("[red]-ls 必须配合 -t 指定表名[/red]")
            return
        trading_date = calc_belong_trading_day(date + timedelta(seconds=1), dividing_line=datetime_time(0, 0, 0))
        trading_date_str = trading_date.strftime('%Y%m%d')
        db_url = _assemble_db_url(db_type, _CFG)
        stocks = _query_table_stocks(db_url, table_name, _CSL, trading_date_str)
        if cache_stocks or _is_pipe_producer:
            return {'stocks': stocks}
        return

    # 纯 --set-db-type 操作（无管道数据 + 无数据需保存），仅修改全局变量后返回
    pipe_data = _ctx.obj.get('_pipe_data', {})
    if not pipe_data:
        if not set_db_type:
            _CSL.print("[red]无管道传入数据[/red]")
            _CSL.print("用法示例: [yellow]gmd -c 100 -s 600000.SH | db -t history_data_1d[/yellow]")
        return

    dfs = pipe_data.get('dfs', {})
    if not dfs:
        _CSL.print("[red]管道数据中未包含 DataFrame（缺少 'dfs' 键）[/red]")
        _CSL.print(f"上游返回的键: {list(pipe_data.keys())}")
        return

    # ── 自动推断目标表名 ──
    if table_name is None:
        _source = pipe_data.get('_source', '')
        if _source == 'stock_metrics':
            table_name = 'stock_metrics'
        elif _source == 'market_data':
            table_name = 'market_data'
        elif pipe_data.get('formula_key'):
            table_name = 'stock_metrics'  # 向后兼容：旧管道无 _source 但有 formula_key
        else:
            table_name = 'history_data_1d'
        _CSL.print(f"[dim]根据管道来源自动选择表: [yellow]{table_name}[/yellow][/dim]")

    # ── stock_metrics：公式指标 JSONB ──
    if table_name == 'stock_metrics':
        period = pipe_data.get('period', '1d')
        dividend_type = pipe_data.get('dividend_type', 1)
        formula_key = pipe_data.get('formula_key', '')
        if not formula_key:
            _CSL.print("[red]管道数据中缺少 formula_key，无法确定指标公式标识[/red]")
            _CSL.print("提示: 请使用 [yellow]formula -t zb -n <公式名> ... | db -t stock_metrics[/yellow]")
            return
        db_url = _assemble_db_url(db_type, _CFG)
        StockMetrics.init_db(db_url)
        StockMetrics.bulk_upsert_from_dfs(dfs, formula_key, period, dividend_type,
                                          db_url, is_replace, console=_CSL)
        return

    # ── market_data：行情 K 线 JSONB ──
    if table_name == 'market_data':
        period = pipe_data.get('period', '1d')
        dividend_type = pipe_data.get('dividend_type', 1)
        db_url = _assemble_db_url(db_type, _CFG)
        MarketData.init_db(db_url)
        MarketData.bulk_upsert_from_dfs(dfs, period, dividend_type,
                                         db_url, is_replace, console=_CSL)
        return

    # ── 其他表：走 ORM（如 history_data_1d）──
    _save_kline_to_db_table(dfs, table_name, db_type, _CFG, is_replace, _CSL)


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
    _CSL = _ctx.obj['console'] # type: Console
    try:
        for stock in stocks:
            code = SecurityCode(stock.upper())
            market_snapshot = tq.get_market_snapshot(stock_code = code.full_code)
            _CSL.print(f"{code.full_code} 的市场快照数据:", market_snapshot)
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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
    _CSL = _ctx.obj['console'] # type: Console
    try:
        return_fields = []
        for full_code in stocks:
            fdc = tq.get_stock_info(stock_code=full_code, field_list=fields)
            _CSL.print(f"{full_code} 基础财务数据:", fdc)

            if (not return_fields) and fdc is not None and isinstance(fdc, dict):
                return_fields = list(fdc.keys())

        _show_return_fields_meaning(STOCK_INFO_DATAFRAME, return_fields)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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
    _CSL = _ctx.obj['console'] # type: Console

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
            _CSL.print(f"没有找到匹配的字段，无法列出字段意义")
            return

    if list_field:
        if matched_fields:
            _show_return_fields_meaning(GMI_INFO_DATAFRAME, matched_fields, printer=_CSL.print)

        else:
            _show_return_fields_meaning(GMI_INFO_DATAFRAME, printer=_CSL.print)

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
                _CSL.print(f"get_more_info({full_code} {get_stock_name(full_code)}): {res}")

        if join_one_table and stocks_info_list:
            df = pd.DataFrame(stocks_info_list, index=stocks)
            print_dataframe(df, title="股票更多信息", show_footer=True, printer=_CSL.print)

        if return_fields:
            _show_return_fields_meaning(GMI_INFO_DATAFRAME, return_fields)
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            df = tq.get_divid_factors(stock_code=full_code, start_time=start_time, end_time=end_time)
            print_dataframe(df, title=f"{full_code} 分红配送数据",
                            show_footer=True, printer=_CSL.print)
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)



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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        count = len(date_list)
        if count:
            for full_code in stocks:
                res = tq.get_gb_info(stock_code=full_code, date_list=date_list, count=count)
                _CSL.print(f"get_gb_info({full_code}): {res}")
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)



@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='可转债代码列表 (如: 123265.SZ)')
@click.pass_context
def get_cb_info(_ctx: click.Context,
    stocks: list[str]
):
    """获取可转债基础数据"""
    _CSL = _ctx.obj['console'] # type: Console
    try:
        for stock in stocks:
            code = SecurityCode(stock.upper())
            cb_info = tq.get_cb_info(stock_code = code.full_code)
            _CSL.print(f"{code.full_code} {code.security_type.value} 的可转债基础数据:", cb_info)
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        ipo_info = tq.get_ipo_info(ipo_type, ipo_date)

        ipo_type_tip = '所有新股申购信息' if (ipo_type == 0) else '所有新发债信息'
        ipo_date_tip = '今天' if (ipo_date == 0) else '今天及以后'
        _CSL.print(f"{ipo_date_tip}{ipo_type_tip}:", ipo_info)
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
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
                                printer=_CSL.print)

        _show_return_fields_meaning(FINANCIAL_DATAFRAME, return_fields)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_gpjy_value(stocks, field_list, start_time, end_time)
        _CSL.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(GPJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_gpjy_value_by_date(stocks, field_list, year, mmdd)
        _CSL.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(GPJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_bkjy_value(stocks, field_list, start_time, end_time)
        _CSL.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(BKJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_bkjy_value_by_date(stocks, field_list, year, mmdd)
        _CSL.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(BKJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_scjy_value(field_list, start_time, end_time)
        _CSL.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0 and isinstance(res, dict):
            return_fields = list(res.keys())

        _show_return_fields_meaning(SCJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_scjy_value_by_date(field_list, year, mmdd)
        _CSL.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0 and isinstance(res, dict):
            return_fields = list(res.keys())

        _show_return_fields_meaning(SCJY_VALUE_DATAFRAME, return_fields)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.get_gp_one_data(stocks, field_list) # type: dict[dict]
        _CSL.print(f"返回: ", res)

        return_fields = []
        if res and len(res) > 0:
            one = res.get(stocks[0])
            if one and isinstance(one, dict):
                return_fields = list(one.keys())

        _show_return_fields_meaning(GP_ONE_DATA_DATAFRAME, return_fields)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)

# ---------------------------------------------------------------------------------------------
# 分类/板块成份股
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@blocks_collector
@click.option('-c', '--contains', 'contains', multiple=True, callback=split_comma, help='包含的字串')
@click.option('-v', '--verbose', 'is_verbose', is_flag=True, help='是否打印详细信息')
@click.pass_context
def get_sector_list(_ctx: click.Context,
    contains: list[str],
    is_verbose: bool,
    cache_stocks: bool,
    stock_group_index: int,
    cache_blocks: bool,
    block_group_index: int,
    **kwargs
):
    """获取A股板块代码列表（通达信板块、概念、行业等88开头的板块）"""
    _CSL = _ctx.obj['console'] # type: Console
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

            if cache_stocks or is_verbose or _is_pipe_producer:
                stocks_in_filtered_sectors = set()
                blocks_in_filtered = set(df_filtered['Code'].tolist())

                # 遍历板块获取成份股，同时填充 stocks.num 和 stocks 列
                stocks_num_col = []
                stocks_list_col = []
                for _, row in df_filtered.iterrows():
                    sector_code = row['Code']
                    res = tq.get_stock_list_in_sector(block_code=sector_code, block_type=0, list_type=1)
                    cnt = len(res) if res else 0
                    stocks_num_col.append(cnt)
                    stocks_list_col.append(
                        [f"{r.get('Code')}|{r.get('Name')}" for r in res if isinstance(r, dict)]
                        if res else []
                    )

                    if (cache_stocks or _is_pipe_producer) and res:
                        stocks_in_filtered_sectors.update([_get(x) for x in res if x])

                df_filtered['stocks.num'] = stocks_num_col
                df_filtered['stocks'] = stocks_list_col

            print_dataframe(df_filtered,
                            title=f'含有 {contains} 的板块（{len(df_filtered)} / {len(df)}）',
                            printer=_CSL.print)

            if cache_stocks or cache_blocks or _is_pipe_producer:
                return {'stocks': stocks_in_filtered_sectors,
                        'blocks': blocks_in_filtered}

        else:
            if _is_pipe_producer:
                return {'blocks': set(df['Code'].tolist())}
            print_dataframe(df, title='板块列表（全量）', print=_CSL.print)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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
    cache_stocks: bool,
    stock_group_index: int,
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

    _CSL = _ctx.obj['console'] # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    try:
        stocks_result = set()
        res = tq.get_stock_list_in_sector(block_code=block_name,
                                        block_type=block_type,
                                        list_type=list_type)
        _CSL.print(f"板块 [yellow]{block_name}[/yellow] 中含有 {len(res)} 只个股：", end='')
        _CSL.print(Pretty(res, max_length=max_to_show) if (res and max_to_show > 0) else res)

        if cache_stocks or _is_pipe_producer:
            if res and isinstance(res, list):
                stocks_result.update(set([_get(x) for x in res if x]))

            return {'stocks': stocks_result}

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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
    cache_stocks: bool,
    stock_group_index: int,
):
    """获取系统分类成份股（通过指定 市场代码 或 市场名称）"""
    print_locals()
    _CSL = _ctx.obj['console'] # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    try:
        if not (markets or market_name_contains) or list_all:
            print_dataframe(_MARKET_NAME_DF, title="市场代码-名称对应表", printer=_CSL.print)
            return

        if market_name_contains:
            df_filtered = check_text_in_column(_MARKET_NAME_DF, '市场名称', market_name_contains)
            print_dataframe(df_filtered, title=f"含有{market_name_contains}的市场", printer=_CSL.print)
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
                            res = [x for x in res if not is_st_stock(x.get('Name', ''))]

                        if stock_name_contains:
                            res = [x for x in res if any(contain_str in x.get('Name', '') for contain_str in stock_name_contains)]

                            _CSL.print(f"市场【代码：{market} 名称：{market_name}】 共 {old_len} 只个股，筛选后剩余 {len(res)} 只：", end='')
                        else:
                            _CSL.print(f"市场【代码：{market} 名称：{market_name}】 共 {len(res)} 只个股：", end='')

                        _CSL.print(Pretty(res, max_length=max_to_show) if max_to_show > 0 else res)

                        if (cache_stocks or _is_pipe_producer) and isinstance(res, list):
                            stocks_result.update([_get(x) for x in res if x])

            if cache_stocks or _is_pipe_producer:
                I(stocks_result_LEN=len(stocks_result))
                return {'stocks': stocks_result}  # 返回就会被 stocks_collector 添加到 cache_cmd.STOCKS 中

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


# ---------------------------------------------------------------------------------------------
# 个股板块归属 & 涨幅统计
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@blocks_collector
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
              default=STOCKS, required=False, help='股票代码列表 (如: 603358.SH)。管道模式下可从上游自动获取')
@click.option('--date', '-d', 'date', type=DATETIME, default=None,
              help='日期（默认：最近一个交易日，9:30 之前算前一个交易日）')
@click.option('--block-type', '-t', 'block_types', multiple=True, default=['概念'],
              type=click.Choice(['概念', '行业', '地域', '风格', '自定义']),
              help='板块类型')
@click.option('--verbose', '-v', 'is_verbose', is_flag=True, help='详细模式（打印每只个股的板块详情）')
@click.option('--max-to-show', '-max', 'max_to_show', default=300, show_default=True, type=int,
              help='最多显示多少条板块记录')
@click.option('--to-file', '-tf', 'to_file', type=str, default=None,
              help='导出到 output/{name}.xlsx（每个 DataFrame 一个 sheet）')
@click.pass_context
def stock_block_stat(_ctx: click.Context,
    stocks: list[str],
    date: datetime | None,
    block_types: list[str],
    is_verbose: bool,
    max_to_show: int,
    to_file: str | None,
    cache_blocks: bool,
    block_group_index: int,
):
    """获取个股涨幅及其所属通达信板块统计

    对每只输入股票：
    1. 获取指定日期的 K 线数据，计算涨幅（(今收-昨收)/昨收 * 100）
    2. 通过 tq.get_relation 获取所属的全部通达信板块
    3. 按板块聚合：统计每个板块下有多少只输入个股，以及板块内个股的均涨幅
    4. 返回 {'blocks': list[str]} 供管道下游消费

    使用示例：
        sbs -s 603358.SH -s 600000.SH              # 指定个股
        gs -m 自选股 | sbs                         # 管道：自选股 → 板块统计
        gsl -c 华为 | sbs                          # 管道：概念板块个股 → 板块统计
    """
    _CSL = _ctx.obj['console']  # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    # 确定交易日期
    if date is None:
        now_dt = datetime.now()
        trading_date = calc_belong_trading_day(now_dt, datetime_time(hour=9, minute=30))  # 9:30 之前算前一个交易日
    else:
        trading_date = date

    trading_date_str = trading_date.strftime('%Y%m%d')

    print_locals()

    try:
        stocks_list = list(stocks)
        if not stocks_list:
            _CSL.print("[red]未提供任何股票代码（请通过 -s 参数、管道上游 或 缓存内存提供）[/red]")
            return

        # ── Step 1: 获取 K 线数据，计算每只个股的涨幅 ──
        progress_print(f"[bold]STEP 1/3[/bold] 获取 {len(stocks_list)} 只个股在 {trading_date_str} 附近的 K 线数据...")
        dict_df = tq.get_market_data(
            field_list=['Close'],
            stock_list=stocks_list,
            end_time=trading_date.strftime('%Y%m%d%H%M%S'),
            count=2,
            dividend_type='front',
            period='1d',
            fill_data=False,
        )  # type: Dict[str, pd.DataFrame] # -- field-first: {'Open': DataFrame(columns=stocks, index=dates)}

        # tq.get_market_data 返回 field-first 结构，需转为 stock-first
        stock_2_df = transform_field_to_stock_fast(dict_df)  # → {stock_code: DataFrame(columns=['Close'], index=dates)}

        stock_change_pct = {}  # stock_code (full_code) → 涨跌幅%
        for full_code, df in stock_2_df.items():
            if df is None or df.empty:
                stock_change_pct[full_code] = None
                continue
            closes = df['Close'].values
            if len(closes) >= 2:
                prev_close = closes[-2]
                today_close = closes[-1]
                if prev_close and prev_close != 0:
                    change_pct = (today_close - prev_close) / prev_close * 100
                    stock_change_pct[full_code] = round(change_pct, 2)
                else:
                    stock_change_pct[full_code] = 0.0
            else:
                stock_change_pct[full_code] = 0.0

        valid_count = sum(1 for v in stock_change_pct.values() if v is not None)
        progress_print(f"   涨幅计算完成：{valid_count}/{len(stocks_list)} 只有效数据")

        # ── Step 2: 获取每只个股的所属板块 ──
        progress_print(f"[bold]STEP 2/3[/bold] 获取个股所属板块...")
        block_to_stocks = defaultdict(list) # 记录每个板块下的个股列表（仅在筛选样本 stocks 中）
        block_2_infos = {}
        stock_details = []  # 用于 verbose 打印

        for _, stock_code in enumerate_with_progress(stocks_list, task_name="获取个股所属板块"):
            code = SecurityCode(stock_code)
            full_code = code.full_code
            short_code = code.short_code

            blocks = tq.get_relation(stock_code=full_code)

            block_infos = [] # 记录该个股的板块信息
            if blocks and isinstance(blocks, list):
                for b in blocks:
                    if not isinstance(b, dict):
                        W("tq.get_relation 返回的板块信息不是 dict，请检查API是否更新", stock_code=full_code, block_info=b)
                        return

                    bc = b.get('BlockCode', '')
                    bn = b.get('BlockName', '')
                    bt = b.get('BlockType', '')
                    gn_num = b.get('GPNume', 0) # 成份股数量
                    if block_types and bt not in block_types:
                        continue # 跳过不在统计范围内的板块

                    if bc not in block_2_infos:
                        block_2_infos[bc] = {
                            'BlockName': bn,
                            'BlockType': bt,
                            'GPNume': gn_num,
                        }

                    block_infos.append('|'.join([bc, bn, bt, str(gn_num)]))

                    block_to_stocks[bc].append(full_code)

            if is_verbose:
                change = stock_change_pct.get(full_code, None)
                stock_details.append({
                    '股票代码': full_code,
                    '股票名称': get_stock_name(full_code, ''),
                    '涨幅%': change if change is not None else np.nan,
                    '所属板块数': len(block_infos),
                    '板块列表': block_infos,
                })

        # ── Step 3: 聚合统计并打印 ──
        progress_print(f"[bold]STEP 3/3[/bold] 聚合板块统计...")
        block_stats = []
        for block_code, stocks_in_block in block_to_stocks.items():
            block_name = block_2_infos.get(block_code, {}).get('BlockName', '')
            changes = [stock_change_pct.get(s) for s in stocks_in_block
                       if stock_change_pct.get(s) is not None]
            avg_change = round(sum(changes) / len(changes), 2) if changes else 0

            # 版块实时更多信息
            block_more_info = tq.get_more_info(stock_code=block_code, field_list=['fHSL', 'fLianB', 'Zjl', 'Zjl_HB'])
            # 板块快照信息
            block_snapshot = tq.get_market_snapshot(stock_code=block_code, field_list=['Inside', 'Outside', 'UpHome', 'DownHome'])

            block_stats.append({
                '板块代码': block_code,
                '板块名称': block_name,
                '板块成分股数量': block_2_infos.get(block_code, {}).get('GPNume', 0),
                '个股数': len(stocks_in_block),
                '均涨幅%': avg_change,
                '涨(家)': block_snapshot.get('UpHome', 0),
                '涨停': block_snapshot.get('Outside', 0),
                '跌(家)': block_snapshot.get('DownHome', 0),
                '跌停': block_snapshot.get('Inside', 0),
                '换手率%': float(block_more_info.get('fHSL', '0')),
                '量比': float(block_more_info.get('fLianB', '0')),
                '主买净额(亿)': float(block_more_info.get('Zjl', '0')) / 10000,
                '主力净额(亿)': float(block_more_info.get('Zjl_HB', '0')) / 10000,
            })

        # 按个股数降序
        block_stats.sort(key=lambda x: x['个股数'], reverse=True)
        df_stats = pd.DataFrame(block_stats)

        _CSL.print(f"\n[bold]📊 板块归属统计[/bold] — 日期: [yellow]{trading_date_str}[/yellow]，"
                      f"个股: [yellow]{len(stocks_list)}[/yellow] 只，"
                      f"涉及板块: [yellow]{len(block_2_infos.keys())}[/yellow] 个")
        print_dataframe(df_stats,
                        title=f"板块聚合（按个股数降序，共 {len(df_stats)} 个板块）",
                        table_max_rows=max_to_show, show_footer=True, printer=_CSL.print,
                        sum_cols=['个股数', '涨(家)', '涨停', '跌(家)', '跌停', '主买净额(亿)', '主力净额(亿)'],
                        avg_cols=['均涨幅%', '换手率%', '量比'])

        if is_verbose:
            df_detail = pd.DataFrame(stock_details)
            print_dataframe(df_detail, title="个股详情", sum_cols=['所属板块数'], avg_cols=['所属板块数', '涨幅%'], table_max_rows=max_to_show,
                            show_footer=True, printer=_CSL.print)

        # ── 导出 xlsx ──
        _export_to_xlsx(to_file, [('板块聚合', df_stats)] +
                        ([('个股详情', pd.DataFrame(stock_details))] if is_verbose else []))

        # ── 管道返回 ──
        if cache_blocks or _is_pipe_producer:
            return {'blocks': list(block_2_infos.keys())}

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


def _export_to_xlsx(filename: str | None, sheets: list[tuple[str, pd.DataFrame]]):
    """导出多 DataFrame 到 output/{filename}.xlsx，每个 tuple 一个 sheet"""
    if not filename or not sheets:
        return
    import os
    os.makedirs('output', exist_ok=True)
    path = os.path.join('output', f"{filename}.xlsx")
    with pd.ExcelWriter(path, engine='openpyxl') as w:
        for sheet_name, df in sheets:
            safe = sheet_name[:31]  # Excel sheet name limit
            df.to_excel(w, sheet_name=safe, index=False)
    I(f"导出: {path}")


# ---------------------------------------------------------------------------------------------
# 个股持仓盈亏统计
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
              default=STOCKS, required=False, help='股票代码列表。管道模式下可从上游自动获取')
@click.option('--date', '-d', 'date', type=DATETIME, default=None,
              help='买入日期（默认：最近一个交易日 15:00 为界）')
@click.option('--end-time', '-et', 'end_time', type=DATETIME, default=None,
              help='结束统计日期（默认：今天）')
@click.option('--daily', '-dl', 'daily', is_flag=True,
              help='逐日输出模式：从买入日起每一天输出一个持仓盈亏 DataFrame')
@click.option('--intraday', '-id', 'intraday', is_flag=True,
              help='日内盈亏曲线（仅 -dl 时生效，需安装 plotext）')
@click.option('--verbose', '-v', 'is_verbose', is_flag=True, help='详细模式（打印每只个股的逐日 K 线明细）')
@click.option('--top', '-top', 'top_n', type=int, default=0, show_default=True,
              help='仅显示涨/跌幅前 N 名（0 表示全部）')
@click.option('--max-to-show', '-max', 'max_to_show', default=200, show_default=True, type=int,
              help='每张表最多显示多少条记录')
@click.option('--to-file', '-tf', 'to_file', type=str, default=None,
              help='导出到 output/{name}.xlsx（每个 DataFrame 一个 sheet）')
@click.pass_context
def stock_stat(_ctx: click.Context,
    stocks: list[str],
    date: datetime | None,
    end_time: datetime | None,
    daily: bool,
    intraday: bool,
    is_verbose: bool,
    top_n: int,
    max_to_show: int,
    to_file: str | None,
    cache_stocks: bool,
    stock_group_index: int,
):
    """统计个股从某日收盘买入后的持仓盈亏表现

    以 --date 当日收盘价为买入成本，计算持有期内每天：
    - 盈亏.收盘（涨幅%）：(当日收盘 - 买入成本) / 买入成本 × 100
    - 盈亏.最高（涨幅%）：(当日最高 - 买入成本) / 买入成本 × 100
    - 盈亏.最低（跌幅%）：(当日最低 - 买入成本) / 买入成本 × 100

    返回 {'stocks': 股票集合} 供管道下游使用。

    使用示例：
        ss -s 603358.SH -d 2026-06-01 -dl              # 每日持仓盈亏表
        gs -m 50 | ss -d 2026-07-01 -top 10            # 全A股7月1日买入，前10名
        ss -s 603358.SH -d 2026-06-01 -v               # 逐 K 线明细
    """
    _CSL = _ctx.obj['console']  # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    # 确定日期范围
    now_dt = datetime.now()
    now_trading_date = calc_belong_trading_day(now_dt, datetime_time(hour=9, minute=30))
    if date is None:
        entry_date = calc_previous_trading_day(now_trading_date, n=1)
    else:
        entry_date = date
    if end_time is None:
        end_date = now_trading_date
    else:
        end_date = end_time

    entry_date_str = entry_date.strftime('%Y%m%d')
    end_date_str = end_date.strftime('%Y%m%d')

    print_locals()

    try:
        stocks_list = list(stocks)
        if not stocks_list:
            _CSL.print("[red]未提供任何股票代码（请通过 -s 参数、管道上游 或 缓存内存提供）[/red]")
            return

        _sheets = []  # 收集导出 sheet
        mode_label = "逐日持仓" if daily else "持仓盈亏"
        _CSL.print(f"\n[bold]📈 {mode_label}统计[/bold] — "
                      f"买入: [yellow]{entry_date_str}[/yellow]，"
                      f"截止: [yellow]{end_date_str}[/yellow]，"
                      f"候选: [yellow]{len(stocks_list)}[/yellow] 只")

        # ── Step 1: 批量获取 K 线 ──
        progress_print(f"[bold]STEP 1/{'3' if daily else '2'}[/bold] 获取 {len(stocks_list)} 只个股的 K 线数据...")
        dict_df = tq.get_market_data(
            field_list=['Close', 'High', 'Low'],
            stock_list=stocks_list,
            start_time=entry_date.strftime('%Y%m%d%H%M%S'),
            end_time=end_date.strftime('%Y%m%d%H%M%S'),
            count=-1,
            dividend_type='front',
            period='1d',
            fill_data=False,
        )
        stock_2_df = transform_field_to_stock_fast(dict_df)  # field-first → stock-first

        # ── 收集所有交易日（取各股索引并集）──
        all_trading_days = set()
        for df in stock_2_df.values():
            if df is not None and not df.empty:
                all_trading_days.update(df.index)
        trading_days = sorted(all_trading_days)
        entry_ts = pd.Timestamp(entry_date)
        trading_days = [d for d in trading_days if d >= entry_ts]

        if not trading_days:
            _CSL.print("[yellow]买入日后无交易数据[/yellow]")
            return

        # ── Step 2: 预计算每只股票的买入成本和逐日累计盈亏 ──
        progress_print(f"[bold]STEP 2/{'3' if daily else '2'}[/bold] 计算持仓盈亏...")
        # stock_pnl[full_code] = {'entry_close': float, 'daily': list of {date, close, close_pnl, high_pnl, low_pnl}}
        stock_pnl = {}
        all_passed = set()

        for _, stock_code in enumerate_with_progress(stocks_list, task_name="计算盈亏"):
            code = SecurityCode(stock_code)
            full_code = code.full_code

            df = stock_2_df.get(full_code)
            if df is None or df.empty:
                continue

            entry_mask = df.index >= entry_ts
            if not entry_mask.any():
                continue
            entry_idx = df.index[entry_mask][0]
            entry_close = float(df.loc[entry_idx, 'Close'])
            if entry_close == 0:
                continue

            post_entry = df.loc[df.index > entry_idx]  # 买入日收盘后，次日开始
            if post_entry.empty:
                continue

            # 逐日累计盈亏
            daily_list = []
            for day_idx, row in post_entry.iterrows():
                daily_list.append({
                    'date': day_idx,
                    'close': float(row['Close']),
                    'close_pnl': round((float(row['Close']) - entry_close) / entry_close * 100, 2),
                    'high_pnl': round((float(row['High']) - entry_close) / entry_close * 100, 2),
                    'low_pnl': round((float(row['Low']) - entry_close) / entry_close * 100, 2),
                })
            stock_pnl[full_code] = {
                'entry_close': entry_close,
                'entry_date': entry_idx,
                'daily': daily_list,
            }
            all_passed.add(full_code)

        if not stock_pnl:
            _CSL.print("[yellow]无有效数据[/yellow]")
            return

        # ── Step 3a: 逐日输出模式 ──
        if daily:
            progress_print(f"[bold]STEP 3/3[/bold] 逐日输出持仓表（共 {len(trading_days)} 个交易日）...")
            for _, day in enumerate(trading_days):
                day_rows = []
                for full_code, info in stock_pnl.items():
                    pnl_list = info['daily']
                    # 找到 <= day 的最新一条
                    day_data = None
                    for d in reversed(pnl_list):
                        if d['date'] <= day:
                            day_data = d
                            break
                    if day_data is None:
                        continue
                    sc = SecurityCode(full_code)
                    entry_close = info.get('entry_close', 0)
                    day_rows.append({
                        '代码': sc.short_code,
                        '名称': get_stock_name(full_code, ''),
                        '买入价': round(entry_close, 2),
                        '收盘': day_data['close'],
                        '盈亏.收盘%': day_data['close_pnl'],
                        '盈亏.最高%': day_data['high_pnl'],
                        '盈亏.最低%': day_data['low_pnl'],
                    })

                if not day_rows:
                    continue

                df_day = pd.DataFrame(day_rows).sort_values('盈亏.收盘%', ascending=False).reset_index(drop=True)
                if top_n > 0:
                    half = top_n // 2 if top_n > 1 else 1
                    df_day = pd.concat([df_day.head(half), df_day.tail(top_n - half)]).drop_duplicates()

                day_str = day.strftime('%Y%m%d') if hasattr(day, 'strftime') else str(day)[:10]
                print_dataframe(df_day,
                                title=f"📅 {day_str} 持仓盈亏（买入日 {entry_date_str}，共 {len(day_rows)} 只）",
                                table_max_rows=max_to_show,
                                avg_cols=['盈亏.收盘%', '盈亏.最高%', '盈亏.最低%'],
                                show_footer=True, printer=_CSL.print)

                # ── 日内盈亏曲线（需 plotext）──
                if intraday and all_passed:
                    _plot_intraday(_ctx, day, all_passed, stock_pnl, _CSL)

                _sheets.append((day_str, df_day))
        else:
            # ── Step 3b: 最终汇总模式 ──
            stock_results = []
            for full_code, info in stock_pnl.items():
                pnl_list = info['daily']
                if not pnl_list:
                    continue
                sc = SecurityCode(full_code)
                first = pnl_list[0]
                latest = pnl_list[-1]
                max_high = max(d['high_pnl'] for d in pnl_list)
                min_low = min(d['low_pnl'] for d in pnl_list)
                high_day = next(d for d in pnl_list if d['high_pnl'] == max_high)
                low_day = next(d for d in pnl_list if d['low_pnl'] == min_low)
                stock_results.append({
                    '代码': sc.short_code,
                    '名称': get_stock_name(full_code, ''),
                    '买入日': first['date'].strftime('%Y%m%d') if hasattr(first['date'], 'strftime') else str(first['date']),
                    '买入价': round(info['entry_close'], 2),
                    '最新收盘': latest['close'],
                    '盈亏.收盘%': latest['close_pnl'],
                    '盈亏.最高%': max_high,
                    '最高日': high_day['date'].strftime('%Y%m%d') if hasattr(high_day['date'], 'strftime') else str(high_day['date']),
                    '盈亏.最低%': min_low,
                    '最低日': low_day['date'].strftime('%Y%m%d') if hasattr(low_day['date'], 'strftime') else str(low_day['date']),
                    '持有天数': len(pnl_list),
                })

            if not stock_results:
                _CSL.print("[yellow]无有效数据[/yellow]")
                return

            df_summary = pd.DataFrame(stock_results).sort_values('盈亏.收盘%', ascending=False).reset_index(drop=True)
            _sheets.append(('持仓盈亏', df_summary))

            if top_n > 0:
                half = top_n // 2 if top_n > 1 else 1
                df_show = pd.concat([df_summary.head(half), df_summary.tail(top_n - half)]).drop_duplicates()
            else:
                df_show = df_summary

            _CSL.print(f"\n统计完成: [green]{len(stock_results)}[/green] / {len(stocks_list)} 只")
            print_dataframe(df_show,
                            title=f"持仓盈亏（共 {len(df_summary)} 只）买入日 {entry_date_str}，截止 {end_date_str}，"
                                  + (f"，显示涨跌前 {top_n} 名" if top_n > 0 else ""),
                            table_max_rows=max_to_show,
                            sum_cols=['持有天数'],
                            avg_cols=['盈亏.收盘%', '盈亏.最高%', '盈亏.最低%'],
                            show_footer=True, printer=_CSL.print)

        # ── verbose: 逐 K 线明细 ──
        if is_verbose:
            for full_code, info in stock_pnl.items():
                pnl_list = info['daily']
                if not pnl_list:
                    continue
                sc = SecurityCode(full_code)
                df_detail = pd.DataFrame(pnl_list).set_index('date')
                df_detail = df_detail.rename(columns={'close_pnl': '盈亏.收盘%', 'high_pnl': '盈亏.最高%', 'low_pnl': '盈亏.最低%'})
                daily_cols = ['close', '盈亏.收盘%', '盈亏.最高%', '盈亏.最低%']
                print_dataframe(df_detail[daily_cols],
                                title=f"{sc.short_code} {get_stock_name(full_code, '')} 逐日明细（共 {len(pnl_list)} 天）",
                                table_max_rows=max_to_show, show_footer=True, printer=_CSL.print)
                _sheets.append((sc.short_code, df_detail[daily_cols]))

        # ── 导出 xlsx ──
        _export_to_xlsx(to_file, _sheets)

        # ── 管道返回 ──
        if cache_stocks or _is_pipe_producer:
            return {'stocks': all_passed}

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


# ---------------------------------------------------------------------------------------------
# 主力资金流筛选
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
              default=STOCKS, required=False, help='股票代码列表。管道模式下可从上游自动获取')
@click.option('--date', '-d', 'date', type=DATETIME, default=None,
              help='日期（默认：最近一个交易日 15:00 为界）')
@click.option('--zm-min', '-zm-min', 'zm_min', type=float, default=None,
              help='主买净额(万元) 最小值（含）')
@click.option('--zm-max', '-zm-max', 'zm_max', type=float, default=None,
              help='主买净额(万元) 最大值（含）')
@click.option('--zl-min', '-zl-min', 'zl_min', type=float, default=None,
              help='主力净流入(万元) 最小值（含）')
@click.option('--zl-max', '-zl-max', 'zl_max', type=float, default=None,
              help='主力净流入(万元) 最大值（含）')
@click.option('--verbose', '-v', 'is_verbose', is_flag=True, help='详细模式（打印每只个股的资金数据）')
@click.option('--with-name', '-wn', 'is_with_name', is_flag=True, help='股票代码带上股票名称（如 603358|华达科技）')
@click.option('--max-to-show', '-max', 'max_to_show', default=200, show_default=True, type=int,
              help='最多显示多少条结果')
@click.pass_context
def filter_capital_flow(_ctx: click.Context,
    stocks: list[str],
    date: datetime | None,
    zm_min: float | None,
    zm_max: float | None,
    zl_min: float | None,
    zl_max: float | None,
    is_verbose: bool,
    is_with_name: bool,
    max_to_show: int,
    cache_stocks: bool,
    stock_group_index: int,
):
    """按主力资金流向筛选个股

    数据来源（根据 --date 自动选择）：
    - 当日 / 最近交易日：通过 get_more_info 实时获取 Zjl / Zjl_HB
    - 历史日期：从 stock_metrics 表查询 L2_DATA 指标（需先运行过 formula -t zb -n L2_DATA --save-db）

    返回 {'stocks': 符合条件的股票集合} 供管道下游使用。

    使用示例：
        fcf -s 603358.SH -zm-min 1000                       # 主买净额 ≥ 1000万
        fcf -zm-min 500 -zl-min 1000 -zm-max 5000           # 双条件范围筛选
        gs -m 50 | fcf -zm-min 1000 -v                      # 管道：全A股 → 资金流筛选
    """
    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    # 确定交易日期 & 判断数据来源
    if date is None:
        now_dt = datetime.now()
        trading_date = calc_belong_trading_day(now_dt, datetime_time(hour=15))
    else:
        trading_date = date

    trading_date_str = trading_date.strftime('%Y%m%d')
    today_str = datetime.now().strftime('%Y%m%d')

    # 是否为实时日期（当日或最近交易日 ≈ 当前）
    is_realtime = (trading_date_str == today_str)

    try:
        stocks_list = list(stocks)
        if not stocks_list:
            _CSL.print("[red]未提供任何股票代码（请通过 -s 参数、管道上游 或 缓存内存提供）[/red]")
            return

        _CSL.print(f"\n[bold]💰 主力资金流筛选[/bold] — 日期: [yellow]{trading_date_str}[/yellow]"
                      f"{' (实时)' if is_realtime else ' (历史 DB)'}，"
                      f"候选: [yellow]{len(stocks_list)}[/yellow] 只")

        passed_stocks = set()
        stock_details = []  # 用于 verbose 打印

        if is_realtime:
            # ── 实时路径：get_more_info ──
            progress_print(f"[bold]实时获取[/bold] {len(stocks_list)} 只个股的资金流数据...")
            for _, stock_code in enumerate_with_progress(stocks_list, task_name="获取主力资金数据"):
                code = SecurityCode(stock_code)
                full_code = code.full_code

                info = tq.get_more_info(stock_code=full_code, field_list=['Zjl', 'Zjl_HB'])
                if not info or not isinstance(info, dict):
                    continue

                zjl_val = _safe_float(info.get('Zjl', '0'))
                zjl_hb_val = _safe_float(info.get('Zjl_HB', '0'))

                if _match_filters(zjl_val, zm_min, zm_max) and \
                   _match_filters(zjl_hb_val, zl_min, zl_max):
                    passed_stocks.add(full_code)

                if is_verbose:
                    stock_details.append({
                        '股票代码': code.short_code,
                        '股票名称': get_stock_name(full_code, ''),
                        '主买净额(万)': zjl_val,
                        '主力净额(万)': zjl_hb_val,
                        '符合条件': full_code in passed_stocks,
                    })
        else:
            # ── 历史路径：stock_metrics DB ──
            progress_print(f"[bold]历史查询[/bold] {len(stocks_list)} 只个股在 {trading_date_str} 的 L2_DATA...")
            db_url = _assemble_db_url(DB_TYPE, _CFG)
            StockMetrics.init_db(db_url)

            for _, stock_code in enumerate_with_progress(stocks_list, task_name="查询 L2_DATA"):
                code = SecurityCode(stock_code)
                full_code = code.full_code

                # 查询主买净额
                rows_zjl = StockMetrics.query(
                    db_url, full_code, '1d',
                    trading_date_str, trading_date_str,
                    dividend_type=1,
                    formula_key='L2_DATA', indicator_key='主买净额')
                # 查询主力净额
                rows_hb = StockMetrics.query(
                    db_url, full_code, '1d',
                    trading_date_str, trading_date_str,
                    dividend_type=1,
                    formula_key='L2_DATA', indicator_key='主力净额')

                zjl_val = _safe_float(rows_zjl[0]['value']) if rows_zjl else 0.0
                zjl_hb_val = _safe_float(rows_hb[0]['value']) if rows_hb else 0.0

                if _match_filters(zjl_val, zm_min, zm_max) and \
                   _match_filters(zjl_hb_val, zl_min, zl_max):
                    passed_stocks.add(full_code)

                if is_verbose:
                    stock_details.append({
                        '股票代码': code.short_code,
                        '股票名称': get_stock_name(full_code, ''),
                        '主买净额(万)': zjl_val,
                        '主力净额(万)': zjl_hb_val,
                        '符合条件': full_code in passed_stocks,
                    })

        # ── 输出结果 ──
        _CSL.print(f"\n筛选结果: [green]{len(passed_stocks)}[/green] / {len(stocks_list)} 只符合条件")

        if is_verbose:
            df_detail = pd.DataFrame(stock_details)
            df_sorted = df_detail.sort_values('主买净额(万)', ascending=False)
            print_dataframe(df_sorted,
                            title=f"个股资金流详情（共 {len(df_sorted)} 条）",
                            show_footer=True, printer=_CSL.print)

        # 打印通过筛选的股票列表
        if passed_stocks:
            _CSL.print(f"符合条件个股: ", end='')
            if is_with_name:
                stocks_to_show = [f"{sc}|{get_stock_name(sc)}" for sc in list(passed_stocks)]
            else:
                stocks_to_show = list(passed_stocks)
            _CSL.print(Pretty(stocks_to_show, max_length=max_to_show))

        # ── 管道返回 ──
        if cache_stocks or _is_pipe_producer:
            return {'stocks': passed_stocks}

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


# ---------------------------------------------------------------------------------------------
# 涨跌停过滤
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
              default=STOCKS, required=False, help='股票代码列表。管道模式下可从上游自动获取')
@click.option('--date', '-d', 'date', type=DATETIME, default=None,
              help='日期（默认：最近一个交易日 9:30 为界）')
@click.option('--keep-zt', '-zt', 'keep_zt', is_flag=True, default=False,
              help='保留涨停股')
@click.option('--keep-not-zt', '-nzt', 'keep_not_zt', is_flag=True, default=False,
              help='保留非涨停股')
@click.option('--keep-dt', '-dt', 'keep_dt', is_flag=True, default=False,
              help='保留跌停股')
@click.option('--keep-not-dt', '-ndt', 'keep_not_dt', is_flag=True, default=False,
              help='保留非跌停股')
@click.option('--without-st', '-nst', 'without_st', is_flag=True, help='排除ST')
@click.option('--verbose', '-v', 'is_verbose', is_flag=True, help='详细模式')
@click.pass_context
def filter_limit(_ctx: click.Context,
    stocks: list[str],
    date: datetime | None,
    keep_zt: bool,
    keep_not_zt: bool,
    keep_dt: bool,
    keep_not_dt: bool,
    without_st: bool,
    is_verbose: bool,
    cache_stocks: bool,
    stock_group_index: int,
):
    """按涨跌停条件筛选个股

    使用通达信取整规则精确计算涨跌停价（calc_limit_price），
    自动识别 主板10% / 科创板20% / 创业板20% / 北交所30%。

    四个开关独立并存，保留满足任一条件的个股：
    -zt 保留涨停股，-nzt 保留非涨停股，-dt 保留跌停股，-ndt 保留非跌停股

    返回 {'stocks': 符合条件的股票集合} 供管道下游使用。

    使用示例：
        fl -s 603358.SH -nzt -ndt                      # 剔除涨跌停
        fl -zt                                         # 仅保留涨停
        fl -zt -ndt                                    # 涨停 + 非跌停 = 涨停未封死
        gs -m 50 | fl -nzt -ndt -v                     # 全A股剔除涨跌停
    """
    _CSL = _ctx.obj['console']  # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    if date is None:
        now_dt = datetime.now()
        trading_date = calc_belong_trading_day(now_dt, datetime_time(hour=9, minute=30))
    else:
        trading_date = date

    trading_date_str = trading_date.strftime('%Y%m%d')

    print_locals()

    try:
        stocks_list = list(stocks)
        if not stocks_list:
            _CSL.print("[red]未提供任何股票代码（请通过 -s 参数、管道上游 或 缓存内存提供）[/red]")
            return

        labels = []
        if keep_zt: labels.append('涨停')
        if keep_not_zt: labels.append('非涨停')
        if keep_dt: labels.append('跌停')
        if keep_not_dt: labels.append('非跌停')
        _CSL.print(f"\n[bold]🚫 涨跌停筛选[/bold] — 日期: [yellow]{trading_date_str}[/yellow]，"
                   f"条件: [yellow]{' + '.join(labels)}[/yellow]，"
                   f"候选: [yellow]{len(stocks_list)}[/yellow] 只")

        # 取近2日 Close 计算涨跌停价
        dict_df = tq.get_market_data(
            field_list=['Close'],
            stock_list=stocks_list,
            end_time=trading_date.strftime('%Y%m%d%H%M%S'),
            count=2,
            dividend_type='front',
            period='1d',
            fill_data=False,
        )
        stock_2_df = transform_field_to_stock_fast(dict_df)

        from difoss_stock_util.stock_util import calc_limit_price
        zt_stocks, dt_stocks, normal_stocks = set(), set(), set()
        st_removed = set()
        kept = set()

        for full_code, df in stock_2_df.items():
            if df is None or df.empty:
                continue

            if without_st and is_st(full_code):
                st_removed.add(full_code)
                continue

            closes = df['Close'].values
            if len(closes) < 2:
                continue
            prev_close = float(closes[-2])
            today_close = float(closes[-1])
            if prev_close == 0:
                continue
            sc = SecurityCode(full_code)

            is_zt = today_close >= calc_limit_price(prev_close, sc.short_code, is_limit_up=True)
            is_dt = today_close <= calc_limit_price(prev_close, sc.short_code, is_limit_up=False)

            if is_zt:
                zt_stocks.add(full_code)
            if is_dt:
                dt_stocks.add(full_code)
            if not is_zt and not is_dt:
                normal_stocks.add(full_code)

            # 四个开关独立，满足任一条件即保留
            if (keep_zt and is_zt) or \
               (keep_not_zt and not is_zt) or \
               (keep_dt and is_dt) or \
               (keep_not_dt and not is_dt):
                kept.add(full_code)

        _CSL.print(f"涨停: [red]{len(zt_stocks)}[/red] 只（保留 {len(zt_stocks & kept)}），"
                   f"跌停: [green]{len(dt_stocks)}[/green] 只（保留 {len(dt_stocks & kept)}），"
                   f"正常: [dim]{len(normal_stocks)}[/dim] 只，"
                   + (f"ST剔除: [magenta]{len(st_removed)}[/magenta] 只，" if st_removed else "") +
                   f"最终保留: [yellow]{len(kept)}[/yellow] 只")

        if is_verbose and st_removed:
            _CSL.print(f"ST剔除股: {list(st_removed)[:20]}")
        if is_verbose and zt_stocks:
            _CSL.print(f"涨停股: {list(zt_stocks)[:20]}")
        if is_verbose and dt_stocks:
            _CSL.print(f"跌停股: {list(dt_stocks)[:20]}")

        if cache_stocks or _is_pipe_producer:
            return {'stocks': kept}

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


def _plot_intraday(_ctx, day, stock_codes: set, stock_pnl: dict, _CSL: Console):
    """绘制日内盈亏曲线（5分钟K线），需 plotext"""
    try:
        import plotext as plt
    except ImportError:
        _CSL.print("[yellow]⚠ 需要安装 plotext: pip install plotext[/yellow]")
        return

    day_str = day.strftime('%Y%m%d') if hasattr(day, 'strftime') else str(day)[:10]

    stocks_list = list(stock_codes)
    if not stocks_list:
        return

    # 取1分钟K线（仅支持 count 模式，start_time/end_time 对分钟线无效）
    dict_df = tq.get_market_data(
        field_list=['Close'],
        stock_list=stocks_list,
        period='1m', count=240,
        dividend_type='front', fill_data=False,
    )
    if not dict_df:
        _CSL.print("[yellow]⚠ 无日内分钟线数据（可能需先 refresh_kline -p 1m）[/yellow]")
        return
    stock_2_df = transform_field_to_stock_fast(dict_df)

    # 仅保留目标日期的分钟线
    target_date = pd.Timestamp(day.date() if hasattr(day, 'date') else day)
    curves = {}
    for full_code, df in stock_2_df.items():
        if df is None or df.empty:
            continue
        df_day = df[df.index.normalize() == target_date]
        if df_day.empty:
            continue
        info = stock_pnl.get(full_code, {})
        entry_close = info.get('entry_close', 0)
        if entry_close == 0:
            continue
        closes = df_day['Close'].values
        curves[full_code] = [(c - entry_close) / entry_close * 100 for c in closes]

    if not curves:
        _CSL.print("[yellow]无日内数据[/yellow]")
        return

    # 计算平均曲线
    max_len = max(len(v) for v in curves.values())
    avg_curve = [0.0] * max_len
    for i in range(max_len):
        vals = [c[i] for c in curves.values() if i < len(c)]
        avg_curve[i] = sum(vals) / len(vals) if vals else 0.0

    # 选表现最极端的 top N（按当日振幅排序）用于单独曲线
    amp = [(code, max(curve) - min(curve)) for code, curve in curves.items()]
    amp.sort(key=lambda x: x[1], reverse=True)
    top_stocks = [code for code, _ in amp[:12]]

    plt.clear_figure()
    plt.theme('dark')
    plt.title(f'{day_str} 日内盈亏曲线 (5m)')
    plt.xlabel('时间')
    plt.ylabel('盈亏%')

    colors = ['cyan', 'green', 'yellow', 'magenta', 'red', 'blue',
              'white', 'orange', 'teal', 'gold', 'pink', 'lime']
    for i, code in enumerate(top_stocks):
        curve = curves[code]
        sc = SecurityCode(code)
        label = f"{sc.short_code}"
        plt.plot(curve, label=label, color=colors[i % len(colors)])

    # 平均线（粗白线）
    plt.plot(avg_curve, label='AVG', color='white', linewidth=2)

    plt.canvas_color('black')
    plt.axes_color('black')
    plt.ticks_color('white')
    plt.show()
    _CSL.print(f"[dim]曲线数: {len(top_stocks)} + AVG（共 {len(curves)} 只）[/dim]")


def _safe_float(val) -> float:
    """安全转换为 float，处理 None / str / 空字符串"""
    if val is None or val == '':
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _match_filters(value: float, vmin: float | None, vmax: float | None) -> bool:
    """检查 value 是否在 [vmin, vmax] 范围内（None 表示无限制）"""
    if vmin is not None and value < vmin:
        return False
    if vmax is not None and value > vmax:
        return False
    return True


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
    _CSL = _ctx.obj['console'] # type: Console
    try:
        res = tq.order_stock(account=account, stock_code=full_code,
            order_type=order_type, order_volume=order_volume,
            price_type=price_type, price=price,
            strategy_name=strategy_name, order_remark=order_remark)

        _CSL.print(f"下单 {full_code} 结果: {res}")
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)

# ---------------------------------------------------------------------------------------------
# 自选股/自定义板块
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('-c', '--contains', 'contains', multiple=True, callback=split_comma, help='包含的字串')
@click.option('-v', '--verbose', 'is_verbose', is_flag=True, help='是否打印详细信息')
@click.option('-max', '--max-to-show', 'max_to_show', default=20, show_default=True, type=int, help='最多显示多少只股票（仅 is_verbose=True 时有效）')
@click.pass_context
def get_user_sector(
    _ctx: click.Context,
    contains: list[str], # 用于查找
    is_verbose: bool,
    max_to_show: int,
    cache_stocks: bool,
    stock_group_index: int,
    **kwargs,
):
    """获取自定义板块列表

    管道返回 {'stocks': set[str], 'user_blocks': list[{'Code': ..., 'Name': ...}]}
    user_blocks 与标准 blocks (88XXXX.SH) 不同，是用户自定义板块的 Code/Name 对。
    """
    _CSL = _ctx.obj['console'] # type: Console
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

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
                    _CSL.print(f"自定义板块（过滤含有 {contains} ）共 {len(sectors_filtered)} / {len(sectors)} 个。" )
                else:
                    _CSL.print(f"未发现包含 {contains} 的自定义板块。")
                    return
            else:
                _CSL.print(f"自定义板块，共 {len(sectors)} 个。")

            # 管道收集：板块 {Code, Name} + 板块内的个股
            user_blocks = []
            all_stocks_in_sectors = set()

            sector_detail_infos = []
            for sector_info in sectors_filtered if sectors_filtered else sectors:
                _code = sector_info.get('Code', '')
                _name = sector_info.get('Name', '')
                _stocks_in_sector = tq.get_stock_list_in_sector(block_code=_code, block_type=1, list_type=1)
                _stocks_num = len(_stocks_in_sector) if _stocks_in_sector else 0

                _detail_info = {**sector_info, 'stock.num': _stocks_num}
                if is_verbose:
                    _detail_info.update({"Stocks": [f"{stock.get('Code', '')}|{stock.get('Name', '')}" for stock in _stocks_in_sector]})
                sector_detail_infos.append(_detail_info)

                # 管道：收集板块和个股
                if cache_stocks or _is_pipe_producer:
                    if _code:
                        user_blocks.append({'Code': _code, 'Name': _name})
                    if _stocks_in_sector:
                        all_stocks_in_sectors.update([_get(x) for x in _stocks_in_sector if x])

            # 创建 DataFrame 并按 stock.num 排序
            df = pd.DataFrame(sector_detail_infos)
            df_sorted = df.sort_values(by='stock.num', ascending=False)
            print_dataframe(df_sorted, f'自定义板块概要{f"（过滤含有 {contains} 的板块）" if sectors_filtered else ""}',
                            printer=_CSL.print)

            # ── 管道返回 ──
            if cache_stocks or _is_pipe_producer:
                return {'stocks': all_stocks_in_sectors,
                        'user_blocks': user_blocks}
        else:
            _CSL.print(f"未发现自定义板块")
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)



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
    cache_stocks: bool,
    stock_group_index: int,
):
    """获取自定义板块中的股票列表（需要先使用 get_user_sector 获取板块列表）"""
    _CSL = _ctx.obj['console'] # type: Console
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
                _CSL.print(f"匹配到的板块（包含 {abbrev} 的板块名称）：{filtered_sectors}")
            if name:
                filtered_sectors.extend([{'Code': c, 'Name': n} for c, n in sectors_code2name.items() if name in n])
                _CSL.print(f"匹配到的板块（包含 {name} 的板块名称）：{filtered_sectors}")

            if abbrev or name:

                stocks_in_filtered_sectors = set()

                _CSL.print(f"已匹配到的板块列表 {len(filtered_sectors)} / {len(sectors)}: {filtered_sectors}")

                for f_sector in filtered_sectors:
                    _code = f_sector['Code']

                    _stocks = tq.get_stock_list_in_sector(block_code=_code, block_type=1, list_type=0)

                    _CSL.print(f"板块代码 {_code} 内有 {len(_stocks)} 只个股:", end='')
                    if is_with_name:
                        stocks_with_name = [f"{code}|{get_stock_name(code)}" for code in _stocks]
                        _CSL.print(Pretty(stocks_with_name, max_length=max_to_show) if max_to_show > 0 else stocks_with_name)
                    else:
                        _CSL.print(Pretty(_stocks, max_length=max_to_show) if max_to_show > 0 else _stocks)

                    if show_on_tdx:
                        tq.send_user_block(block_code=_code, stock_list=_stocks, show=True) # 把最后一个显示在客户端

                    if cache_stocks or _is_pipe_producer:
                        stocks_in_filtered_sectors.update(set([_get(x) for x in _stocks if x]))

                if cache_stocks or _is_pipe_producer:
                        return {'stocks': stocks_in_filtered_sectors}
            else:
                _CSL.print(f"自定义板块列表（共 {len(sectors)} 个）: ", end='')
                _CSL.print(Pretty(sectors))

            # 当 action == get 时，-cs 参数可存储板块中的个股到 cache_cmd.STOCKS 中，供后续命令使用
            if cache_stocks or _is_pipe_producer:
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

            tq.send_user_block(block_code=code, stock_list=stocks, show=show_on_tdx)

            _CSL.print(f"已将 {len(stocks)} 只个股添加到自定义板块【代码：{code} 名称：{name}】中")

        elif action == 'create':
            if not name:
                E("创建自定义板块需要指定 --name 参数")
                return
            if not abbrev:
                abbrev = convert_block_name_2_code(name)
                I(自动生成板块简称=abbrev)

            is_new = False
            existing_code = None
            if abbrev in sectors_code2name:
                W(f"板块简称 [yellow]{abbrev}[/yellow] 已存在（{sectors_code2name[abbrev]}）")
                existing_code = abbrev
            elif name in sectors_name2code:
                W(f"板块名称 [yellow]{name}[/yellow] 已存在（简称：{sectors_name2code[name]}）")
                existing_code = sectors_name2code[name]
            else:
                create_res = tq.create_sector(block_code=abbrev, block_name=name)
                I(create_res=create_res)
                _CSL.print(f"✅ 已创建自定义板块【简称：{abbrev} 名称：{name}】")
                is_new = True
                existing_code = abbrev

            if stocks and existing_code:
                if is_new:
                    tq.send_user_block(block_code=existing_code, stock_list=stocks, show=show_on_tdx)
                    _CSL.print(f"   已添加 {len(stocks)} 只个股到新板块")
                else:
                    label = sectors_code2name.get(existing_code, existing_code)
                    if click.confirm(f"是否将 {len(stocks)} 只个股追加到已有板块【{label}】？", default=True):
                        tq.send_user_block(block_code=existing_code, stock_list=stocks, show=show_on_tdx)
                        _CSL.print(f"   已添加 {len(stocks)} 只个股到该板块")

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
                    _CSL.print(f"已从自定义板块【代码：{code} 名称：{name}】中删除 {len(stocks)} 只个股，剩余 {len(remained_stocks)} 只个股: ", end='')
                    _CSL.print(Pretty(list(remained_stocks), max_length=max_to_show) if max_to_show > 0 else list(remained_stocks))
                else:
                    _CSL.print(f"[pink] 未指定需要从板块中删除的个股，请带上 -s 参数指定要删除的个股 [/pink]")
                    _CSL.print(f"自定义板块【代码：{code} 名称：{name}】中共有 {len(_stocks)} 只个股: ", end='')
                    _CSL.print(Pretty(_stocks, max_length=max_to_show) if max_to_show > 0 else _stocks)
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
                tq.send_user_block(block_code=code, stock_list=keep_stocks, show=show_on_tdx)  # 再把过滤掉 ST 后的个股发送到客户端

                _CSL.print(f"已从自定义板块【代码：{code} 名称：{name}】中删除 ST 的个股共 {len(_stocks) - len(keep_stocks)} 只: ", end='')
                _CSL.print(Pretty(st_stocks, max_length=max_to_show) if max_to_show > 0 else st_stocks)


        elif action == 'clear':
            filtered_sectors = []
            if abbrev:
                filtered_sectors.extend([{'Code': c, 'Name': n} for c, n in sectors_code2name.items() if abbrev in c])
                _CSL.print(f"匹配到的板块（包含 {abbrev} 的板块名称）：{filtered_sectors}")
            if name:
                filtered_sectors.extend([{'Code': c, 'Name': n} for c, n in sectors_code2name.items() if name in n])
                _CSL.print(f"匹配到的板块（包含 {name} 的板块名称）：{filtered_sectors}")

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
                    _CSL.print("⚠️ 接下来删除余下的自定义板块", style=Style(color="yellow", bold=True))
                    clear_all = True

                click.confirm(f"确定要清空自定义板块【代码：{code} 名称：{name}】中的个股吗？", abort=True)

                _CSL.print(f"已清空自定义板块【代码：{code} 名称：{name}】中的个股")

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

            name1 = sectors_code2name.get(code1)
            name2 = sectors_code2name.get(code2)

            _CSL.print(f"仅在 {name1} 中的个股（共 {len(only_in_1)} 只）: ", end='')
            _CSL.print(Pretty(list(only_in_1), max_length=max_to_show) if max_to_show > 0 else list(only_in_1))

            _CSL.print(f"仅在 {name2} 中的个股（共 {len(only_in_2)} 只）: ", end='')
            _CSL.print(Pretty(list(only_in_2), max_length=max_to_show) if max_to_show > 0 else list(only_in_2))

            _CSL.print(f"同时在 {name1} 和 {name2} 中的个股（共 {len(in_both)} 只）: ", end='')
            _CSL.print(Pretty(list(in_both), max_length=max_to_show) if max_to_show > 0 else list(in_both))


    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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

    _CSL = _ctx.obj['console']  # type: Console

    try:
        res = tq.get_trading_dates(market='SH', start_time=start_time, end_time=end_time, count=count)
        _CSL.print(f"{res}")
        return res

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)

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
# 2026-6-30 新参数：字段过滤，用于筛选输出指标列名（替代原来的 --keep-output）
@click.option('--field-exclusion', '-fe', 'field_exclusions', multiple=True, callback=split_comma,
              help='需要从输出中剔除的指标列名（可多选）')
@click.option('--field-regex-exclusion', '-fre', 'field_regex_exclusions', multiple=True, callback=split_comma,
              default=[r'^OUTPUT\d+'], show_default=True,
              help='需要从输出中剔除的指标列名的正则表达式（可多选），默认排除 OUTPUT 开头的字段')
@click.option('--field-inclusion', '-fi', 'field_inclusions', multiple=True, callback=split_comma,
              help='需要从输出中包含的指标列名（可多选）')
@click.option('--field-regex-inclusion', '-fri', 'field_regex_inclusions', multiple=True, callback=split_comma,
              help='需要从输出中包含的指标列名的正则表达式（可多选）')
@click.option('--jump-tdx', '-j', 'jump_tdx', type=float, default=None,
              help='跳转通达信界面并等待指定秒数（以获得L2指标数据），不指定时不跳转')
@click.option('--save-db/--no-save-db', '-sdb', 'is_save_db', is_flag=True,
              help='每获取完一只股票立即入库（边跑边存），无需通过 | db 管道')
@click.option('--replace', '-r', 'is_replace', is_flag=True,
              help='入库时替换已有记录（默认 merge，仅与 -sdb 配合生效）')
@click.option('--with-name', '-wn', 'is_with_name', is_flag=True, help='股票代码是否带上股票名称')
@trace_function
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
    field_exclusions: list[str],
    field_regex_exclusions: list[str],
    field_inclusions: list[str],
    field_regex_inclusions: list[str],
    jump_tdx: float | None,
    is_save_db: bool,
    is_replace: bool,
    is_with_name: bool,
    **kwargs,
):
    """调用通达信公式进行计算（技术指标zb/条件选股xg/专家系统exp）公式

    支持：
    - 【指标公式】筛选（-fre参数默认过滤 OUTPUT* 等无意义的字段）、入库、管道输出等功能；
    - 【选股公式】列出所有可用公式、查找公式、获取公式详细信息等功能，
    但不支持选股后直接存于tdx自定义板块中（请使用 formula_multi 命令）。
    如果要入库带有 L2数据的指标数据，请做好以下准备：
    1. 在配置文件中配置数据库连接信息（[db] 节）和启动数据库服务；
    2. 通达信页面需跳转到任意一只个股，并设置周期是【月K】（否则无法拿到尽可能多的指标数据）。
    """
    print_locals()

    _CSL = _ctx.obj['console'] # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict
    _is_pipe_producer = _ctx.obj.get('_pipe_producer', False)

    if not stocks:
        _CSL.print("⚠️ 股票列表为空，请使用 -s/--stock （或在 memory-cache 命令中缓存）指定。")
        return

    _ft_name = {
        'zb': '技术指标',
        'xg': '条件选股',
        'exp': '专家系统'
    }.get(formula_type)

    _ft_int = {'zb': 0, 'xg': 1, 'exp': 2}.get(formula_type)

    # ── 类型特征标志（一次性解析，后续不再判断 formula_type 字符串） ──
    _is_zb = (formula_type == 'zb')
    _is_xg = (formula_type == 'xg')
    _is_exp = (formula_type == 'exp')

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
                print_dataframe(_all_formula_df, title=title, table_max_rows=max_to_show, printer=_CSL.print)
            else:
                _CSL.print(f"未找到合符条件的 {_ft_name} 公式。")

            if verbose:
                for formula_info in res:
                    _f_name = formula_info.get('acName', '')
                    _f_code = formula_info.get('acCode', '')
                    formula_detail_info = tq.formula_get_info(formula_type=_ft_int, formula_code=_f_code)
                    _CSL.print(f"{_ft_name} 公式 {_f_name}（{_f_code}）的详细信息:")
                    _CSL.print(Pretty(formula_detail_info))

            return

        # ── 阶段2: 请求参数准备 ──
        trading_dates = tq.get_trading_dates(market='SH', start_time='', end_time='', count=count)
        _CSL.print(f"len(trading_dates) = {len(trading_dates)}")
        if verbose:
            _CSL.print(f"trading_dates = ", end='')
            _CSL.print(Pretty(trading_dates, max_length=max_to_show))

        # --save-db 且非管道/非 verbose 时不累加全量内存（边跑边存已落盘每只个股）
        _should_accumulate = not (is_save_db and _is_zb and not verbose and not _is_pipe_producer)
        code_2_value = {} if (_should_accumulate and (_is_xg or _is_exp)) else None
        code_2_df = {} if (_should_accumulate and _is_zb) else None

        # ── 阶段3: 逐股票调用 ──
        formula_arg = ','.join(args)
        formula_key = f"{name}|{','.join(args)}" if args else name

        # 准备工作：预先计算 DB URL（供 -sdb 边跑边存用）
        _db_url = _assemble_db_url(DB_TYPE, _CFG) if is_save_db else None
        if _db_url:
            StockMetrics.init_db(_db_url)

        for stock_idx, full_code in enumerate_with_progress(stocks, task_name="逐个股票调用公式", console=_CSL):
            # NOTICE: 通达信缺陷：L2 数据需要软件先跳转（触发界面拉取后）才能获取，不然全是 0 值
            # 跳转逻辑：首只在循环内跳转，后续在上一轮末尾已提前跳转
            if jump_tdx is not None and stock_idx == 0:
                tq.exec_to_tdx(url=f"http://www.treeid/code_{full_code[:6]}")
                sleep(jump_tdx)

            formula_set_res = tq.formula_set_data_info(stock_code=full_code, stock_period=period,
                                                       count=count, dividend_type=dividend_type)
            if isinstance(formula_set_res, dict):
                if int(formula_set_res.get('ErrorId', '-1')) != 0:
                    _CSL.print(f"[ERROR] formula_set_res(): {formula_set_res}")
                    break

            # 调用公式 API（类型分发）
            if _is_zb:
                formula_res = tq.formula_zb(formula_name=name, formula_arg=formula_arg, xsflag=xs_flag)
            elif _is_xg:
                formula_res = tq.formula_xg(formula_name=name, formula_arg=formula_arg)
            else:  # _is_exp
                formula_res = tq.formula_exp(formula_name=name, formula_arg=formula_arg)

            if verbose:
                _CSL.print(f"{full_code} {get_stock_name(full_code)} "
                              f"在{_ft_name} {name} 值: {json.dumps(formula_res, indent=2, ensure_ascii=False)}")

            # 提取 value_of_res（所有类型共用）
            value_of_res = {}
            if formula_res and isinstance(formula_res, dict) and int(formula_res.get('ErrorId', -1)) == 0:
                value_of_res = formula_res.get('Value', {})
                if value_of_res and isinstance(value_of_res, dict):
                    # 应用字段过滤（包含/排除，用于筛选输出指标列名）
                    # 排除包含指定字符串的字段名
                    for fe in (field_exclusions or []):
                        value_of_res = {k: v for k, v in value_of_res.items() if fe not in k}
                    # 正则排除字段名
                    for fre in (field_regex_exclusions or []):
                        try:
                            value_of_res = {k: v for k, v in value_of_res.items() if not re.search(fre, k)}
                        except re.error as re_err:
                            E(正则出错=f"{re_err}", field_regex_exclusions=field_regex_exclusions, err_fre=fre)
                            return
                    # 包含指定字符串的字段名
                    if field_inclusions:
                        included = {}
                        for fi in field_inclusions:
                            included.update({k: v for k, v in value_of_res.items() if fi in k})
                        value_of_res = included
                    # 正则包含字段名
                    if field_regex_inclusions:
                        included = {}
                        for fri in field_regex_inclusions:
                            try:
                                included.update({k: v for k, v in value_of_res.items() if re.search(fri, k)})
                            except re.error as re_err:
                                E(正则出错=f"{re_err}", field_regex_inclusions=field_regex_inclusions, err_fri=fri)
                                return
                        value_of_res = included

                    if code_2_value is not None:
                        code_2_value[full_code] = value_of_res

            # 构建每股票 DataFrame（所有类型统一处理）
            if value_of_res:
                value_of_res_VALUES_LIST = list(value_of_res.values())
                cnt_of_res = len(value_of_res_VALUES_LIST[0])

                if verbose:
                    _CSL.print(f"指标有{len(value_of_res)}个数：{value_of_res.keys()}，涵盖 {cnt_of_res} 天")

                if cnt_of_res < count:
                    _CSL.print(f"⚠️ 返回指标天数 < 请求的数量({count})")

                valid_cnt = min(cnt_of_res, len(trading_dates))
                df = pd.DataFrame(value_of_res, index=pd.to_datetime(trading_dates[-cnt_of_res:]))

                # 过滤掉"有效数据出现之前的无效行"
                is_invalid_row = (df.isna()) | (df == 0) | (df == '')
                valid_mask = is_invalid_row.all(axis=1).cumprod().astype(bool)
                df_cleaned = df[~valid_mask]

                if verbose:
                    if not df.empty:
                        print_dataframe(df,
                                        title=f"{full_code} {get_stock_name(full_code)} 在{_ft_name} {name} 的输出（未过滤空值）",
                                        table_max_rows=max_to_show, printer=_CSL.print, sep='_')

                # zb 始终打印每股票详情；xg 仅在 verbose 时打印
                if _is_zb or verbose:
                    if not df_cleaned.empty:
                        if is_save_db:
                            # 存数据库时尽量进行复杂打印以节省时间
                            _CSL.print(df_cleaned)
                        else:
                            print_dataframe(df_cleaned,
                                            title=f"{full_code} {get_stock_name(full_code)} 在{_ft_name} {name} 的输出（已过滤空值）",
                                            table_max_rows=max_to_show, printer=_CSL.print, sep='_')

                if code_2_df is not None:
                    code_2_df[full_code] = df_cleaned if not df_cleaned.empty else df

                # ── 准备下一轮：跳转下一页 → 落盘当前 → 补足 sleep ──
                if stock_idx + 1 < len(stocks):
                    _t0 = None
                    if jump_tdx is not None:
                        tq.exec_to_tdx(url=f"http://www.treeid/code_{stocks[stock_idx + 1][:6]}")
                        _t0 = time()

                    # 落盘当前股票（在页面加载期间进行）
                    if is_save_db and _is_zb and not df_cleaned.empty:
                        StockMetrics.bulk_upsert_from_dfs(
                            {full_code: df_cleaned}, formula_key, period,
                            dividend_type, _db_url, replace=is_replace, console=_CSL)

                    # 若落盘耗时 < jump_tdx，补足剩余等待时间
                    if _t0 is not None:
                        _elapsed = time() - _t0
                        if _elapsed < jump_tdx:
                            sleep(jump_tdx - _elapsed)
                else:
                    # 最后一只股票：直接落盘
                    if is_save_db and _is_zb and not df_cleaned.empty:
                        StockMetrics.bulk_upsert_from_dfs(
                            {full_code: df_cleaned}, formula_key, period,
                            dividend_type, _db_url, replace=is_replace, console=_CSL)

        # ── 阶段4: 结果输出（类型分发） ──
        if verbose and code_2_value is not None:
            _CSL.print(f"code_2_value = {code_2_value}")

        if _is_zb:
            if code_2_df is not None:
                formula_key = f"{name}|{','.join(args)}" if args else name
                return {'dfs': code_2_df, 'period': period,
                        'formula_key': formula_key, 'dividend_type': dividend_type,
                        '_source': 'stock_metrics'}
            # --save-db 边跑边存模式：无需返回巨量数据
            return

        # xg / exp 使用聚合输出
        if _is_xg:
            res_df = _trans_xg_data_to_date2stocks(code_2_value, trading_dates,
                                                    field_be_counted='OUTPUT1',
                                                    is_with_name=is_with_name)
            print_dataframe(res_df, title='选股结果', flatten_list=True,
                            exclude_cols=['stocks'] if is_with_name else [],
                            printer=_CSL.print)
        elif _is_exp:
            res_df = _trans_xg_data_to_date2stocks(code_2_value, trading_dates,
                                                    field_be_counted='ENTERLONG',
                                                    is_with_name=is_with_name)
            print_dataframe(res_df, title='专家系统 买入信号（ENTERLONG）统计结果',
                            exclude_cols=['stocks'] if is_with_name else [],
                            printer=_CSL.print)

            res_df = _trans_xg_data_to_date2stocks(code_2_value, trading_dates,
                                                    field_be_counted='EXITLONG',
                                                    is_with_name=is_with_name)
            print_dataframe(res_df, title='专家系统 卖出信号（EXITLONG）统计结果',
                            exclude_cols=['stocks'] if is_with_name else [],
                            printer=_CSL.print)

        if verbose:
            _CSL.print(f"res_df = ", end='')
            _CSL.print(Pretty(res_df))

        # stocks_on_date = _trans_xg_data_to_date2stocks(df)
        # for date, stocks in stocks_on_date.items():
        #     if stocks:  # 只显示有股票的日期
        #         print(f"{date}: {stocks} (共{len(stocks)}只股票)")
        #     else:
        #         print(f"{date}: []")

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)




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
@click.option('--save-db/--no-save-db', '-sdb', 'is_save_db', is_flag=True,
              help='每只股票结果立即入库（边跑边存），无需通过 | db 管道（仅 -t zb 生效）')
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
    is_save_db: bool,
    cache_stocks: bool,
    stock_group_index: int,
    cache_df: bool,
    **kwargs,
):
    """批量通达信选股公式"""
    # 注：无需使用formula_set_data和formula_set_data_info提前设置，formula_set_data和formula_set_data_info的设置也对批量调用不生效

    start_time = start_time.strftime('%Y%m%d%H%M%S') if start_time else None
    end_time = end_time.strftime('%Y%m%d%H%M%S') if end_time else None

    if start_time or end_time:
        count = 0

    print_locals()

    _CSL = _ctx.obj['console'] # type: Console
    _CFG = _ctx.obj['cfg'] # type: dict
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

            print_dataframe(mul_res_df, title=f"批量调用选股公式结果", printer=_CSL.print)

            stocks_on_date = set()
            if is_save_user_sector or cache_stocks:
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
                            tq.send_user_block(block_code=block_code, stock_list=stocks, show=True)

                            _CSL.print(f"{date} 选出 {len(stocks)} 只股票，存于自定义板块 [yellow]{usr_block_name}[/yellow] 内。")

                    if cache_stocks or _is_pipe_producer:
                        stocks_on_date.update(stocks)

                if cache_stocks or _is_pipe_producer:
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
                _CSL.print(f"批量调用指标公式结果: ", end='')
                _CSL.print(Pretty(mul_res, max_length=200))

                # 把完整的结果保存到文件中
                with open(f"output/RESULT-{'.'.join(stocks)}-zb_{name}({formula_arg}).json", 'w+', encoding='utf-8') as F:
                    F.write(json.dumps(mul_res, ensure_ascii=False, indent=2))
                    F.flush()

            # 方法1：转换为长格式DataFrame
            df_long = _zb_multi_result_to_dataframe(mul_res, index=None)

            # 检查转换后的DataFrame是否为空
            if df_long.empty:
                _CSL.print(f"[yellow]公式 {name} 返回的数据为空[/yellow]")
                return

            # 处理 exclude/include fields
            required_cols = ['stock_code', 'date'] # 必要的列（始终保留）

            for fe in (field_exclusions or []):
                df_long = df_long.loc[:, ~df_long.columns.str.contains(fe, na=False)]
            for fre in (field_regex_exclusions or []):
                try:
                    df_long = df_long.loc[:, ~df_long.columns.str.contains(fre, regex=True, na=False)]
                except re.error as re_err:
                    E(正则出错=f"{re_err}", field_regex_exclusions=field_regex_exclusions, err_fre=fre)
                    return

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
                    try:
                        matched = df_long.columns[df_long.columns.str.contains(fri, regex=True, na=False)].tolist()
                        matched_cols.extend(matched)
                    except re.error as re_err:
                        E(正则出错=f"{re_err}", field_regex_inclusions=field_regex_inclusions, err_fri=fri)
                        return

                cols_to_keep = list(set(required_cols + matched_cols))
                # 只保留实际存在的列
                cols_to_keep = [col for col in cols_to_keep if col in df_long.columns]
                df_long = df_long[cols_to_keep]

            if output_style == 'long':
                print_dataframe(df_long, title="方法1：长格式DataFrame", sum_cols=sum_columns, printer=_CSL.print)
            elif output_style == 'field':
                # 方法2：转换为透视表（每个指标一个表）
                _CSL.print("透视表格式（每个指标一个表）")
                pivot_dfs = _zb_multi_result_to_pivot(df_long)
                for indicator, pivot_df in pivot_dfs.items():
                    print_dataframe(pivot_df, title=f"指标: {indicator}", sum_cols=sum_columns, printer=_CSL.print)
            elif output_style == 'stock':
                # 方法3：转换为以股票为第一层的DataFrame
                _CSL.print("以股票为第一层的DataFrame")
                stock_dfs = _zb_multi_result_dataframe_stock_first(df_long)
                for stock_code, stock_df in stock_dfs.items():
                    print_dataframe(stock_df, title=f"{stock_code}|{get_stock_name(stock_code,'')} 在 [yellow]{name}[/yellow] 指标的值", sum_cols=sum_columns, printer=_CSL.print)

                    # 边跑边存：每只股票立即入库
                    if is_save_db and formula_type == 'zb' and not stock_df.empty:
                        formula_key = f"{name}|{','.join(args)}" if args else name
                        db_url = _assemble_db_url(DB_TYPE, _CFG)
                        StockMetrics.init_db(db_url)
                        StockMetrics.bulk_upsert_from_dfs(
                            {stock_code: stock_df}, formula_key, period,
                            dividend_type, db_url, console=_CSL)

                if cache_df:
                    formula_key = f"{name}|{','.join(args)}" if args else name
                    return {'dfs': stock_dfs, 'period': period,
                            'formula_key': formula_key, 'dividend_type': dividend_type,
                            '_source': 'stock_metrics'}
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


# ---------------------------------------------------------------------------------------------
# 查询已存储的指标数据
@command_with_abbrev(abbrev='gsm', context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
              default=STOCKS, required=True, help='股票代码列表 (如: 603337.SH)')
@click.option('--period', '-p', 'period', default='1d',
              type=click.Choice(ALL_PERIODS), show_default=True, help='K线周期')
@click.option('--dividend-type', '-d', 'dividend_type', default=1, show_default=True,
              help='0不复权 1前复权 2后复权')
@click.option('--start-time', '-st', 'start_time', type=DATETIME, help='开始时间')
@click.option('--end-time', '-et', 'end_time', type=DATETIME, default=datetime.now(),
              help='结束时间（默认当前时间）')
@click.option('--count', '-c', 'count', default=20, type=int,
              help='返回最近 N 条记录（count>0 时忽略 start_time）')
@click.option('--formula-key', '-fk', 'formula_key',
              help='按公式 key 过滤（如 L2_DATA，不传则返回全部）')
@click.option('--indicator-key', '-ik', 'indicator_key',
              help='进一步提取特定指标值（如 DDX）')
@click.option('--db-type', '-db', 'db_type', default=None,
              type=click.Choice(ALL_DB_LIST, case_sensitive=False),
              help=f'数据库类型（默认: {DB_TYPE}）')
@click.pass_context
def get_stock_metrics(_ctx: click.Context,
                       stocks: list[str],
                       period: str,
                       dividend_type: int,
                       start_time: datetime | None,
                       end_time: datetime | None,
                       count: int,
                       formula_key: str,
                       indicator_key: str,
                       db_type: str):
    """从 stock_metrics 表查询已存储的公式指标数据

    用法示例：
        gsm -s 603337.SH -fk L2_DATA                          # 查询全部 L2_DATA 指标
        gsm -s 603337.SH -fk L2_DATA -ik DDX -c 5             # 查最近5天 DDX 值
        gsm -s 603337.SH,600000.SH -fk MY_MR_ZJLX|1 -c 10     # 多只股票
    """
    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    if db_type is None:
        db_type = DB_TYPE

    # 时间处理
    if start_time:
        start_time_str = start_time.strftime('%Y-%m-%d')
    else:
        # count>0: 截取最近N条，往后推足够远
        start_time_str = '2000-01-01'

    if end_time:
        end_time_str = end_time.strftime('%Y-%m-%d')
    else:
        end_time_str = datetime.now().strftime('%Y-%m-%d')

    print_locals()

    try:
        db_url = _assemble_db_url(db_type, _CFG)

        for full_code in stocks:
            rows = StockMetrics.query(
                db_url, full_code, period,
                start_time_str, end_time_str,
                dividend_type=dividend_type,
                formula_key=formula_key,
                indicator_key=indicator_key,
            )

            # 限制返回条数（count > 0 时取最早的 N 条，即从 start_time 开始数）
            if count > 0:
                rows = rows[-count:]  # query 返回 DESC，[-count:] = 最旧 count 条

            if not rows:
                _CSL.print(f"[dim]{full_code} {get_stock_name(full_code)} — 无数据[/dim]")
                continue

            # 转为 DataFrame 展示
            df = pd.DataFrame(rows)
            if 'time' in df.columns:
                df.set_index('time', inplace=True)
            title = (f"{full_code} {get_stock_name(full_code)} "
                     f"指标: {formula_key or '全部'}"
                     f"{' → ' + indicator_key if indicator_key else ''}"
                     f" (period={period}, dividend_type={dividend_type})")
            print_dataframe(df, title=title, show_footer=True, printer=_CSL.print)

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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
    _CSL = _ctx.obj['console'] # type: Console
    if not stocks:
        _CSL.print("[yellow]请至少指定一只股票进行订阅/取消订阅[/yellow]")
        return

    global SUBSCRIBED_STOCKS

    try:
        if is_unsubscribe:
            tq.unsubscribe_hq(stock_list=stocks)
            SUBSCRIBED_STOCKS.difference_update(stocks)
            _CSL.print(f"已取消订阅股票: {stocks}，当前订阅列表: {SUBSCRIBED_STOCKS}")
            return

        tq.subscribe_hq(stock_list=stocks, callback=lambda data: _CSL.print(f"行情更新: {data}"))
        SUBSCRIBED_STOCKS.update(stocks)
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)




@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.pass_context
def _example(_ctx: click.Context,
    stocks: list[str],
):
    """"""
    _CSL = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            # TODO:
            _CSL.print(f"{full_code} :", )
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, default=STOCKS,
              help='股票代码列表（管道中由上游自动注入，也可手动传参）')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.option('--with-name', '-wn', 'is_with_name', is_flag=True, help='股票代码是否带上股票名称')
@click.option('--max-to-show', '-max', 'max_to_show', default=20, show_default=True, type=int, help='最多显示多少条数据')
@click.pass_context
def print_pipe(_ctx: click.Context,
    stocks: list[str],
    verbose: bool,
    is_with_name: bool,
    max_to_show: int,
):
    """打印管道接收到的数据（用于测试管道功能）

    用法示例：
      gsl -c 存储 | print-pipe           # 查看上游传来的 stocks
      gsl -c 存储 | get-market-data -p 1d -c 10 -fd | print-pipe  # 查看 stocks + df
      formula -t zb -n MACD -c 10 | print-pipe  # 查看 stocks + dfs

    简单类型（stocks 等）由管道引擎自动注入 --stock 参数；
    复杂类型（df / dfs）通过 _pipe_data 传递，本命令从 ctx.obj 显式读取。
    """
    _CSL = _ctx.obj['console']  # type: Console
    if verbose:
        _CSL.print(f"ctx.obj = { {k: v for k, v in _ctx.obj.items() if k.startswith('_')} }")

    # ── 1. 简单类型：由 click.option 接收（管道引擎自动注入） ──
    if stocks:
        _CSL.print(f"\n[bold cyan]📦 stocks[/bold cyan] （[bold]{len(stocks)}[/bold] 只）:")
        if is_with_name:
            stock_with_names = [f"{code}|{get_stock_name(code)}" for code in stocks]
            print_dataframe(pd.DataFrame(stock_with_names, columns=['股票代码|名称']), title='stocks 列表', printer=_CSL.print)
            # _CSL.print(Pretty(stock_with_names, max_length=max_to_show) if len(stock_with_names) > max_to_show else stock_with_names)
        else:
            _CSL.print(Pretty(stocks, max_length=max_to_show) if len(stocks) > max_to_show else list(stocks))
    else:
        _CSL.print("[dim]📦 stocks: (空)[/dim]")

    # ── 2. 复杂类型：从 _pipe_data 显式读取 ──
    pipe_data = _ctx.obj.get('_pipe_data')
    if not pipe_data:
        _CSL.print("\n[yellow]⚠️ 未收到 _pipe_data（可能不在管道中，或上游未返回数据）[/yellow]")
        _CSL.print("[dim]提示: 管道中上游命令需返回 dict 类型（如 {'stocks': ..., 'df': ..., 'dfs': ...}）[/dim]")
        return

    _CSL.print(f"\n[bold]🔗 _pipe_data 包含的 key:[/bold] {list(pipe_data.keys())}")

    # ── 2a. df ──
    _df = pipe_data.get('df')
    if _df is not None:
        if isinstance(_df, pd.DataFrame):
            _CSL.print(f"\n[bold cyan]📊 df[/bold cyan]  shape={_df.shape}, columns={list(_df.columns)}, "
                          f"index={_df.index.name or type(_df.index).__name__}")
            # 如果 df 较小则直接打印，否则仅打印 head
            if _df.shape[0] <= 20:
                print_dataframe(_df, title='df 完整内容', printer=_CSL.print)
            else:
                print_dataframe(_df.head(10), title='df 前 10 行', printer=_CSL.print)
                _CSL.print(f"[dim]... 省略 {_df.shape[0] - 10} 行[/dim]")
        else:
            _CSL.print(f"[dim]📊 df: type={type(_df).__name__} (非 DataFrame，跳过)[/dim]")

    # ── 2b. dfs ──
    _dfs = pipe_data.get('dfs')
    if _dfs is not None:
        if isinstance(_dfs, dict) and _dfs:
            _CSL.print(f"\n[bold cyan]📚 dfs[/bold cyan] （[bold]{len(_dfs)}[/bold] 个股票）:")
            for code, s_df in _dfs.items():
                if isinstance(s_df, pd.DataFrame):
                    _CSL.print(f"  [cyan]{code}[/cyan]  shape={s_df.shape}, columns={list(s_df.columns)}")
                else:
                    _CSL.print(f"  [cyan]{code}[/cyan]  type={type(s_df).__name__} (非 DataFrame)")
        else:
            _CSL.print("[dim]📚 dfs: (空)[/dim]")

    # —— 2c. blocks ——
    _blocks = pipe_data.get('blocks')
    if _blocks:
        _CSL.print(f"\n[bold cyan]📦 blocks[/bold cyan] （[bold]{len(_blocks)}[/bold] 个板块）:")
        _CSL.print(Pretty(_blocks, max_length=max_to_show) if len(_blocks) > max_to_show else list(_blocks))


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('--file', '-f', 'file_path', type=click.Path(exists=True, dir_okay=False, readable=True), required=True, help='包含股票代码的文件路径（每行一个股票代码）')
@click.option('--key', '-k', 'key', default='stocks', show_default=True, help='返回的 key 名称')
@click.pass_context
def read_from_file(_ctx: click.Context,
                   file_path: str,
                   key: str,
                   **kwargs):
    """从文件中读取 stocks 列表（每行一个股票代码）"""
    _CSL = _ctx.obj['console'] # type: Console

    try:
        stocks = []
        df = None
        # 支持从 .parquet 文件中导入 df
        if file_path.endswith('.parquet'):
            import pandas as pd
            df = pd.read_parquet(file_path)
            if not df.empty:
                # 尝试取第一列作为股票代码
                first_col = df.columns[0]
                stocks = [str(code).strip() for code in df[first_col] if str(code).strip()]
                df = df[df[first_col].isin(stocks)]  # 过滤掉空值或无效股票代码的行
            else:
                _CSL.print(f"[yellow]⚠️ Parquet 文件 {file_path} 中未找到有效的股票代码[/yellow]")
                return

        with open(file_path, 'r', encoding='utf-8') as f:
            # 根据后缀名判断用哪种方式解析文件
            if file_path.endswith('.csv'):
                import csv
                reader = csv.reader(f)
                stocks = [row[0].strip() for row in reader if row and row[0].strip()]
            elif file_path.endswith('.json'):
                import json
                data = json.load(f)
                if isinstance(data, list):
                    stocks = [str(item).strip() for item in data if str(item).strip()]
                elif isinstance(data, dict):
                    # 如果是字典，尝试取 key 为 'stocks' 或 'data' 的值
                    if 'stocks' in data and isinstance(data['stocks'], list):
                        stocks = [str(item).strip() for item in data['stocks'] if str(item).strip()]
                    elif 'data' in data and isinstance(data['data'], list):
                        stocks = [str(item).strip() for item in data['data'] if str(item).strip()]
                    else:
                        _CSL.print(f"[yellow]⚠️ JSON 文件 {file_path} 中未找到有效的股票代码列表[/yellow]")
                        return
                else:
                    _CSL.print(f"[yellow]⚠️ JSON 文件 {file_path} 格式不支持[/yellow]")
                    return
            elif file_path.endswith('.xlsx') or file_path.endswith('.xls'):
                import pandas as pd
                df = pd.read_excel(f)
                if not df.empty:
                    # 尝试取第一列作为股票代码
                    first_col = df.columns[0]
                    stocks = [str(code).strip() for code in df[first_col] if str(code).strip()]
                else:
                    _CSL.print(f"[yellow]⚠️ Excel 文件 {file_path} 中未找到有效的股票代码[/yellow]")
                    return
            elif file_path.endswith('.txt'):
                stocks = [line.strip() for line in f if line.strip()]

        if not stocks:
            _CSL.print(f"[yellow]⚠️ 文件 {file_path} 中未找到有效的股票代码[/yellow]")
            return
        _CSL.print(f"从文件 {file_path} 读取到 [bold]{len(stocks)}[/bold] 个股票代码")

        if df is not None:
            return {key: stocks, 'df': df}
        return {key: stocks}  # 返回就会被 stocks_collector 添加到 cache_cmd.STOCKS 中
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@stocks_collector
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
              default=STOCKS, required=False, help='股票代码列表。管道模式下可从上游自动获取')
@click.option('--file', '-f', 'file_path', type=str, required=True,
              help='输出文件路径。无路径分隔符时自动放入 output/ 目录；后缀名决定格式（.txt/.csv/.xlsx/.json）')
@click.option('--key', '-k', 'key', default='stocks', show_default=True, help='JSON 输出时的键名')
@click.pass_context
def save_to_file(_ctx: click.Context,
                  stocks: list[str],
                  file_path: str,
                  key: str,
                  cache_stocks: bool,
                  stock_group_index: int,
                  **kwargs):
    """保存 stocks / df / dfs 到文件（与 read_from_file 对应）

    根据 --file 后缀名自动识别格式：
    - .xlsx: 所有数据同一文件，stocks→sheet「stocks」、df→sheet「df」、dfs 逐 key
    - .txt/.csv/.json: 仅 stocks

    管道模式下自动获取上游的 stocks / df / dfs。
    文件路径不含 / 或 \\ 时自动加上 output/ 前缀。

    使用示例：
        gs -m 50 | sf -f all_a.txt
        ss -s 603358.SH -dl -tf daily_pnl | sf -f report.xlsx
    """
    _CSL = _ctx.obj['console']  # type: Console

    try:
        import os

        # ── 收集数据：CLI stocks + 管道 pipe_data ──
        pipe_data = _ctx.obj.get('_pipe_data', {})
        stocks_list = list(stocks) if stocks else []
        if pipe_data:
            if not stocks_list:
                stocks_list = list(pipe_data.get('stocks', set()))
        pipe_df = pipe_data.get('df')  # single DataFrame
        pipe_dfs = pipe_data.get('dfs', {})  # dict[str, DataFrame]

        # 无路径分隔符 → 自动加 output/ 前缀
        if '/' not in file_path and '\\' not in file_path:
            os.makedirs('output', exist_ok=True)
            file_path = os.path.join('output', file_path)

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ('.txt', '.csv', '.xlsx', '.json'):
            _CSL.print(f"[red]不支持的文件后缀: {ext}（支持 .txt / .csv / .xlsx / .json）[/red]")
            return

        # ── xlsx: 所有数据同一文件 ──
        if ext == '.xlsx':
            import pandas as pd
            sheets = []
            if stocks_list:
                sheets.append(('stocks', pd.DataFrame({key: stocks_list})))
            if pipe_df is not None and isinstance(pipe_df, pd.DataFrame) and not pipe_df.empty:
                sheets.append(('df', pipe_df))
            if pipe_dfs:
                for k, v in pipe_dfs.items():
                    if isinstance(v, pd.DataFrame) and not v.empty:
                        safe = str(k)[:31]
                        sheets.append((safe, v))
            if not sheets:
                _CSL.print("[red]无数据可保存（stocks/df/dfs 均为空）[/red]")
                return
            with pd.ExcelWriter(file_path, engine='openpyxl') as w:
                for sheet_name, s_df in sheets:
                    s_df.to_excel(w, sheet_name=sheet_name, index=False)
            parts = [f"{s[0]}:{len(s[1])}行" for s in sheets]
            _CSL.print(f"✅ 已保存到 [yellow]{file_path}[/yellow]（{'，'.join(parts)}）")
        elif stocks_list:
            # ── 非 xlsx: 仅 stocks ──
            if ext == '.txt':
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(stocks_list))
            elif ext == '.csv':
                import csv
                with open(file_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    for s in stocks_list:
                        writer.writerow([s])
            elif ext == '.json':
                import json
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({key: stocks_list}, f, ensure_ascii=False, indent=2)
            _CSL.print(f"✅ 已保存 [green]{len(stocks_list)}[/green] 只股票到 [yellow]{file_path}[/yellow]")
        else:
            _CSL.print("[red]无数据可保存（stocks/df/dfs 均为空）[/red]")
            return

        if cache_stocks and stocks_list:
            return {'stocks': stocks_list}

    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--date', '-d', 'date', type=DATETIME, default=None,
              help='日期（默认从 from_block_name 中提取，如 吸完·首倍阳_5.20260710 → 20260710）')
@click.option('--from-block-name', '-fb', 'from_block_name', required=True,
              help='来源板块名称（从中提取个股，支持 -c 模糊匹配）')
@click.option('--to-block-tip', '-tbt', 'to_block_tip', default='可买入',
              help='目标板块后缀（如 "可买入" → XXXX.可买入.YYYYMMDD）')
@click.option('--zm-min', '-zm-min', 'zm_min', type=float, default=None,
              help='主买净额(万元) 最小值')
@click.option('--zm-max', '-zm-max', 'zm_max', type=float, default=None,
              help='主买净额(万元) 最大值')
@click.option('--zl-min', '-zl-min', 'zl_min', type=float, default=None,
              help='主力净流入(万元) 最小值')
@click.option('--zl-max', '-zl-max', 'zl_max', type=float, default=None,
              help='主力净流入(万元) 最大值')
@click.option('--keep-zt', '-zt', 'keep_zt', is_flag=True, default=False, help='保留涨停股')
@click.option('--keep-not-zt', '-nzt', 'keep_not_zt', is_flag=True, default=False, help='保留非涨停股')
@click.option('--keep-dt', '-dt', 'keep_dt', is_flag=True, default=False, help='保留跌停股')
@click.option('--keep-not-dt', '-ndt', 'keep_not_dt', is_flag=True, default=False, help='保留非跌停股')
@click.pass_context
def filter_to_block(_ctx: click.Context,
    date: datetime | None,
    from_block_name: str,
    to_block_tip: str,
    zm_min: float | None,
    zm_max: float | None,
    zl_min: float | None,
    zl_max: float | None,
    keep_zt: bool,
    keep_not_zt: bool,
    keep_dt: bool,
    keep_not_dt: bool,
):
    """从自定义板块取股 → 资金流筛选 → 涨跌停过滤 → 存入新板块

    等价于管道链: gus -c <from> | fcf -d <date> ... | fl ... | us -a create -n <to>
    所有步骤在一次调用中完成。

    使用示例：
        ftb -fb 吸完·首倍阳_5.20260710 -zm-min 0 -zl-min 0 -nzt -ndt
            → gus → fcf(d=20260710) → fl(nzt+ndt) → 创建板块「吸完·首倍阳_5.可买入.20260710」

        ftb -fb 吸完·首倍阳_5.20260710 -zt -tbt 涨停票
            → 仅保留涨停股，存入「吸完·首倍阳_5.涨停票.20260710」
    """
    _CSL = _ctx.obj['console']  # type: Console
    import re

    # ── 提取日期：优先用显式 --date，否则从 from_block_name 中取最后的8位数字 ──
    if date is None:
        m = re.search(r'(\d{8})', from_block_name)
        if m:
            date_str = m.group(1)
            from difoss_stock_util.time_util import TimeUtils
            date = TimeUtils.str_to_datetime(date_str)
        if date is None:
            _CSL.print(f"[red]无法从板块名 '{from_block_name}' 提取日期，请使用 -d 指定[/red]")
            return

    trading_date_str = date.strftime('%Y%m%d')
    _CSL.print(f"\n[bold]🔗 一键筛选入库[/bold] — 日期: [yellow]{trading_date_str}[/yellow]")

    # ── Step 1: 从自定义板块获取个股 ──
    _CSL.print(f"[bold]Step 1/4[/bold] 从板块 [yellow]{from_block_name}[/yellow] 获取个股...")
    result = _ctx.invoke(get_user_sector, contains=[from_block_name], cache_stocks=True)
    stocks = result.get('stocks', set()) if isinstance(result, dict) else set()
    if not stocks:
        _CSL.print(f"[red]板块 '{from_block_name}' 中无个股[/red]")
        return
    _CSL.print(f"   获取到 [green]{len(stocks)}[/green] 只个股")

    # ── Step 2: 主力资金流筛选 ──
    if any(v is not None for v in (zm_min, zm_max, zl_min, zl_max)):
        _CSL.print(f"[bold]Step 2/4[/bold] 主力资金流筛选...")
        result = _ctx.invoke(filter_capital_flow,
                             stocks=list(stocks), date=date,
                             zm_min=zm_min, zm_max=zm_max,
                             zl_min=zl_min, zl_max=zl_max,
                             cache_stocks=True)
        stocks = result.get('stocks', set()) if isinstance(result, dict) else set()
        if not stocks:
            _CSL.print("[yellow]资金流筛选后无个股剩余[/yellow]")
            return
        _CSL.print(f"   剩余 [green]{len(stocks)}[/green] 只")
    else:
        _CSL.print(f"[dim]Step 2/4 资金流筛选: 未设置过滤条件，跳过[/dim]")

    # ── Step 3: 涨跌停过滤 ──
    if any([keep_zt, keep_not_zt, keep_dt, keep_not_dt]):
        _CSL.print(f"[bold]Step 3/4[/bold] 涨跌停筛选...")
        result = _ctx.invoke(filter_limit,
                             stocks=list(stocks), date=date,
                             keep_zt=keep_zt, keep_not_zt=keep_not_zt,
                             keep_dt=keep_dt, keep_not_dt=keep_not_dt,
                             cache_stocks=True)
        stocks = result.get('stocks', set()) if isinstance(result, dict) else set()
        if not stocks:
            _CSL.print("[yellow]涨跌停筛选后无个股剩余[/yellow]")
            return
        _CSL.print(f"   剩余 [green]{len(stocks)}[/green] 只")
    else:
        _CSL.print(f"[dim]Step 3/4 涨跌停筛选: 未设置过滤条件，跳过[/dim]")

    # ── Step 4: 构建目标板块名并创建 ──
    # 规则：原板块名去掉末尾日期 → 加 to_block_tip → 加日期
    base_name = re.sub(r'\.?\d{8}$', '', from_block_name)  # 去掉末尾的日期
    to_block_name = f"{base_name}.{to_block_tip}.{trading_date_str}"
    _CSL.print(f"[bold]Step 4/4[/bold] 创建板块 [yellow]{to_block_name}[/yellow] 并添加 {len(stocks)} 只个股")
    _ctx.invoke(user_sector, action='create', name=to_block_name, stocks=list(stocks))

    _CSL.print(f"\n✅ 完成！板块 [yellow]{to_block_name}[/yellow] 共 [green]{len(stocks)}[/green] 只个股")