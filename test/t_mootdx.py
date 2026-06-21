#!python
# encoding: utf-8
# author: DifossChen
#
import click

from difoss_stock_util.dir_util import walk
from difoss_stock_util.util import *
from difoss_stock_util.click_util import *
from difoss_stock_util.color_log_util import *
from difoss_stock_util.security_util import *
from difoss_stock_util.time_util import *
from difoss_stock_util.rich_util.rich_table import *
from difoss_stock_util.time_util import *
from difoss_stock_util.stock_util import *
from rich import print, console
from typing import List, Optional

from mootdx.reader import Reader, StdReader, ExtReader
from mootdx.quotes import Quotes
# from pytdx.parser.get_block_info import get_and_parse_block_info
# from pytdx.hq import TdxHq_API

from tdxpy.reader.block_reader import BlockReader, BaseReader, CustomerBlockReader, BlockReader_TYPE_FLAT, BlockReader_TYPE_GROUP
from tdxpy.reader.history_financial_reader import HistoryFinancialReader

# 除了测速接口，其余都尽量使用 tdxpy，而非 pytdx（因为从代码对比来看，tdxpy 更先进）
from pytdx.util.best_ip import select_best_ip
from pathlib import Path
import re
import pandas as pd
import numpy as np
from datetime import datetime

# -----------------------------------------------------------------------------------
CN_BLOCK_MAP = {
    # 经典 ----------------------------
    '风格': 'block_fg',
    '概念': 'block_gn',
    '指数': 'block_zs',
    '自定义': 'blocknew',

    # ---------------------------
    '股本变迁': 'gbbq.map',

    # 少用 ----------------------------
    '巴克莱？': 'brkcomp',
    '中证全收益指数': 'csiblock',
    '扩展市场行情': 'ds_mrk',
    '基金': 'fundstk',
    '港股指数': 'hkblock',
    '沪深300增强基金': 'jjblock',
    '道琼斯成份股': 'mgblock',
    '已摘牌': 'pttab',
    '三板拟转A股': 'sbblock',
    '新加坡中国股': 'sgxblock',
    '融资融券': 'spblock',
    '知名英股': 'ukblock'
}

BLOCK_CN_MAP = {v: k for k, v in CN_BLOCK_MAP.items()}
ALL_MARKETS = ['SZ', 'SH'] # mootdx 暂时不支持 'BJ'
ALL_SECURITY_TYPE_LIST = SecurityType.allows()
ALL_SECURITY_TYPE_CN_LIST = SecurityType.allows_cn()
NOW_DT = datetime.now()
BELONG_TRADING_DATE = calc_belong_trading_day(NOW_DT)

CONSOLE = console.Console()
# -----------------------------------------------------------------------------------

# 【分组格式】列名: blockname, block_type, stock_count, code_list
def read_block(reader: StdReader|ExtReader|CustomerBlockReader, symbol, is_group,
            # 查找相关参数
            columns: List[str], finds: List[str], finds_contained: List[str],
            # 显示设置相关参数
            is_show: bool = True,
            table_max_rows: int = 300,
) -> Optional[pd.DataFrame]:
    
    if isinstance(reader, (StdReader, ExtReader)):
        df = reader.block(symbol=symbol, group=is_group)  # type: pd.DataFrame
    elif isinstance(reader, CustomerBlockReader):
        df = reader.get_df(symbol, is_group)

    if str(df.columns.dtype) == 'int64':
        df.columns = df.columns.astype(str)

    need_filter = finds or finds_contained
    tip = f"{'过滤后的' if need_filter else ''}结果（{'分组' if is_group else '扁平'}格式）"
    
    if df is not None and not df.empty:

        df_filtered = pd.DataFrame()

        if need_filter:
            for column in columns:
                if column in df.columns:
                    if finds:
                        df_once_filtered = df[df[column].isin(finds)]
                    if finds_contained:
                        df_once_filtered = check_text_in_column(df, column, finds_contained)
                    df_filtered = pd.concat([df_filtered, df_once_filtered], ignore_index=True)

            df = df_filtered
        
        if is_show:
            print_dataframe(df, title=tip, printer=CONSOLE.print,
                            footer_options={'custom_text': f"板块: {symbol}"})
            D(_level='RESULT', finds=finds, finds_contained=finds_contained)

    return df


