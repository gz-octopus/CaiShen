#!python
# encoding: utf-8
# author: DifossChen
#
from difoss_stock_util import *
from difoss_stock_util.color_log_util import *
from difoss_stock_util.db_util import *
from difoss_stock_util.metric_data import SLBDetail
from slb_migration import sync_data_with_raw_sql

from sqlalchemy.orm import declared_attr, Session
from sqlalchemy import (
    Column, String, Integer, JSON,
    create_engine, Engine
)
from datetime import datetime, timedelta
from datetime import time as datetime_time
import pytz
import json
from typing import Optional, List
from dictdiffer import diff
import click
from rich.console import Console

# -----------------------------------------------------------------------------------
CONSOLE = Console()

# -----------------------------------------------------------------------------------
ALL_MARKET_LIST = ['SH', 'SZ'] #, 'BJ'
ALL_DB_LIST = ['pg', 'postgresql', 'sqlite']
NOW_DT = datetime.now()
BELONG_TRADING_DATE = calc_belong_trading_day(NOW_DT, datetime_time(hour=15))
DEFAULT_OUTPUT_FOLDER = SLBFileManager.generate_dirname(BELONG_TRADING_DATE)

I(BELONG_TRADING_DATE=BELONG_TRADING_DATE, DEFAULT_OUTPUT_FOLDER=DEFAULT_OUTPUT_FOLDER)

def get_input_dir(dt: datetime) -> str:
    return os.path.join(os.environ.get('SLB_HISTORY', '.'), SLBFileManager.generate_dirname(dt))
# -----------------------------------------------------------------------------------

@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.argument('stocks', nargs=-1, required=False)

@click.option('-db', '--db-type', default='pg', show_default=True,
              type=click.Choice(ALL_DB_LIST, case_sensitive=False),
              help="选中该项后，会读取 config.yaml 文件中对应的数据库信息进行连接")
@click.option('-d', '--date', 'date', type=DATETIME, default=NOW_DT, show_default=True, help="在什么时间查找（可用于历史数据回放）")
@click.option('-i', '--input-dir', 'input_dir',
              help=f"扫雷宝详情json文件所在目录 [default: {DEFAULT_OUTPUT_FOLDER} ]")
@click.option('-a', '--all', is_flag=True, help="是否查找全部记录，和 -m 并用")
@click.option('--latest', is_flag=True, help="是否查找最近记录，和 -m 并用")

@click.option('-m', '--market', 'markets', multiple=True, callback=split_comma,
              type=click.Choice([*ALL_MARKET_LIST, 'ALL'], case_sensitive=False),
              help='市场代码（可多次使用，自动转换大写，支持半角逗号分隔），如: -m SH -m SZ 或者 -m SH,SZ ')
@click.option('--list-markets', is_flag=True, help="列出所有市场代码")

