#!python
# encoding: utf-8
# author: DifossChen
#
import requests
import json
import sys
import time
from datetime import datetime, timedelta, time as datetime_time
from typing import List, Optional
from pathlib import Path
from difoss_stock_util.metric_data import *

def fetch_tdx_json(stock_code):
    """
    抓取通达信股票 JSON 数据

    Args:
        stock_code (str): 6位股票代码（如 "000507"）

    Returns:
        dict: 解析后的 JSON 数据（如果成功）
        str: 错误信息（如果失败）
    """

    code = SecurityCode(stock_code)
    url = f"http://page3.tdx.com.cn:7615/site/pcwebcall_static/bxb/json/{code.short_code}.json"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Referer": "http://page3.tdx.com.cn:7615/site/pcwebcall_static/bxb/bxb.html",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    }

    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        return json.loads(response.text)

    return None


def calculate_total_fs(data):
    total_minus_fs = 0

    # 遍历所有data条目
    for category in data.get("data", []):
        # 遍历每个category中的rows
        for row in category.get("rows", []):
            # 检查row本身的trig
            if row.get("trig") == 1:
                total_minus_fs += row.get("fs", 0)

    return 100 - total_minus_fs


from difoss_stock_util import *
from difoss_stock_util.xtquant_util import get_market_stocks
from difoss_stock_util.slb_file_mgr import SLBFileManager
from difoss_stock_util.db_util import get_local_stocks
from difoss_stock_util.color_log_util import *
import click
from rich import print
from pathlib import Path
from typing import Callable
from xtquant import xtdata
xtdata.enable_hello = False

# --------------------------------------------------------------------------------------------------------------------
NOW_DT = datetime.now()
BELONG_TRADING_DATE = calc_belong_trading_day(NOW_DT, datetime_time(hour=15))
DEFAULT_OUTPUT_FOLDER = SLBFileManager.generate_dirname(BELONG_TRADING_DATE)
ALL_MARKET_LIST = ['SH', 'SZ'] # 扫雷宝只目前包含沪深两市 ['SH', 'SZ', 'IF', 'DF', 'SF', 'ZF']
ALL_DB_LIST = ['pg', 'postgresql', 'sqlite']

# global variables
g_max_try_times = 3
# --------------------------------------------------------------------------------------------------------------------

@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.argument('stocks', nargs=-1, required=False)
@click.option('-s/-ns', '--save/--no-save', is_flag=True, default=True, help="保存成文件")
@click.option('-db', '--db-type', default='pg', show_default=True,
              type=click.Choice(ALL_DB_LIST, case_sensitive=False),
              help="选中该项后，会读取 config.yaml 文件中对应的数据库信息进行连接")
@click.option('-m', '--market', 'markets', multiple=True,
              type=click.Choice([*ALL_MARKET_LIST, 'ALL'], case_sensitive=False),
              help='过滤市场代码（可多次使用，自动转换大写），如: -m SH -m SZ。')
@click.option('-a', '--all-markets', is_flag=True, help="相当于 -m ALL，代表全市场")
@confirmable_option('--clean', is_flag=True,
    help="清空当天（最后一个交易日）的全部json文件",
    confirm_message="⚠️ 是否确定要清空当天下载的全部json文件？")