# -----------------------------------------------------------------------------------
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
# 个股参数
@click.argument('stocks', nargs=-1, callback=split_comma)
# 市场参数
@click.option('-m', '--market', 'markets', callback=split_comma, multiple=True, help='市场代码（可多次使用，支持半角逗号分隔）')
@click.option('-a', '--all', 'all_markets', is_flag=True, help='查询所有市场（相当于 -m ALL）')
# 板块参数
@click.option('-b', '--block', 'blocks', callback=split_comma, multiple=True, help='板块代码（可多次使用，支持半角逗号分隔）')
@click.option('-fab', '--find-all-blocks', 'find_all_blocks', is_flag=True, help='获取 T0002/hq_cache 目录下的板块信息')
# 查找类参数f
@click.option('-f', '--find', 'finds', callback=split_comma, multiple=True, help='根据名称（全部匹配）查找板块')
@click.option('-fc', '--find-contain', 'finds_contained', callback=split_comma, multiple=True, help='根据名称（部分匹配）查找板块')
@click.option('-col', '--column', 'columns', callback=split_comma, multiple=True, help='指定列（可多次使用，支持半角逗号分隔）')
@click.option('-d', '--date', 'date_range', callback=split_comma, help='日期范围（格式：YYYY-MM-DD,YYYY-MM-DD）')
@click.option('-t', '--security-type', 'security_types',
              type=click.Choice([*ALL_SECURITY_TYPE_LIST, *ALL_SECURITY_TYPE_CN_LIST], case_sensitive=False),
              multiple=True, callback=split_comma, help='股票类型')
