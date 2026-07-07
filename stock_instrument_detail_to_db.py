#!python
# encoding: utf-8
# author: DifossChen
#
from difoss_stock_util import *
from difoss_stock_util.color_log_util import *
from difoss_stock_util.db_util_lazy_loading import *
from difoss_stock_util.metric_data import *

from sqlalchemy import TypeDecorator
from datetime import datetime, time, timedelta
import pytz
import json
from typing import Optional, List, Dict
from dictdiffer import diff
import click
from rich import print
from typing import DefaultDict

from xtquant import xtdata
xtdata.enable_hello = False
# -----------------------------------------------------------------------------------

ALL_MARKET_LIST = ['SH', 'SZ'] #, 'BJ'
ALL_DB_LIST = ['pg', 'postgresql', 'sqlite']
NOW_DT = datetime.now()
# -----------------------------------------------------------------------------------

@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.argument('stocks', nargs=-1, callback=split_comma, required=False)
@click.option('-s/-ns', '--need-save/--no-save', is_flag=True, help="保存成文件")
@click.option('-db', '--db-type', 'db_type', default='pg',
              type=click.Choice(ALL_DB_LIST, case_sensitive=False),
              help="选中该项后，会读取 config.yaml 文件中对应的数据库信息进行连接，默认是 pg")
@click.option('-d', '--date', type=DATETIME, default=NOW_DT, help="在什么时间查找（可用于历史数据回放）")
@click.option('-c', '--count', is_flag=True, help="今天更新了多少只个股")
@click.option('-v', '--verbose', is_flag=True, help='详细模式')
@click.option('-vv', '--very-verbose', 'very_verbose', is_flag=True, help='更加详细模式（打印json到控制台，慎用）')
@click.option('-t', '--test', is_flag=True, help='测试模式')
@click.option('-l', '--limit', type=int, default=-1, help='限制处理股票的数量')
@click.option('-s2p', '--sqlite-to-pg', is_flag=True, help="从SQLite导出数据到PostgreSQL（两者连接的配置文件为 config.yaml）")
@click.option('-m', '--market', 'markets', multiple=True, callback=split_comma,
              type=click.Choice([*ALL_MARKET_LIST, 'ALL'], case_sensitive=False),
              help='市场代码（可多次使用，自动转换大写，支持半角逗号分隔），如: -m SH -m SZ 或者 -m SH,SZ ')