@click.option('-v', '--verbose', is_flag=True, help='详细模式')
@click.option('-vv', '--very-verbose', 'very_verbose', is_flag=True, help='更加详细模式（打印json到控制台，慎用）')
@click.option('-to-db/-not-to-db', '--to-db/--not-to-db', is_flag=True, default=True, show_default=True, help="是否直接更新数据库")
@click.option('-t', '--test', is_flag=True, help='测试模式')
@click.option('-q', '--quick', is_flag=True, help='快速模式（无进度显示）')
@click.option('-d', '--debug', is_flag=True, help='调试模式')
@click.option('-gf', '--only-generate-diy-file', 'only_generate_diy_file', is_flag=True, help='只生成【自定义序列】文件')
@click.option('-version', '--version', type=int, default=2, help='使用的API版本')
def main(
    stocks: List[str],
    save: bool,
    db_type: str,
    markets: List[str],
    all_markets: bool,
    clean: bool,
    verbose: bool,
    very_verbose: bool,
    to_db: bool,
    test: bool,
    quick: bool,
    debug: bool,
    only_generate_diy_file: bool,
    version: int,
):
    """把股票（或特定市场上的所有股票）的扫雷宝数据（json）保存到本地文件中
    """

    print_locals()

    if very_verbose:
        verbose = True

    # 不支持参数输入，读取配置文件 config.yaml
    CFG = read_yaml_config()
    SLB_BASE_DIR = Path(CFG['slb']['base_dir'])
    output_dir = SLB_BASE_DIR / DEFAULT_OUTPUT_FOLDER
    I("扫雷宝数据将保存到此目录：", output_dir=output_dir)
    # 处理文件夹
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)

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
        SLBDetail.init_db(conn_str, echo=very_verbose, debug=debug)
    else:
        E("配置缺失，请检查 config.yaml 文件")
        exit(1)

    stocks_schedule = {} # 记录处理的股票长代码（和对应到处理状态）  # type: Dict[str, bool]

    # 处理输入参数
    if stocks:
        for stock in list(stocks):
            stocks_schedule.update({SecurityCode(stock).full_code: False})

    if "ALL" in markets or all_markets:
        markets = ALL_MARKET_LIST

    if verbose:
        I(markets=markets)

    # 没办法动态改动 enumerate_with_progress，只能通过 import 了。
    from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import progress_print
    if quick:
        I("⚡ 快速模式：跳过所有进度显示")
        enumerate_with_progress = lambda items, start=0, **kwargs: enumerate(items, start=start)
    else:
        from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import enumerate_with_progress

    if clean:
        I("⚠️ 准备删除所有json文件...", dir=output_dir)
        _, existed_json_files = walk(output_dir, include_extensions=".json", without_root_path=False)
        I("待删除的文件数量：", total=len(existed_json_files))
        for _, ejf in enumerate_with_progress(existed_json_files, task_name="[bold]删除当天扫雷宝文件"):
            os.remove(ejf)
        return

    steps = [
        ("根据市场统计股票", 5),
        ("统计现有扫雷宝文件", 11),
        ("下载新的扫雷宝数据", 40),
        ("文件对比入库", 40),
        ("生成【自定义序列(字符串,数值)】【自定义序列(日期,数值)】文件", 4),
    ]

    if only_generate_diy_file: # 只生成【自定义序列】文件，只拿4,5步
        steps = steps[4:]
        start = 5
    else:
        start = 1

    I(steps=steps, start=start)

    for step_NI, (step_name, step_prog_size) in enumerate_with_progress(
        steps,
        sizes=[s for _, s in steps],
        task_name=f"[bold]处理交易日 {BELONG_TRADING_DATE} 的扫雷宝数据",
        start=start):  # NI：Natural Index

        progress_print(f"\n[[yellow]STEP[/yellow]] {step_NI-start+1}/{len(steps)}: {step_name}")

        if step_NI == 1: # 遍历股票代码 -----------------------------------------------------------------------------------------------------
            try:
                for _, market in enumerate_with_progress(markets, task_name=step_name, start=1):
                    progress_print(f"   📈 处理市场: {market}")
                    # 注意：get_stock_list_in_sector 返回的是带市场代码的证券长代码
                    stock_codes_in_market = get_market_stocks(market)
                    # D("stock_codes_in_market() return: ", _len=len(stock_codes_in_market))
                    stocks_schedule.update({code.full_code: False for code in stock_codes_in_market})
                    D(market=market, 个股数量=len(stock_codes_in_market))
                    if verbose:
                        print(f"具体个股：{stock_codes_in_market}")
            except Exception as e:
                W("无法从 xtquant 获取股票列表", sectors=markets, 异常=f"{e}")
                I("从现有库中的最近的全部股票列表", _level='STEP')
                for _, market in enumerate_with_progress(markets):
                    stock_codes_in_market = get_local_stocks(market, SLBDetail)
                    stocks_schedule.update({code.full_code: False for code in stock_codes_in_market})
                    D(market=market, 个股数量=len(stock_codes_in_market))
                    if verbose:
                        print(f"具体个股：{stock_codes_in_market}")

        elif step_NI == 2: # 统计需要处理的股票个数和输出文件中的文件个数 ---------------------------------------------------------------------
            all_count = len(stocks_schedule)
            stocks_existing = []

            mgr = SLBFileManager(output_dir)
            stocks_existing = mgr.get_stock_codes()
            for _, full_code in enumerate_with_progress(stocks_existing, task_name=step_name):
                stocks_schedule.pop(full_code, None) # 为优化速度，直接踢出已经下载的 code

            I("🚧", 股票总数=all_count, 已经下载文件=len(stocks_existing),
                需要处理_个=len(stocks_schedule))

            if verbose:
                I(需处理个股=stocks_schedule.keys())

        elif step_NI == 3: # 下载 -------------------------------------------------------------------------------------------------------------
            for _, stock_code in enumerate_with_progress(stocks_schedule.keys(), task_name=step_name):
                json_filename = f'SLB.{stock_code}.json'
                json_filepath = os.path.join(output_dir, json_filename)

                result = None  # json object
                json_str = None # json string(indented)

                if os.path.exists(json_filepath):
                    D('⚠️ 文件已存在，跳过', fn=json_filename)
                    with open(json_filepath, 'r', encoding='utf-8') as F:
                        json_str = F.read()
                        result = json.loads(json_str)
                else:
                    I("🔽 尝试获取股票JSON数据", stock_code=stock_code)
                    try:
                        result = fetch_tdx_json(stock_code)
                    except Exception as e:
                        E("通达信扫雷宝接口出错", stock=stock_code, 异常=f"{e}")
                        return

                    json_str = json.dumps(result, indent=2, ensure_ascii=False)

                    if result:
                        if save:
                            I("✏️ 写入文件", stock_code=stock_code)
                            with open(json_filepath, 'w', encoding='utf-8') as F:
                                F.write(json_str)
                        else:
                            W("⚠️ 忽略不写文件", stock_code=stock_code)

                    else:
                        full_stock_code = SecurityCode.guess_full_code(stock_code)
                        E("❌ 无法获取股票JSON 数据", code=stock_code, name=stock_code, full_stock_code=full_stock_code)
                        continue


                if very_verbose:
                    D(f"✅ 成功获取股票 {stock_code} 的 JSON 数据：{json_str}")

                if result:
                    total_fs = SLBDetail._calculate_total_score(result)
                    stock_name = result.get('name', '(未知股票)')
                    I(code=stock_code, name=stock_name, 扫雷宝总分=total_fs)

        elif step_NI == 4: # 入库 -------------------------------------------------------------------------------------------------------------
            if to_db:
                input_dir = str(SLB_BASE_DIR / DEFAULT_OUTPUT_FOLDER)
                # 插入或更新数据
                # 批量 SLB.{stock_code}.json 文件读到内存
                I(f"开始处理扫雷宝数据目录：{input_dir}", _level='STEP')
                mgr = SLBFileManager(input_dir)
                json_file_infos = mgr.list_all_files()
                # D(files=files, _indent=2)
                # limiter = create_limiter(1)

                codes_classify = {
                    '无操作': [],
                    '利空': [],
                    '利好': [],
                    '数据变更': [],
                    '新增记录': [],
                    '更新时间': [],
                }

                for _, file_info in enumerate_with_progress(json_file_infos, task_name=step_name):
                    # if not limiter():  # 逐个调试时用
                    #     break

                    stock_full_code = file_info['full_code']
                    code = SecurityCode(stock_full_code)
                    # D(file_info=file_info, code=code.to_dict(), _level='TEST')
                    if code.security_type != SecurityType.STOCK:
                        # 非 'stock' 没有扫雷宝数据（应该是混入指数了）
                        I("删除混进来的非股票数据", file_info=file_info, security_type=code.security_type)
                        # 删除该文件
                        mgr.delete_file(code)

                    json_data = mgr.load_data(code)

                    if json_data:
                        # 新数据
                        new_record = dict(
                            InstrumentID=code.short_code,
                            ExchangeID=code.market_code,
                            name=json_data['name'],
                            total_risk_score=SLBDetail._calculate_total_score(json_data),
                            risk_count=json_data['num'],
                            risk_data=json_data,
                            created_at=datetime.now(),
                            updated_at=file_info.get('modified_time', datetime.now())
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
                                    if SLBDetail.has_more_risk(new_record, old_record):
                                        codes_classify['利好'].append(code)
                                    elif SLBDetail.has_more_risk(old_record, new_record):
                                        codes_classify['利空'].append(code)
                                    else:
                                        codes_classify['数据变更'].append(code)
                            elif result == 'new':
                                codes_classify['新增记录'].append(code)
                            elif result == 'error':
                                break  # 出错就退出
                        else:
                            try:
                                result, old_record_dict = SLBDetail.upsert(new_record)
                                # if result in ['insert', 'new']:
                                #     progress_print(f"upsert() return: result={result}, old.score={old_record_dict.get('total_risk_score')}, new.score={new_record_dict.get('total_risk_score')}")
                                SLBDetail.show_differences(old_record_dict, new_record)
                            except Exception as e:
                                E(f"Error occurred during upsert: ", error=e, **new_record)
                                import traceback
                                traceback.print_exc()
                                exit(1)

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

        elif step_NI == 5: # 生成【自定义序列(字符串,数值)】和【自定义序列(日期,数值)】文件
            # 【自定义序列(字符串,数值)】
            diy_filename = CFG['slb']['user_diy_data']
            diy_filepath = SLB_BASE_DIR / DEFAULT_OUTPUT_FOLDER / diy_filename # type: Path

            I(diy_filepath=diy_filepath)

            #【自定义序列(日期,数值)】文件

            trading_date_str = BELONG_TRADING_DATE.strftime("%Y%m%d")

            diy_daily_filename = CFG['slb']['user_diy_data_by_date']
            I(diy_daily_filename=diy_daily_filename)

            # 处理转义字符
            if '{date}' in diy_daily_filename:
                diy_daily_filename = str(diy_daily_filename).format(date=trading_date_str)

            I(diy_daily_filename=diy_daily_filename)
            diy_daily_filepath = SLB_BASE_DIR / DEFAULT_OUTPUT_FOLDER / diy_daily_filename # type: Path

            diy_lines = []
            diy_daily_lines = []

            if not diy_filepath.exists() or not diy_daily_filepath.exists():
                for _, market in enumerate_with_progress(ALL_MARKET_LIST):
                    today_records = SLBDetail.get_all_latest_by_market(market_code=market) # type: List[SLBDetail]
                    market_int_in_str = ("0", "1")[market == 'SH']

                    I(f"{market} 市场 拥有 {len(today_records)} 个 个股信息")
                    for _, record in enumerate_with_progress(today_records, display_name_func=lambda d: f"{d.InstrumentID} {d.name}"):
                        slb_score = 100 - record.total_risk_score
                        slb_score = max(1, min(100, slb_score)) # 确保在1-100范围内
                        
                        # DEBUG: 由于通达信自定义字段在板块列表中以字符串格式排序，导致降序排列时，100分（1开头）反而会排在90之后（9开头），
                        # 所以：字符格式保留 3位整数，不保留小数，前面补零，如 001, 023, 100
                        slb_score_str = f"{int(slb_score):03d}"
                        # 格式：{market_code}|{stock_short_code})|{SLB Score}|{SLB Score}
                        diy_lines.append("|".join([market_int_in_str, record.InstrumentID, slb_score_str, f'{slb_score}']) + '\n')
                        # 格式：{market_code}|{stock_short_code})|{YYYYMMDD}|{SLB Score}
                        diy_daily_lines.append("|".join([market_int_in_str, record.InstrumentID, trading_date_str, slb_score_str]) + '\n')

                if diy_filepath.exists():
                    W(f"文件 {diy_filename} 已存在，忽略不处理")
                else:
                    with open(diy_filepath, 'w', encoding='utf-8') as DIY_DATA_FILE:
                        DIY_DATA_FILE.writelines(diy_lines)
                    I(f"文件 {diy_filename} 共写入 {len(diy_lines)} 只个股信息")


                if diy_daily_filepath.exists():
                    W(f"文件 {diy_daily_filename} 已存在，忽略不处理")
                else:
                    with open(diy_daily_filepath, 'w', encoding='utf-8') as DIY_DAILY_FILE:
                        DIY_DAILY_FILE.writelines(diy_daily_lines)
                    I(f"文件 {diy_daily_filename} 共写入 {len(diy_daily_lines)} 只个股信息")


if __name__ == "__main__":
    main()