# 选项
@click.option('-best', '--find-best-ip', 'find_best_ip', is_flag=True, help='获取最佳IP')
@click.option('-v', '--verbose', is_flag=True, help='详细模式')
@click.option('-tc', '--test-code', 'is_test_code', is_flag=True, help='测试SecurityCode功能')
@click.option('-lang', '--language', 'language', default='zh', type=click.Choice(['zh', 'en']), help='语言选择')
# infoharbor_block.dat
# @click.option('-ib-name', '--infoharbor-block-name', 'infoharbor_block_by_name', is_flag=True, help='以获取 infoharbor_block.dat 文件内容')
def main(
    stocks: List[str],
    markets: List[str],
    all_markets: bool,
    blocks: List[str],
    find_all_blocks: bool,
    finds: List[str],
    finds_contained: List[str],
    date_range: str,
    security_types: List[str],
    columns: List[str],
    find_best_ip: bool,
    verbose: bool,
    is_test_code: bool,
    language: str,
):
    """处理股票和板块信息"""

    # 参数预处理 -----------------------------------------------------------------------------------------------------------
    if not date_range:
        date_range = []
    elif len(date_range) == 1:
        date_range = [TimeUtils.str_to_date(date_range[0]), BELONG_TRADING_DATE]
    else:
        date_range = [TimeUtils.str_to_date(date_range[0]), TimeUtils.str_to_date(date_range[1])]

    if not columns:
        columns = ['blockname']

    if all_markets or (markets and "ALL" in markets):
        markets = ALL_MARKETS

    # 支持中文名称作为参数
    s_types = set()
    for st in security_types:
        if st in ALL_SECURITY_TYPE_LIST:
            s_types.add(SecurityType(st).value)
        elif st in ALL_SECURITY_TYPE_CN_LIST:
            s_types.add(SecurityType(SecurityType.chinese_name_2_en(st)).value)
    security_types = list(s_types)  # type: list[str]

    I(**{k:v for k,v in locals().items() if v}, _level='PARAMETER')

    # 读取配置
    CFG = read_yaml_config()

    TDX_DIR = CFG.get('tdx', {}).get('base_dir', 'C:/new_tdx')
    T0002_DIR = Path(TDX_DIR, 'T0002')
    HQ_CACHE_DIR = Path(T0002_DIR, 'hq_cache')
    
    MOOTDX_CFG = CFG.get('mootdx', {})
    IP = MOOTDX_CFG.get('ip', 'sztdx.gtjas.com')
    PORT = int(MOOTDX_CFG.get('port', 7709))
    
    print_locals()
    # ----------------------------------------------------------------------------------------------------------

    try:
        client = Quotes.factory(ip=IP, port=PORT, market='std', multithread=True, heartbeat=True) # 用于线上行情
        reader = Reader.factory(market='std', tdxdir=TDX_DIR)                   # 用于离线数据

        # 用于记录所有证券产品的详情

        if markets:
            stocks_df_matched = pd.DataFrame()

            for market in markets:
                I(f"处理市场 {market}")
                mt = MarketType(market)
                market_enum = mt.int
                stock_count = client.stock_count(market_enum)
                I(market=mt, get_stocks_count=stock_count, _level="RESULT")

                stocks_df = client.stocks(market_enum) # type: pd.DataFrame

                type_col = []  # 新列

                # 处理成交量的小数
                new_pre_close_col = []

                if stocks_df is not None and not stocks_df.empty:
                    for row in stocks_df.itertuples():
                        code = SecurityCode(code=row.code, market=mt)
                        # D(f"处理", sc=code.to_dict(), **record)
                        type_col.append(str(code.security_type))
                        if row.decimal_point > 0:
                            new_pre_close_col.append(format(row.pre_close, f".{row.decimal_point}f"))
                        else:
                            new_pre_close_col.append(row.pre_close)
                    
                    # DEBUG: 涨幅
                    change_col = np.round(np.random.uniform(-10, 10, len(stocks_df)), 2)
                    stocks_df['increase'] = change_col
                    stocks_df['type'] = type_col
                    del stocks_df['decimal_point']
                    del stocks_df['volunit']
                    
                    if language == 'zh':
                        stocks_df.rename(columns={'pre_close': '昨收盘价',
                                                  'increase': '涨幅'}, inplace=True)

                    type_counts = stocks_df['type'].value_counts().to_dict()

                    print(f"市场: {mt} 所有证券产品:", stocks_df)
                    print(f"类型分布: {type_counts}")
                    
                    if security_types:
                        stocks_df_matched = stocks_df[stocks_df['type'].isin(security_types)]
                        print(f"符合类型筛选（{security_types}）参数的有: {len(stocks_df_matched)} 个")
                        print(dataframe_to_rich_table(stocks_df_matched, "符合类型"))

            return


        if find_best_ip:
            find_best_ip = select_best_ip()
            print(f"最佳IP: {find_best_ip}")

        # 处理股票 ----------------------------------------------------------------------------------------------------------
        for stock in stocks:
            code = SecurityCode(stock)
            if is_test_code:
                I("测试SecurityCode:", stock=stock, security_type=code.security_type,
                  market_code=code.market_code, short_code=code.short_code)
                return

            # 通达信离线数据（需要在通达信中点击菜单【选项】【盘后数据下载】，成功后，才能使用数据）
            # 日线
            df = reader.daily(symbol=stock)
            print("日K（离线）", df if not df.empty else None)

            # 通达信线上行情读取
            _market_int = 0 if 'SH' == code.market_code else 1
            df_online = client.bars(symbol=code.short_code, market=_market_int)
            print("日K（线上）", df_online if not df_online.empty else None)

            # return # TODO: TEST

        # 预处理板块参数 ----------------------------------------------------------------------------------------------------
        for block in blocks:
            # 全路径直接读取
            if '/' in block or '\\' in block:
                blocks[blocks.index(block)] = Path(block)
                continue

            # 转换中文
            if block in CN_BLOCK_MAP.keys():
                blocks[blocks.index(block)] = CN_BLOCK_MAP[block]
                block = CN_BLOCK_MAP[block]
                
            if Path(block).stem == 'blocknew':
                # 自定义板块比较特殊，输入参数居然是 “blocknew.cfg” 文件所在的目录（默认是： T0002_DIR/“blocknew/ )
                pass
            elif not block.endswith(('.dat', '.map', '.cfg')):
                blocks[blocks.index(block)] = block + '.dat'  # 保证 blocks 中的文件名都是 .dat 结尾

        # 加载通达信所有板块文件
        block_files_IMS = [
            'ds_stk.dat', 'ds_tinf.dat', 'funddiv.dat', 'fundinfo.dat', 'hkcwdata.dat',
            'hkqxinfo.dat', 'hkqxinfo2.dat', 'hy.dat', 'itcomte.dat', 'mgcwdata.dat',
            'mgqxinfo.dat', 'mgqxinfo2.dat', 'nscomte.dat', 'nvcomte.dat', 'profile.dat',
            'relation.dat', 'sbcwdata.dat', 'sbdiv.dat', 'sgpcwdata.dat'] # [ERROR] illegal multibyte sequence

        _, block_files = walk(HQ_CACHE_DIR, include_extensions=['.dat', '.cfg'], without_root_path=True,\
            exclude_files=block_files_IMS)

        if not blocks:
            if finds or finds_contained:  # 在查找 {columns} 时没有指定板块，则补充默认查找全部板块
                find_all_blocks = True
            if find_all_blocks:  # 此时 -b/--block 参数可作为额外添加查找范围
                blocks.extend(block_files)
                print(f"行情缓存目录={HQ_CACHE_DIR}, 板块文件={block_files}")

        # 处理 blocks
        blocks_exception_occurred = []  # 存储发生异常的板块
        for block in blocks:
            print('🧴 处理板块:', block)

            try:
                if isinstance(block, Path):
                    df = HistoryFinancialReader.get_df(block)
                    print(df.head())
                    continue

                block_path = Path(block)
                T(block_path=block_path)

                if Path(block).stem == 'blocknew':
                    from mootdx.tools.customize import Customize # 此工具类支持删减自定义板块

                    if not block_path.exists():
                        block_path = Path(T0002_DIR) / 'blocknew'

                    customer_reader = CustomerBlockReader()
                    
                    D(block_path=block_path, _level='TEST')

                    read_block(customer_reader, block_path, is_group=True, columns=columns, finds=finds, finds_contained=finds_contained)
                    
                    # DEBUG: 扁平格式可能因为数据太多无法完全显示
                    # read_block(customer_reader, block_path, is_group=False, columns=columns, finds=finds, finds_contained=finds_contained)
                    continue


                # 【分组格式】列名: blockname, block_type, stock_count, code_list
                read_block(reader, symbol=block, is_group=True, columns=columns, finds=finds, finds_contained=finds_contained)

                # 【扁平格式】列名: blockname, block_type, code_index, code
                read_block(reader, symbol=block, is_group=False, columns=columns, finds=finds, finds_contained=finds_contained)

                # if find_all_blocks:
                #     input("按任意键继续 >>>")
            except ValueError as e:
                print(f"处理板块 {block} 时发生错误(值错误): {e}")
                blocks_exception_occurred.append(block)
                continue
            except Exception as e:
                print(f"处理板块 {block} 时发生错误: {e}")
                blocks_exception_occurred.append(block)
                
                CONSOLE.print_exception(extra_lines=5, show_locals=True)
                # import traceback
                # print(traceback.format_exc())

        if blocks_exception_occurred:
            print(f"以下板块处理时发生异常: {blocks_exception_occurred}")

    except KeyboardInterrupt:
        print("\n[yellow]⚠ Installation interrupted by user")

    finally:
        client.close()

if __name__ == "__main__":
    main()