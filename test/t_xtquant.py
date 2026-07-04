#!python

import click
from datetime import datetime, date, timedelta, time as datetime_time
from difoss_stock_util import *
from difoss_stock_util.xtquant_util import get_market_stocks
from difoss_stock_util.color_log_util import *
from typing import Optional, List
import pandas as pd
from xtquant import xtdata
xtdata.enable_hello = False
from rich import print
from pandas import DataFrame
from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import *
from chinese_calendar import is_workday

from difoss_stock_util.metric_data import HistoryData1D

# -----------------------------------------------------------------------------------
# 全局变量
ALL_MARKET_LIST = ['SH', 'SZ', 'BJ']
ALL_DB_LIST = ['pg', 'postgresql', 'sqlite']
NOW_DT = datetime.now()
BELONG_TRADING_DATE = calc_belong_trading_day(NOW_DT, datetime_time(hour=15))


# -----------------------------------------------------------------------------------
# 功能函数
def get_industry_by_stock() -> pd.DataFrame:
    """获取股票对应的行业"""
    reverse_industry = {}
    sw_sectors = [sector for sector in xtdata.get_sector_list() if (sector.startswith('SW1') and ("加权" not in sector))]
    for _sector in sw_sectors:
        for _stk in xtdata.get_stock_list_in_sector(_sector):
            reverse_industry[_stk] = _sector
    return pd.get_dummies(pd.Series(reverse_industry))

# -----------------------------------------------------------------------------------
@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.argument('stocks', nargs=-1, callback=split_comma, required=False)
@click.option('-m', '--market', 'markets', multiple=True, callback=split_comma,
            #   type=click.Choice([*ALL_MARKET_LIST, 'ALL']), case_sensitive=False,
              help='市场代码（可多次使用，自动转换大写，支持半角逗号分隔），如: -m SH -m SZ 或者 -m SH,SZ ')
@click.option('-a', '--all', is_flag=True, help='获取所有市场数据')
@click.option('-v', '--verbose', is_flag=True, help='详细模式')
@click.option('-l', '--limit', type=int, default=-1, show_default=True, help='限制处理股票的数量')
@click.option('-t-f', '--test-futures', is_flag=True, help='测试期货')
@click.option('-c', '--count', type=int, default=30, show_default=True, help='获取市场数据的数量')
@click.option('--start-time', type=DATETIME, help='开始时间')
@click.option('--end-time', type=DATETIME, help='结束时间')
@click.option('-f', '--field', 'fields', multiple=True, callback=split_comma, default=[], help='指定字段，支持逗号分隔')
@click.option('-dh', '--download-history', 'download_history', is_flag=True, help='下载（从个股发行日开始的）历史数据')
@click.option('-gsl', '--get-sector-list', is_flag=True, help='显示板块列表')
@click.option('-s', '--sector', 'sectors', multiple=True, callback=split_comma, help='板块代码（可多次使用，支持半角逗号分隔）')
@click.option('-w', '--workday', is_flag=True, help='是否为工作日')
@click.option('-sdh', '--save-1d-history', 'save_1d_history', is_flag=True, help='保存日线历史数据')
@click.option('-db', '--db-type', 'db_type', default='pg',
              type=click.Choice(ALL_DB_LIST, case_sensitive=False),
              help="选中该项后，会读取 config.yaml 文件中对应的数据库信息进行连接，默认是 pg")