@click.option('-slb', '--slb-range', 'slb_score_range', type=str, help="扫雷宝股票分值区间，格式：x,y（表示：x <= slb-risk-score <= y")
@click.option('-risk', '--risk-range', 'risk_score_range', type=str, help="扫雷宝风险总分区间，格式：x,y（表示：x <= risk-score <= y")
@click.option('--risk-plot', is_flag=True, help="生成风险分析图")
@click.option('--fill-market-code', is_flag=True, help="对数据库中的数据补充市场代码")
@click.option('-c', '--count', is_flag=True, help="今天更新了多少只个股")
@click.option('-v', '--verbose', is_flag=True, help='详细模式')
@click.option('-t', '--test', is_flag=True, help='测试模式')
@click.option('-s2p', '--sqlite-to-pg', is_flag=True, help="从SQLite导出数据到PostgreSQL（两者连接的配置文件为 config.yaml）")
@click.option('-p2s', '--pg-to-sqlite', is_flag=True, help="从PostgreSQL导出数据到SQLite（两者连接的配置文件为 config.yaml）")
@click.option('-l', '--limit', 'limit', type=int, default=-1, help="限制处理的记录数")
def main(
    stocks: List[str],
    db_type: str,
    date: datetime,
    input_dir: str,
    all: bool,
    latest: bool,
    markets: List[str],
    list_markets: bool,
    slb_score_range: str,
    risk_score_range: str,
    risk_plot: bool,
    fill_market_code: bool,
    count: bool,
    verbose: bool,
    test: bool,
    sqlite_to_pg: bool,
    pg_to_sqlite: bool,
    limit: int,
):
    """把扫雷宝文件放入PostgreSQL/SQLite数据库
    """
    if not input_dir:
        date = datetime.combine(calc_belong_trading_day(date, datetime_time(hour=15)), datetime_time())
        input_dir = get_input_dir(date)

    print_locals()

    CFG = read_yaml_config()
    sqlite_cfg = CFG.get('sqlite', {'database' : ':memory:'})
    pg_cfg = CFG.get('postgresql', {})
    PG_URL = generate_engine_url_str(**pg_cfg)
    SQLITE_URL = generate_engine_url_str(**sqlite_cfg)
    PG_ENGINE = create_engine(PG_URL)
    SQLITE_ENGINE = create_engine(SQLITE_URL)

    # 数据迁移
    if sqlite_to_pg or pg_to_sqlite:

        try:

            if (not sqlite_cfg) or (not pg_cfg):
                raise Exception("配置文件必须含有sqlite 和 postgresql 的连接配置")

            
            if sqlite_to_pg:
                # SQlite → PostgreSQL
                CONSOLE.print("--- Migrating from SQLite to PostgreSQL ---")
                SLBDetail.init_db(PG_URL)
                sync_data_with_raw_sql(SQLITE_ENGINE, SLBDetail)
                
            elif pg_to_sqlite:
                # PostgreSQL → SQlite
                CONSOLE.print("--- Migrating from PostgreSQL to SQLite ---")
                SLBDetail.init_db(SQLITE_URL)
                sync_data_with_raw_sql(PG_ENGINE, SLBDetail)

        except Exception as e:
            CONSOLE.print_exception(extra_lines=5, show_locals=True)

        return


    # 初始化数据库
    if db_type:
        if db_type == 'sqlite':
            db_cfg = CFG.get('sqlite', {'database' : ':memory:'})
        elif db_type in ['postgresql', 'pg']:
            db_cfg = CFG.get('postgresql', {})
    else:
        W("使用 SQLite 内存数据库模式进行测试")
        db_cfg = {'database' : ':memory:'}

    if db_cfg:
        conn_str = generate_engine_url_str(**db_cfg)
        SLBDetail.init_db(conn_str, echo=verbose)
    else:
        E("配置缺失，请检查 config.yaml 文件")
        exit(1)


    # 补充全表中缺失的市场代码（ExchangeID）字段
    if fill_market_code:
        session = SLBDetail.get_session()
        try:
            details = SLBDetail.get_all(session)
            updated_count = 0
            if details:
                for detail in details:
                    if (detail == None) or (detail.ExchangeID is None) or (len(detail.ExchangeID) > 2):
                        I("✏️ 检测到 ExchangeID 缺失或错误，试图修复", InstrumentID=detail.InstrumentID, name=detail.name)
                        market_code = SecurityCode.guest_market(detail.InstrumentID)
                        D("猜测市场代码填入数据库", 市场代码=market_code)
                        detail.ExchangeID = market_code
                        updated_count += 1
            session.commit()

        except Exception as e:
            session.rollback()
            print(f"操作数据时出错: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            I(f"✅ 成功更新 {updated_count} 条记录")
            session.close()
            return updated_count


    if markets:
        if 'ALL' in markets:
            markets = ALL_MARKET_LIST

        for market in markets:
            if all:
                codes_in_market = SLBDetail.get_all_by_market(market, date)
            else:
                codes_in_market = SLBDetail.get_all_latest_by_market(market, date)

            I(f"发现 {len(codes_in_market)} 条最新记录", market=market, _level='STEP')
        return

    if list_markets:
        I(date=date, 市场列表=SLBDetail.get_markets_list(date), _level='RESULT')
        return

    if all and latest:
        records = SLBDetail.get_latest(date)
        if records:
            I(f"共找到 {len(records)} 只个股", date=date, _level='RESULT')
            if verbose:
                for i, record in enumerate(records):
                    I(f" {i}.", **record.to_dict(exclude_keys=['risk_data']))
        else:
            I("在此时间前没找到扫雷宝记录", date=date, _level='RESULT')
        return

    lower, upper = (-1, -1)
    if slb_score_range:
        upper, lower = str_to_range(slb_score_range)
        upper = 100 - upper
        lower = 100 - lower
    elif risk_score_range:
        lower, upper = str_to_range(risk_score_range)

    if lower >= 0 and upper >= 0:
        try:
            records = SLBDetail.get_latest_with_score_range((lower, upper), date)
            if records:
                I(f"共找到风险分介于 [{lower},{upper}) 中间的个股，共 {len(records)} 只", date=date, _level='RESULT')
                if verbose:
                    for i, record in enumerate(records):
                        I(f" {i}.", **record.to_dict(exclude_keys=['risk_data']))
            else:
                I("没找到扫雷宝记录", date=date, range=f'[{lower},{upper})', _level='RESULT')

        except Exception as e:
            print(f"报错: {e}")
            import traceback
            traceback.print_exc()

        return

    if risk_plot:
        # 简单使用 - 显示当前分数分布
        SLBDetail.plot_score_distribution()

        # 保存图片到文件
        SLBDetail.plot_score_distribution(save_path='risk_score_distribution.png')

        # 查看高风险股票分布
        SLBDetail.plot_score_distribution((30, 100), save_path='high_risk_stocks.png')

        # 生成详细分析报告
        SLBDetail.plot_detailed_score_analysis(save_path='detailed_analysis.png')
        return

    # 查询当前有效记录
    if stocks:
        for stock_code in stocks:
            code = SecurityCode(stock_code)
            I("查询当前有效记录", _level='STEP', code=code, type=code.security_type)
            if all:
                records = SLBDetail.get_all_by_code(code) # type: list['SLBDetail']
                if records:
                    I(date=date, 查找到记录数=len(records))
                    for i, record in enumerate(records):
                        cur_record_dict = record.to_dict(exclude_keys=['risk_data'])
                        I(f" {i}.", **cur_record_dict)
                        if i != 0:
                            last_record_dict = records[i-1].to_dict(exclude_keys=['risk_data'])
                            I(f"{i-1} -> {i}")
                            SLBDetail.show_differences(last_record_dict, cur_record_dict)
                else:
                    W("没有找到记录", date=date)
            else:
                record = SLBDetail.get_latest_by_code(code, date)
                if record is None:
                    W("无法查找对应时间的数据，取最近一条。去掉 date 限制继续查找...", date=date)
                    record = SLBDetail.get_latest_by_code(code)
                if record:
                    I(" ", **record.to_dict())
        return


    if count:
        belong_trading_date = calc_belong_trading_day(date)
        交易日收盘时间 = datetime.combine(belong_trading_date, datetime_time(hour=15))
        records = SLBDetail.get_all_created_later(交易日收盘时间) # type: List[SLBDetail]
        I("查找指定日期后更新记录", date=date, 交易日收盘时间=交易日收盘时间)
        if records:
            I(收盘后更新记录条数=len(records), _level='RESULT')
            if verbose:
                for i, record in enumerate(records):
                    old_record = SLBDetail.get_latest_by_code(
                        SecurityCode(record.InstrumentID, record.ExchangeID),
                        when=(record.created_at - timedelta(minutes=1))) # type: SLBDetail

                    if old_record:
                        SLBDetail.show_differences(
                            old_record.to_dict(exclude_keys=['risk_data']),
                            record.to_dict(exclude_keys=['risk_data'])
                        )
            return
        else:
            I("暂无查找到最近一个交易日的更新记录", _level='RESULT')
            if not click.confirm("是否继续入库？"):
                return

    # 插入或更新数据
    # 批量 SLB.{stock_code}.json 文件读到内存
    I(f"开始处理扫雷宝数据目录：{input_dir}", _level='STEP')
    mgr = SLBFileManager(input_dir)
    json_file_infos = mgr.list_all_files()
    D(files=json_file_infos)
    limiter = create_limiter(limit)

    codes_classify = {
        '无操作': [],
        '利空': [],
        '利好': [],
        '数据变更': [],
        '新增记录': [],
        '更新时间': [],
    }

    for file_info in json_file_infos:
        if not limiter():  # 逐个调试时用
            break

        stock_full_code = file_info['full_code']
        code = SecurityCode(stock_full_code)
        if code.security_type != SecurityType.STOCK:
            # 非 'stock' 没有扫雷宝数据（应该是混入指数了）
            I("删除混进来的非股票数据", file_info=file_info, security_type=code.security_type)
            # 删除该文件
            mgr.delete_file(code)

        json_data = mgr.load_data(code)

        if json_data:
            # 新数据
            new_record = SLBDetail(
                InstrumentID=code.short_code,
                ExchangeID=code.market_code,
                name=json_data['name'],
                total_risk_score=SLBDetail._calculate_total_score(json_data),
                risk_count=json_data['num'],
                risk_data=json_data,
                created_at=datetime.now(),
                updated_at=file_info.get('modified_time')
            )

            if test:
                result, old_record = SLBDetail.upsert(new_record, only_check=True)
                if old_record is None:
                    codes_classify['无操作'].append(code)
                elif result == 'update':
                    codes_classify['更新时间'].append(code)
                elif result == 'insert':
                    if new_record != old_record:
                        SLBDetail.show_differences(old_record, new_record)
                        if new_record < old_record:
                            codes_classify['利好'].append(code)
                        elif new_record > old_record:
                            codes_classify['利空'].append(code)
                        else:
                            codes_classify['数据变更'].append(code)
                elif result == 'new':
                    codes_classify['新增记录'].append(code)
                elif result == 'error':
                    break  # 出错就退出
            else:
                date_dt = file_info.get('modified_time', datetime.now())
                new_record = SLBDetail(
                    InstrumentID=code.short_code,
                    ExchangeID=code.market_code,
                    name=json_data['name'],
                    total_risk_score=SLBDetail._calculate_total_score(json_data),
                    risk_count=json_data['num'],
                    risk_data=json_data,
                    created_at=date_dt,
                    updated_at=date_dt,
                )
                _, old_record_dict = SLBDetail.upsert(new_record.to_dict())
                if new_record != old_record:
                    SLBDetail.show_differences(old_record_dict, new_record.to_dict())

    if test:
        I(  无操作_个=len(codes_classify['无操作']),
            利空_个=len(codes_classify['利空']),
            利好_个=len(codes_classify['利好']),
            数据变更_个=len(codes_classify['数据变更']),
            更新时间_个=len(codes_classify['更新时间']),
            新增记录_个=len(codes_classify['新增记录']),
            _level='RESULT')

        if not verbose:
            I(扫雷宝利空个股=[x.full_code for x in codes_classify['利空']], _color='bright_red')
            I(扫雷宝利好个股=[x.full_code for x in codes_classify['利好']], _color='bright_green')
    return

if __name__ == "__main__":
    main()