@click.option('-a', '--all-market', is_flag=True, help="相当于 -m ALL，代表全市场")
@click.option('-q', '--quick', is_flag=True, help='快速模式（无进度显示）')
@click.option('-fix-rd', '--fix-remove-duplicate', is_flag=True, help='修复重复数据')
@click.pass_context
def main(
    _ctx: click.Context,
    stocks: List[str],
    need_save: bool,
    db_type: str,
    date: datetime,
    count: bool,
    verbose: bool,
    very_verbose: bool,
    test: bool,
    limit: int,
    sqlite_to_pg: bool,
    markets: List[str],
    all_market: bool,
    quick: bool,
    fix_remove_duplicate: bool,
):

    # _ctx.ensure_object(DefaultDict)

    if very_verbose:
        verbose = True
        
    print_locals()

    # 没办法动态改动 enumerate_with_progress，只能通过 import 了。
    from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import progress_print
    if quick:
        I("⚡ 快速模式：跳过所有进度显示")
        enumerate_with_progress = lambda items, start=0, **kwargs: enumerate(items, start=start)
    else:
        from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import enumerate_with_progress

    CFG = read_yaml_config()
    xtdata.enable_hello = very_verbose

    # 初始化数据库
    if db_type and db_type == 'sqlite':
        db_cfg = CFG.get('sqlite', {'database' : ':memory:'})
    elif db_type and (db_type in ['postgresql', 'pg']):
        db_cfg = CFG.get('postgresql', {})

    if db_cfg:
        conn_str = generate_engine_url_str(**db_cfg)
        StockInstrumentDetail.init_db(conn_str, echo=very_verbose, debug=verbose)

    if fix_remove_duplicate:
        latest_details = StockInstrumentDetail.get_latest() # type: Optional[List[StockInstrumentDetail]]
        print(f"最新股票代码数量: {len(latest_details)}")

        limiter = create_limiter(limit)
        count_deleted = 0
        for _, detail in enumerate_with_progress(latest_details, display_name_func=lambda d: d.InstrumentName):
            if not limiter():
                W("达到限制，停止处理", _level='RESULT')
                break
            if detail:
                code = SecurityCode(detail.InstrumentID, detail.ExchangeID)
                all_details_of_code = StockInstrumentDetail.get_all_by_code(code)# type: Optional[List[StockInstrumentDetail]]
                # 主要字段相同的仅保留最旧一个
                if all_details_of_code:

                    oldest_detail = None
                    is_first_XD = False

                    for i, d in enumerate(all_details_of_code):
                        # print(f"[{i}] {d}")
                        if d.InstrumentName.startswith('XD'):
                            if is_first_XD:
                                pre_d = all_details_of_code[i-1]
                                pre_d.update(InstrumentName=d.InstrumentID) # 修改上一条（XD的）
                                pre_d.InstrumentID = d.InstrumentID
                                oldest_detail = pre_d
                                is_first_XD = False

                            if oldest_detail is None:
                                # 第一条就遇到XD，标记并在下一条中修复
                                is_first_XD = True
                                print(f"[DEBUG] 第一条就是XD，在下一条修复名字并保留")
                                continue
                            else:
                                print(f"[TEST] 删除重复数据（由于分红XD导致的名字变更）: {d.id}")
                                count_deleted += 1
                                d.delete()
                                continue

                        if oldest_detail is None:
                            oldest_detail = d
                            continue

                        if d == oldest_detail:
                            print(f"[TEST] 删除重复数据: {d.id}")
                            count_deleted += 1
                            d.delete()
                        else:
                            oldest_detail = d

        print("本次删除重复数据数量:", count_deleted)
        return

    stocks_schedule: dict[SecurityCode, bool] = {}   # 记录处理的股票长代码（和对应到处理状态）

    # 处理输入参数
    if stocks:
        for stock in stocks:
            stocks_schedule.update({SecurityCode(stock): False})

    # DEBUG:
    D(stocks_schedule=stocks_schedule)

    if "ALL" in markets or all_market:
        markets = ALL_MARKET_LIST

    if verbose:
        I(markets=markets)

    belong_trading_date = calc_belong_trading_day(date)

    if count:
        交易日收盘时间 = datetime.combine(belong_trading_date, time(hour=15))
        records = StockInstrumentDetail.get_all_created_later(交易日收盘时间)
        I("查找指定日期后更新记录", date=date, 交易日收盘时间=交易日收盘时间)
        if records:
            I(收盘后更新记录条数=len(records), _level='RESULT')
            if verbose:
                for i, record in enumerate(records):
                    old_record = StockInstrumentDetail.get_latest_by_code(
                        SecurityCode(record.InstrumentID, record.ExchangeID),
                        when=(record.created_at - timedelta(minutes=1)))
                    
                    old_dict = old_record.to_dict() if old_record else {}
                    new_dict = record.to_dict() if record else {}

                    StockInstrumentDetail.show_differences(old_dict, new_dict)
            return
        else:
            I("暂无查找到最近一个交易日的更新记录", _level='RESULT')
            if not click.confirm("是否继续入库？"):
                return

    steps = [
        ("根据市场统计股票", 5),
        ("xtdata.get_instrument_detail 并逐一入库", 95),
    ]

    for step_NI, (step_name, step_progress) in enumerate_with_progress(
        steps,
        sizes=[s for _, s in steps],
        task_name=f"[bold]处理交易日 {belong_trading_date} 的扫雷数据",
        start=1,
    ):
        progress_print(f"\n[[yellow]STEP[/yellow]] {step_NI}/{len(steps)}: {step_name}")

        if step_NI == 1:
            try:
                for market in markets:
                    # 注意：get_stock_list_in_sector 返回的是带市场代码的证券长代码
                    stocks_in_market: Optional[dict[str]] = xtdata.get_stock_list_in_sector(market) # type: List[str]
                    stock_codes_in_market: list[SecurityCode] = []

                    if stocks_in_market:
                        for full_stock_code in stocks_in_market:
                            code = SecurityCode(full_stock_code)
                            if code.security_type == SecurityType.STOCK:
                                stocks_schedule.update({code: False})
                                stock_codes_in_market.append(code)
                    D(market=market, 证券数量=len(stocks_in_market), 个股数量=len(stock_codes_in_market))
            except Exception as e:
                W("无法从 xtquant 获取股票列表", sector=market, 异常=f"{e}")
                I("从现有库中的最近的全部股票列表", _level='STEP')
                SLBDetail.init_db(conn_str, echo=verbose)
                for market in markets:
                    records = SLBDetail.get_all_latest_by_market(market, date)
                    stock_codes_in_market: list[SecurityCode] = []
                    if records:
                        for record in records:
                            code = SecurityCode(record.InstrumentID, record.ExchangeID)
                            stocks_schedule.update({code: False})
                            stock_codes_in_market.append(code)
                    D(market=market, 个股数量=len(stock_codes_in_market))

            I(共有股票_个=len(stocks_schedule))



        if step_NI == 2:
            # 【正式逻辑】插入/更新数据库
            codes_classify = {
                '无操作': [],
                '利空': [],
                '利好': [],
                '数据变更': [],
                '新增记录': [],
                '更新时间': [],
            }
            stocks_list = sorted(set(stocks_schedule.keys()))
            limiter = create_limiter(limit) # 调试时解除注释

            for _, code in enumerate_with_progress(stocks_list):
                if not limiter():
                    W(f"达到最大个数限制，暂停处理", code=code, limit=limit)
                    break

                detail = xtdata.get_instrument_detail(code.full_code, True)
                if detail:
                    if verbose:
                        D(f"get_instrument_detail({code})", **{k:v for k,v in detail.items() if v}, _indent=2, _level='RETURN') # 去掉所有“空”值/零值的项

                    date_dt = datetime.now()
                    new_record = dict(
                        ExchangeID = detail.get('ExchangeID'),
                        InstrumentID = detail.get('InstrumentID'),
                        InstrumentName = detail.get('InstrumentName'),
                        OpenDate = IntegerDate.date_to_int_not_throw(detail.get('OpenDate')),
                        ExpireDate = IntegerDate.date_to_int_not_throw(detail.get('ExpireDate')),
                        FloatVolume = detail.get('FloatVolume'),
                        TotalVolume = detail.get('TotalVolume'),
                        InstrumentStatus = detail.get('InstrumentStatus'),
                        created_at = date_dt,
                        updated_at = date_dt,
                    )

                    if test:
                        result, old_record = StockInstrumentDetail.upsert(new_record, only_check=True)
                        if old_record is None:
                            codes_classify['无操作'].append(code)
                        elif result == 'update':
                            codes_classify['更新时间'].append(code)
                        elif result == 'insert':
                            if new_record != old_record:
                                StockInstrumentDetail.show_differences(old_record, new_record)
                                if StockInstrumentDetail.has_more_risk(old_record, new_record):
                                    codes_classify['利好'].append(code)
                                elif StockInstrumentDetail.has_more_risk(new_record, old_record):
                                    codes_classify['利空'].append(code)
                                else:
                                    codes_classify['数据变更'].append(code)
                        elif result == 'new':
                            codes_classify['新增记录'].append(code)
                        elif result == 'error':
                            break  # 出错就退出
                    else:
                        _, old_record = StockInstrumentDetail.upsert(new_record)
                        if new_record != old_record:
                            StockInstrumentDetail.show_differences(old_record, new_record)
                else:
                    E(f"get_instrument_detail() 失败", full_code=code.full_code)


    # 把股票列表打印到文件中（可用于对比差异）
    if need_save and markets:
        with open(f'{db_type}-{','.join(markets)}-{date.strftime('%Y-%m-%d')}.txt', 'w+') as STOCKS_FILE:
            STOCKS_FILE.writelines([x.full_code + '\n' for x in stocks_schedule.keys()])

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