@click.option('-d', '--debug', is_flag=True, help='调试模式')
@click.option('-gil', '--get-industry-list', is_flag=True, help='显示行业列表')
def main(
    stocks: List[str],
    markets: List[str],
    all: bool,
    verbose: bool,
    limit: int,
    test_futures: bool,
    count: int,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    fields: List[str],
    download_history: bool,
    get_sector_list: bool,
    sectors: List[str],
    workday: bool,
    save_1d_history: bool,
    db_type: str,
    debug: bool,
    get_industry_list: bool,
):
    I(**{k:v for k,v in locals().items() if v}, _level='PARAMETER')

    CFG = read_yaml_config()
    # 初始化数据库
    if db_type and db_type == 'sqlite':
        db_cfg = CFG.get('sqlite', {'database' : ':memory:'})
    elif db_type and (db_type in ['postgresql', 'pg']):
        db_cfg = CFG.get('postgresql', {})

    if db_cfg:
        conn_str = generate_engine_url_str(**db_cfg)
        HistoryData1D.init_db(conn_str, debug=debug)
        if db_type != 'sqlite':
            HistoryData1D.create_yearly_partition(1990, 2026, ALL_MARKET_LIST)

    if not stocks:
        # 如果没有指定特定市场
        if not markets:
            if all:
                markets = ALL_MARKET_LIST
            else:
                # stocks = ["002415.SZ"] # 默认股票
                stocks = []

    if stocks:
        stocks = [SecurityCode(stock).full_code for stock in stocks]

    if not count:
        count = 1

    if workday:
        print(f"{start_time} {'是' if is_trading_day(start_time.date()) else '不是'}交易日")
        return

    trading_info = TradingInfo(start_time=start_time, end_time=end_time, count=count).complete()
    print(f"trading_info={trading_info}")
    
    start_time = trading_info.start_time.strftime("%Y%m%d") if trading_info.start_time else None
    end_time = trading_info.end_time.strftime("%Y%m%d") if trading_info.end_time else None
    count = trading_info.count


    if save_1d_history:
        limiter = create_limiter(limit)
        for stock in stocks:
            if not limiter():
                W("达到限制，停止处理", _level='RESULT')
                break

            if not end_time:
                end_time = BELONG_TRADING_DATE.strftime('%Y%m%d')

            data = xtdata.get_market_data_ex(stock_list=[stock],
                                            start_time=start_time,
                                            end_time=end_time,
                                            count=trading_info.count)
            if data and isinstance(data, dict):
                for full_code, df in data.items():
                    code = SecurityCode(full_code)
                    HistoryData1D.bulk_insert_from_dataframe(df, instrument_id=code.short_code, exchange_id=code.market_code)
                #     print(f"full_code={full_code}, df={df}")
                #     pass #TODO

        return

    for stock in stocks[:limit]:
        code = SecurityCode(stock) # 会自动推断 市场代码，并按照新的北交所股票规则进行代码更换：837344.BJ → 920334.BJ

        detail = xtdata.get_instrument_detail(code.full_code)
        if detail:
            if fields:
                result = {k:v for k,v in detail.items() if k in fields and v}
            else:
                result = {k:v for k,v in detail.items() if v}
            D(f"get_instrument_detail({code}):", **result, _indent=2) # 去掉所有“空”值/零值的项

        # xtdata.download_history_data(code.full_code, period='1d', start_time=start_time, end_time=end_time)

        market_data = xtdata.get_market_data_ex(stock_list=[code.full_code], # count=count,
                                                start_time=start_time, end_time=end_time)
        if market_data:
            # D(f"get_market_data_ex({code}):", **{k:v for k,v in market_data.items() if v}, _indent=2)
            print(f"<type={type(market_data)}> get_market_data_ex({code}):", market_data)

            print(f"- type of market_data[{code.full_code}]:", type(market_data[code.full_code]))
            df = DataFrame(market_data[code.full_code])
            print(f"- columns of market_data[{code.full_code}]:", df.columns.to_list())
            print(f"- index of market_data[{code.full_code}]:", df.index.to_list())

        market_local_data = xtdata.get_local_data(
            stock_list=[code.full_code], count=count,
            start_time=start_time, end_time=end_time)
        if market_local_data:
            print(f"<type={type(market_local_data)}> get_local_data({code}):", market_local_data)


    if download_history:
        for market in markets:
            progress_print(f"Processing market: {market}")
            stock_sorted_list = get_market_stocks(market)

            for _, stock in enumerate_with_progress(stock_sorted_list[:limit]):
                detail = xtdata.get_instrument_detail(stock.full_code)
                if not detail:
                    continue

                # print(f"detail: {detail}")
                open_date = detail.get('OpenDate')
                name = detail.get('InstrumentName')

                start_time_dl = IntegerDate.date_to_int_not_throw(open_date)
                start_time = str(start_time_dl) if start_time_dl else None
                end_time = BELONG_TRADING_DATE.strftime('%Y%m%d')

                progress_print(f"start_time: {start_time}, end_time: {end_time}, stock: {stock.full_code} {name}")
                # if open_date and 99999999 > int(open_date) > 0:
                xtdata.download_history_data(stock.full_code, period='1d', start_time=start_time, end_time=end_time)

        return

    if markets:
        for market in markets:
            progress_print(f"处理市场: {market}")
            stock_sorted_list = get_market_stocks(market)
            print(f"市场 {market} 的有 {len(stock_sorted_list)} 只股票")
        return

    # 市场列表
    if get_sector_list:
        tmp_sectors = xtdata.get_sector_list()
        if tmp_sectors:
            T(f"共 {len(tmp_sectors)} 个板块：", 板块列表=tmp_sectors)
        else:
            W("没有获取任何板块列表")
        
        if verbose:
            sectors = tmp_sectors
            # 留给下面的针对 sectors 的详细遍历处理
        else:
            return

    # 获取行业列表
    if get_industry_list:
        # xtdata 还是一如既往地坑，需要先 download 再 get
        # xtdata.download_sector_data() # BUG: 卡住无法下载成功
        industry_df = get_industry_by_stock()
        print(industry_df.head())
        return
    
    if sectors:
        D(sectors=sectors)
        for sector in sectors:
            # progress_print(f"处理板块: {sector}")
            stock_sorted_list = get_market_stocks(sector, security_types=[SecurityType.STOCK, SecurityType.OPTION])
            len_of_stocks = len([s for s in stock_sorted_list if s.security_type == SecurityType.STOCK])
            len_of_options = len([s for s in stock_sorted_list if s.security_type == SecurityType.OPTION])
            if len_of_stocks or len_of_options > 0:
                I(板块=sector, 股票数量=len_of_stocks, 期权数量=len_of_options)
            
            for stock in stock_sorted_list:
                if stock.short_code.startswith(('92', '8')):
                    # 处理以92开头的股票
                    D(板块=sector, 股票=stock.full_code, 证券类型=stock.security_type)

    # 期货
    if test_futures:
        securities = xtdata.get_stock_list_in_sector('ZF')
        # D(securities=securities, _indent=2)
        fg_securities = []
        for sec in securities:
            if str(sec).startswith('FG'):
                fg_securities.append(sec)

        if verbose:
            D(fg_securities=fg_securities, _indent=2) # FG开头的品种

        # 玻璃（主连）
        detail = xtdata.get_instrument_detail('FG512.ZF')
        if detail:
            D(detail={k:v for k,v in detail.items() if v}, _indent=2)

if __name__ == "__main__":
    main()