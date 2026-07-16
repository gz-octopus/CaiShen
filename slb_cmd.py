#!python
# -*- coding: utf-8 -*-
"""扫雷宝数据 CLI 命令模块"""

import click
from rich import print as pprint
from rich.console import Console
from datetime import datetime, timedelta, time as datetime_time
from pathlib import Path
import os
import json
import requests
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from difoss_stock_util import *
from difoss_stock_util.xtquant_util import get_market_stocks
from difoss_stock_util.slb_file_mgr import SLBFileManager
from difoss_stock_util.color_log_util import *
from difoss_stock_util.click_util import *
from difoss_stock_util.util import read_yaml_config, print_locals
from difoss_stock_util.db_util import *
from difoss_stock_util.db_util import get_local_stocks
from difoss_stock_util.metric_data.slb import SLBDetail
from difoss_stock_util.security_util import SecurityCode, SecurityType
from difoss_stock_util.stock_util import calc_belong_trading_day

# --------------------------------------------------------------------------------
ALL_MARKET_LIST = ['SH', 'SZ']  # TODO: 目前扫雷宝只支持沪深两市个股
ALL_DB_LIST = ['pg', 'postgresql', 'sqlite']

def get_input_dir(date: datetime, cfg: dict) -> str:
    """根据日期和配置获取扫雷宝目录"""
    belong_trading_date = calc_belong_trading_day(date, datetime_time(hour=15))
    default_output_folder = SLBFileManager.generate_dirname(belong_trading_date)
    slb_base_dir = Path(cfg['slb']['base_dir'])
    return str(slb_base_dir / default_output_folder)

# --------------------------------------------------------------------------------
# 扫雷宝数据获取函数
def fetch_tdx_json(stock_code):
    """
    抓取通达信股票 JSON 数据
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

# --------------------------------------------------------------------------------
# 数据库初始化函数
def init_database(db_type: str, cfg: dict, verbose: bool = False, debug: bool = False) -> bool:
    """初始化数据库连接"""
    try:
        if db_type == 'sqlite':
            db_cfg = cfg.get('sqlite', {'database': ':memory:'})
        elif db_type in ['postgresql', 'pg']:
            db_cfg = cfg.get('postgresql', {})
        else:
            W(f"未知的数据库类型: {db_type}")
            return False

        if db_cfg:
            conn_str = generate_engine_url_str(**db_cfg)
            SLBDetail.init_db(conn_str, echo=verbose, debug=debug)
            I(f"✅ 数据库初始化成功: {db_type}")
            return True
        else:
            E("数据库配置缺失，请检查 config.yaml 文件")
            return False
    except Exception as e:
        E(f"数据库初始化失败: {e}")
        return False

# --------------------------------------------------------------------------------
# 扫雷宝数据下载命令
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, help='股票代码列表 (如: 688318.SH)')
@click.option('--market', '-m', 'markets', multiple=True, callback=split_comma_upper,
              type=click.Choice([*ALL_MARKET_LIST, 'ALL'], case_sensitive=False), default=['ALL'], help='市场代码（ALL：所有市场）')
@click.option('--all-markets', '-a', 'all_markets', is_flag=True, help="全市场（相当于 -m ALL）")
@click.option('--save/--no-save', '-s/-ns', 'save', is_flag=True, default=True, help="保存成文件")
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.option('--very-verbose', '-vv', 'very_verbose', is_flag=True, help='更加详细模式（打印json到控制台，慎用）')
@click.option('--quick', '-q', 'quick', is_flag=True, help='快速模式（无进度显示）')
@click.pass_context
def download(_ctx: click.Context,
             stocks: List[str],
             markets: List[str],
             all_markets: bool,
             save: bool,
             verbose: bool,
             very_verbose: bool,
             quick: bool):
    """下载扫雷宝数据"""

    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    # 设置时间变量
    NOW_DT = datetime.now()
    BELONG_TRADING_DATE = calc_belong_trading_day(NOW_DT, datetime_time(hour=15))
    DEFAULT_OUTPUT_FOLDER = SLBFileManager.generate_dirname(BELONG_TRADING_DATE)

    # 读取扫雷宝基础目录配置
    SLB_BASE_DIR = Path(_CFG['slb']['base_dir'])
    output_dir = SLB_BASE_DIR / DEFAULT_OUTPUT_FOLDER

    # 处理文件夹
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)
        _CSL.print(f"✅ 创建输出目录: {output_dir}")

    # 处理市场参数
    if "ALL" in markets or all_markets:
        markets = ['SH', 'SZ']

    # 收集需要处理的股票
    stocks_schedule = {}  # type: Dict[str, bool]

    if stocks:
        for stock in stocks:
            stocks_schedule.update({SecurityCode(stock).full_code: False})

    # 如果指定了市场，获取市场中的所有股票
    if markets:
        try:
            for market in markets:
                _CSL.print(f"📈 处理市场: {market}")
                # 获取市场中的股票
                stock_codes_in_market = get_market_stocks(market)
                stocks_schedule.update({code.full_code: False for code in stock_codes_in_market})
                _CSL.print(f"   市场 {market} 共有 {len(stock_codes_in_market)} 只个股")
        except Exception as e:
            W(f"无法从 xtquant 获取股票列表: {e}")
            _CSL.print("从现有库中的最近的全部股票列表")
            for market in markets:
                stock_codes_in_market = get_local_stocks(market, SLBDetail)
                stocks_schedule.update({code.full_code: False for code in stock_codes_in_market})
                _CSL.print(f"   市场 {market} 共有 {len(stock_codes_in_market)} 只个股")

    # 统计现有文件
    mgr = SLBFileManager(output_dir)
    stocks_existing = mgr.get_stock_codes()
    for full_code in stocks_existing:
        stocks_schedule.pop(full_code, None)  # 移除已经下载的股票

    _CSL.print(f"🚧 股票总数: {len(stocks_schedule)}")

    if not stocks_schedule:
        _CSL.print("✅ 所有股票数据已是最新，无需下载")
        return

    # 下载数据
    if quick:
        enumerate_with_progress = lambda items, **kwargs: enumerate(items)
    else:
        from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import enumerate_with_progress

    for _, stock_code in enumerate_with_progress(stocks_schedule.keys(), task_name="下载扫雷宝数据"):
        json_filename = f'SLB.{stock_code}.json'
        json_filepath = os.path.join(output_dir, json_filename)

        if os.path.exists(json_filepath):
            if verbose:
                _CSL.print(f'⚠️ 文件已存在，跳过: {json_filename}')
            continue

        _CSL.print(f"🔽 尝试获取股票JSON数据: {stock_code}")
        try:
            result = fetch_tdx_json(stock_code)
        except Exception as e:
            E(f"通达信扫雷宝接口出错: {e}", stock=stock_code)
            continue

        if result:
            json_str = json.dumps(result, indent=2, ensure_ascii=False)

            if save:
                with open(json_filepath, 'w', encoding='utf-8') as F:
                    F.write(json_str)
                _CSL.print(f"✏️ 写入文件: {stock_code}")

            if very_verbose:
                _CSL.print(f"✅ 成功获取股票 {stock_code} 的 JSON 数据：{json_str}")

            total_fs = SLBDetail._calculate_total_score(result)
            stock_name = result.get('name', '(未知股票)')
            _CSL.print(f"📊 {stock_code} {stock_name} 扫雷宝总分: {total_fs}")
        else:
            full_stock_code = SecurityCode.guess_full_code(stock_code)
            E(f"❌ 无法获取股票JSON数据: {stock_code} ({full_stock_code})")

# --------------------------------------------------------------------------------
# 数据库入库命令
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--db-type', '-db', default='pg', show_default=True,
              type=click.Choice(['pg', 'postgresql', 'sqlite'], case_sensitive=False),
              help="数据库类型")
@click.option('--date', '-d', 'date', type=DATETIME, default=None, help="指定日期（用于历史数据回放）")
@click.option('--input-dir', '-i', 'input_dir', default=None, help="扫雷宝json文件所在目录")
@click.option('--limit', '-l', 'limit', type=int, default=-1, help="限制处理的记录数")
@click.option('--test', '-t', 'test', is_flag=True, help='测试模式（只检查不实际入库）')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.option('--debug', '-d', 'debug', is_flag=True, help='调试模式')
@click.pass_context
def import_to_db(_ctx: click.Context,
                 db_type: str,
                 date: Optional[datetime],
                 input_dir: Optional[str],
                 limit: int,
                 test: bool,
                 verbose: bool,
                 debug: bool):
    """将扫雷宝数据导入数据库"""

    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    if date is None:
        date = datetime.now()

    if input_dir is None:
        input_dir = get_input_dir(date, _CFG)

    # 初始化数据库
    if not init_database(db_type, _CFG, verbose, debug):
        return

    _CSL.print(f"📂 开始处理扫雷宝数据目录：{input_dir} (date: {date.strftime('%Y-%m-%d')})")

    # 获取所有文件
    mgr = SLBFileManager(input_dir)
    json_file_infos = mgr.list_all_files()

    if not json_file_infos:
        _CSL.print("❌ 没有找到扫雷宝数据文件")
        return

    _CSL.print(f"📄 找到 {len(json_file_infos)} 个扫雷宝数据文件")

    limiter = create_limiter(limit)

    codes_classify = {
        '无操作': [],
        '利空': [],
        '利好': [],
        '数据变更': [],
        '新增记录': [],
        '更新时间': [],
    }

    from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import enumerate_with_progress

    for _, file_info in enumerate_with_progress(json_file_infos, task_name="导入数据库"):
        if not limiter():
            break

        stock_full_code = file_info['full_code']
        code = SecurityCode(stock_full_code)

        # 检查是否为股票类型
        if code.security_type != SecurityType.STOCK:
            if verbose:
                _CSL.print(f"⚠️ 删除非股票数据: {file_info['filename']} ({code.security_type})")
            mgr.delete_file(code)
            continue

        json_data = mgr.load_data(code)

        if not json_data:
            _CSL.print(f"⚠️ 无法加载数据: {stock_full_code}")
            continue

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
                break
        else:
            try:
                result, old_record_dict = SLBDetail.upsert(new_record)
                if verbose:
                    _CSL.print(f"📝 {stock_full_code}: {result}")
            except Exception as e:
                E(f"入库失败: {e}", **new_record)
                import traceback
                traceback.print_exc()

    # 显示统计结果
    _CSL.print("\n📊 入库统计结果:")
    _CSL.print(f"   无操作: {len(codes_classify['无操作'])} 只")
    _CSL.print(f"   利空: {len(codes_classify['利空'])} 只")
    _CSL.print(f"   利好: {len(codes_classify['利好'])} 只")
    _CSL.print(f"   数据变更: {len(codes_classify['数据变更'])} 只")
    _CSL.print(f"   更新时间: {len(codes_classify['更新时间'])} 只")
    _CSL.print(f"   新增记录: {len(codes_classify['新增记录'])} 只")

    if test and verbose:
        if codes_classify['利空']:
            _CSL.print("\n🔴 扫雷宝利空个股:")
            for code in codes_classify['利空']:
                _CSL.print(f"   {code.full_code}")

        if codes_classify['利好']:
            _CSL.print("\n🟢 扫雷宝利好个股:")
            for code in codes_classify['利好']:
                _CSL.print(f"   {code.full_code}")

# --------------------------------------------------------------------------------
# 生成自定义序列文件命令
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--db-type', '-db', default='pg', show_default=True,
              type=click.Choice(['pg', 'postgresql', 'sqlite'], case_sensitive=False),
              help="数据库类型")
@click.option('--date', '-d', 'date', type=DATETIME, default=None, help="指定日期")
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.pass_context
def generate_diy_files(_ctx: click.Context,
                       db_type: str,
                       date: Optional[datetime],
                       verbose: bool):
    """生成【自定义序列(字符串,数值)】和【自定义序列(日期,数值)】文件"""

    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    if date is None:
        date = datetime.now()

    # 设置时间变量
    BELONG_TRADING_DATE = calc_belong_trading_day(date, datetime_time(hour=15))
    DEFAULT_OUTPUT_FOLDER = SLBFileManager.generate_dirname(BELONG_TRADING_DATE)

    # 读取扫雷宝基础目录配置
    SLB_BASE_DIR = Path(_CFG['slb']['base_dir'])
    output_dir = SLB_BASE_DIR / DEFAULT_OUTPUT_FOLDER

    # 初始化数据库
    if not init_database(db_type, _CFG, verbose):
        return

    # 【自定义序列(字符串,数值)】
    diy_filename = _CFG['slb']['user_diy_data']
    diy_filepath = output_dir / diy_filename

    # 【自定义序列(日期,数值)】文件
    trading_date_str = BELONG_TRADING_DATE.strftime("%Y%m%d")
    diy_daily_filename = _CFG['slb']['user_diy_data_by_date']

    # 处理转义字符
    if '{date}' in diy_daily_filename:
        diy_daily_filename = str(diy_daily_filename).format(date=trading_date_str)

    diy_daily_filepath = output_dir / diy_daily_filename

    _CSL.print(f"📁 输出目录: {output_dir}")
    _CSL.print(f"📄 自定义序列文件: {diy_filename}")
    _CSL.print(f"📅 每日自定义序列文件: {diy_daily_filename}")

    diy_lines = []
    diy_daily_lines = []

    # 检查文件是否已存在
    if diy_filepath.exists() and diy_daily_filepath.exists():
        _CSL.print("✅ 自定义序列文件已存在，跳过生成")
        return

    # 从数据库获取最新数据
    for market in ['SH', 'SZ']:
        today_records = SLBDetail.get_all_latest_by_market(market_code=market)  # type: List[SLBDetail]
        market_int_in_str = ("0", "1")[market == 'SH']

        _CSL.print(f"📊 {market} 市场: {len(today_records)} 只个股")

        for record in today_records:
            slb_score = 100 - record.total_risk_score
            slb_score = max(1, min(100, slb_score))  # 确保在1-100范围内

            # 字符格式保留 3位整数，不保留小数，前面补零，如 001, 023, 100
            slb_score_str = f"{int(slb_score):03d}"

            # 格式：{market_code}|{stock_short_code})|{SLB Score}|{SLB Score}
            diy_lines.append("|".join([market_int_in_str, record.InstrumentID, slb_score_str, f'{slb_score}']) + '\n')

            # 格式：{market_code}|{stock_short_code})|{YYYYMMDD}|{SLB Score}
            diy_daily_lines.append("|".join([market_int_in_str, record.InstrumentID, trading_date_str, slb_score_str]) + '\n')

    # 写入自定义序列文件
    if not diy_filepath.exists():
        with open(diy_filepath, 'w', encoding='utf-8') as DIY_DATA_FILE:
            DIY_DATA_FILE.writelines(diy_lines)
        _CSL.print(f"✅ 生成自定义序列文件: {diy_filename} ({len(diy_lines)} 只个股)")
    else:
        _CSL.print(f"⚠️ 自定义序列文件已存在: {diy_filename}")

    # 写入每日自定义序列文件
    if not diy_daily_filepath.exists():
        with open(diy_daily_filepath, 'w', encoding='utf-8') as DIY_DAILY_FILE:
            DIY_DAILY_FILE.writelines(diy_daily_lines)
        _CSL.print(f"✅ 生成每日自定义序列文件: {diy_daily_filename} ({len(diy_daily_lines)} 只个股)")
    else:
        _CSL.print(f"⚠️ 每日自定义序列文件已存在: {diy_daily_filename}")

# --------------------------------------------------------------------------------
# 清理文件命令
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@confirmable_option('--clean', is_flag=True,
    help="清空当天（最后一个交易日）的全部json文件",
    confirm_message="⚠️ 是否确定要清空当天下载的全部json文件？")
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.pass_context
def clean_files(_ctx: click.Context,
                clean: bool,
                verbose: bool,
):
    """清理扫雷宝数据文件"""

    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    if not clean:
        _CSL.print("请使用 --clean 参数来清理文件")
        return

    # 设置时间变量
    NOW_DT = datetime.now()
    BELONG_TRADING_DATE = calc_belong_trading_day(NOW_DT, datetime_time(hour=15))
    DEFAULT_OUTPUT_FOLDER = SLBFileManager.generate_dirname(BELONG_TRADING_DATE)

    # 读取扫雷宝基础目录配置
    SLB_BASE_DIR = Path(_CFG['slb']['base_dir'])
    output_dir = SLB_BASE_DIR / DEFAULT_OUTPUT_FOLDER

    _CSL.print(f"⚠️ 准备删除目录中的所有json文件: {output_dir}")

    # 获取所有json文件
    _, existed_json_files = walk(output_dir, include_extensions=".json", without_root_path=False)

    if not existed_json_files:
        _CSL.print("✅ 目录中没有json文件")
        return

    _CSL.print(f"📄 找到 {len(existed_json_files)} 个json文件")

    from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import enumerate_with_progress

    for _, ejf in enumerate_with_progress(existed_json_files, task_name="删除扫雷宝文件"):
        os.remove(ejf)
        if verbose:
            _CSL.print(f"🗑️ 删除: {os.path.basename(ejf)}")

    _CSL.print(f"✅ 已删除 {len(existed_json_files)} 个json文件")

# --------------------------------------------------------------------------------
# 查询扫雷宝数据命令
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.option('--save/--no-save', '-sv/-ns', 'save', is_flag=True, default=False, help="保存成文件")
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.pass_context
def query_online(_ctx: click.Context,
          stocks: List[str],
          save: bool,
          verbose: bool):
    """在线查询单个或多个股票的扫雷宝数据"""

    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    # 设置时间变量
    NOW_DT = datetime.now()
    BELONG_TRADING_DATE = calc_belong_trading_day(NOW_DT, datetime_time(hour=15))
    DEFAULT_OUTPUT_FOLDER = SLBFileManager.generate_dirname(BELONG_TRADING_DATE)

    # 读取扫雷宝基础目录配置
    SLB_BASE_DIR = Path(_CFG['slb']['base_dir'])
    output_dir = SLB_BASE_DIR / DEFAULT_OUTPUT_FOLDER

    # 处理文件夹
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)
        _CSL.print(f"✅ 创建输出目录: {output_dir}")

    for stock in stocks:
        _CSL.print(f"\n🔍 查询股票: {stock}")

        try:
            result = fetch_tdx_json(stock)
        except Exception as e:
            E(f"通达信扫雷宝接口出错: {e}", stock=stock)
            continue

        if result:
            total_fs = SLBDetail._calculate_total_score(result)
            stock_name = result.get('name', '(未知股票)')
            risk_count = result.get('num', 0)

            _CSL.print(f"📊 股票名称: {stock_name}")
            _CSL.print(f"📈 风险总分: {total_fs}")
            _CSL.print(f"📉 风险项数量: {risk_count}")
            _CSL.print(f"🏆 扫雷宝评分: {100 - total_fs}")

            # 显示风险分类
            if verbose and 'data' in result:
                _CSL.print("\n📋 风险分类:")
                for category in result['data']:
                    category_name = category.get('name', '未知分类')
                    category_risk_count = len([item for item in category.get('rows', []) if item.get('trig') == 1])
                    _CSL.print(f"   {category_name}: {category_risk_count} 项")

            if save:
                json_filename = f'SLB.{SecurityCode(stock).full_code}.json'
                json_filepath = os.path.join(output_dir, json_filename)
                json_str = json.dumps(result, indent=2, ensure_ascii=False)

                with open(json_filepath, 'w', encoding='utf-8') as F:
                    F.write(json_str)
                _CSL.print(f"💾 保存到文件: {json_filename}")
        else:
            _CSL.print(f"❌ 无法获取股票JSON数据: {stock}")

# --------------------------------------------------------------------------------
# 数据库查询命令
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--db-type', '-db', default='pg', show_default=True,
              type=click.Choice(['pg', 'postgresql', 'sqlite'], case_sensitive=False),
              help="数据库类型")
@click.option('--date', '-d', 'date', type=DATETIME, default=None, help="查询时间点（历史回放）")
# 1. 增加 stocks 参数，支持多个股票查询（平替 slb_detail.py )
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, help='股票代码列表 (如: 688318.SH)')
@click.option('--market', '-m', 'markets', multiple=True, callback=split_comma_upper,
              type=click.Choice([*ALL_MARKET_LIST, 'ALL'], case_sensitive=False), default=['ALL'], help='市场代码（ALL：所有市场）')
@click.option('--all', '-a', 'all_flag', is_flag=True, help="查询全部历史记录（与 -m 并用）")
@click.option('--latest', 'latest_flag', is_flag=True, help="查询最新记录（与 -m 并用）")
@click.option('--list-markets', is_flag=True, help="列出所有市场代码")
@click.option('--slb-range', 'slb_score_range', type=str, help="扫雷宝评分区间，格式：x,y（x<=score<=y）")
@click.option('--risk-range', 'risk_score_range', type=str, help="风险总分区间，格式：x,y")
@click.option('--score-min', 'score_min', type=int, default=0, help='最小风险分数')
@click.option('--score-max', 'score_max', type=int, default=100, help='最大风险分数')
# 属于 BUG FIX
@click.option('--fill-market-code', is_flag=True, help="对数据库中缺失的市场代码进行补充")
@click.option('--limit', '-l', 'limit', type=int, default=20, help='显示数量限制')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.option('--max-to-show', '-max', 'max_to_show', type=int, default=20, help='一次性最大显示数量')
@click.pass_context
def query_db(_ctx: click.Context,
             db_type: str,
             date: Optional[datetime],
             stocks: list[str],
             markets: list[str],
             all_flag: bool,
             latest_flag: bool,
             list_markets: bool,
             slb_score_range: Optional[str],
             risk_score_range: Optional[str],
             score_min: int,
             score_max: int,
             fill_market_code: bool,
             limit: int,
             verbose: bool):
    """从数据库查询扫雷宝数据"""

    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    if date is None:
        when = datetime.now()
    else:
        when = date

    markets = ALL_MARKET_LIST if 'ALL' in markets else []
    
    # 初始化数据库
    if not init_database(db_type, _CFG, verbose):
        return
    
    if stocks:
        for stock_code in stocks:
            code = SecurityCode(stock_code)
            _CSL.print(f"\n🔍 深度分析个股: [bold cyan]{code.full_code}[/bold cyan]")
            
            # 获取该股票所有历史记录（按时间倒序）
            records = SLBDetail.get_all_by_code(code)
            if not records:
                _CSL.print("⚠️ 数据库中无该股票记录")
                continue
                
            # 展示最新记录
            latest = records[0]
            _CSL.print(f"   最新记录: {latest.created_at} | 评分: {100 - latest.total_risk_score}")
            
            # 如果开启 verbose，自动进行逐条差异对比
            if verbose and len(records) > 1:
                for i in range(1, len(records)):
                    _CSL.print(f"   🔄 对比 {records[i].created_at} vs {records[i-1].created_at}:")
                    SLBDetail.show_differences(
                        records[i].to_dict(exclude_keys=['risk_data']),
                        records[i-1].to_dict(exclude_keys=['risk_data'])
                    )
        return

    # ---------- 补充市场代码 ----------
    if fill_market_code:
        details = SLBDetail.get_all() # type: List[SLBDetail]
        updated_count = 0
        for _, detail in enumerate_with_progress(details, task_name="补充市场代码"):
            if detail is None or detail.ExchangeID is None or len(detail.ExchangeID) > 2:
                market_code = SecurityCode.guest_market(detail.InstrumentID)
                detail.ExchangeID = market_code
                updated_count += 1

        _CSL.print(f"✅ 成功更新 {updated_count} 条记录的ExchangeID")
        return

    # ---------- 列出市场代码 ----------
    if list_markets:
        _markets = SLBDetail.get_markets_list(when)
        _CSL.print(f"📊 市场列表 ({when.strftime('%Y-%m-%d')}): {_markets}")
        return

    # ---------- 按市场查询 ----------
    if markets:

        records = []
        if all_flag:
            for _m in markets:
                records.extend(SLBDetail.get_all_by_market(_m, when))
        elif latest_flag:
            for _m in markets:
                records.extend(SLBDetail.get_all_latest_by_market(_m, when))
        else:
            for _m in markets:
                records.extend(SLBDetail.get_all_latest_by_market(_m, when))
        _CSL.print(f"📊 市场 {markets} 找到 {len(records)} 条记录")
        if verbose:
            for i, r in enumerate(records):
                _CSL.print(f"  {i}. {r.ExchangeID}.{r.InstrumentID} {r.name} 风险:{r.total_risk_score}")
        return

    # ---------- 按分数区间查询 ----------
    lower, upper = -1, -1
    if slb_score_range:
        upper, lower = str_to_range(slb_score_range)
        upper = 100 - upper
        lower = 100 - lower
    elif risk_score_range:
        lower, upper = str_to_range(risk_score_range)
    else:
        lower, upper = score_min, score_max

    if lower >= 0 and upper >= 0:
        records = SLBDetail.get_latest_with_score_range((lower, upper), when)
        if records:
            _CSL.print(f"📊 风险分 [{lower},{upper}) 区间：共 {len(records)} 只个股")
            display = records[:limit] if limit > 0 else records
            for i, r in enumerate(display):
                _CSL.print(f"  {i}. {r.ExchangeID}.{r.InstrumentID} {r.name} 风险:{r.total_risk_score} 评分:{100-r.total_risk_score}")
            if len(records) > len(display):
                _CSL.print(f"  ... 还有 {len(records)-len(display)} 条")
        else:
            _CSL.print("❌ 没有找到符合条件的记录")
        return

    # ---------- 查询全市场最新 ----------
    if all_flag or latest_flag:
        records = SLBDetail.get_latest(when)
        _CSL.print(f"📊 共找到 {len(records)} 只个股 (when={when.strftime('%Y-%m-%d')})")
        if verbose:
            for i, r in enumerate(records[:limit] if limit > 0 else records):
                _CSL.print(f"  {i}. {r.ExchangeID}.{r.InstrumentID} {r.name} 风险:{r.total_risk_score}")
        return

    _CSL.print("❌ 请指定查询条件（--market, --slb-range, --risk-range, --all 等）")

# --------------------------------------------------------------------------------
# --------------------------------------------------------------------------------
# 数据库迁移命令（slb_detail.py 的 --sqlite-to-pg / --pg-to-sqlite）
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--sqlite-to-pg', '-s2p', is_flag=True, help="从SQLite迁移到PostgreSQL")
@click.option('--pg-to-sqlite', '-p2s', is_flag=True, help="从PostgreSQL迁移到SQLite")
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.pass_context
def migrate_db(_ctx: click.Context,
               sqlite_to_pg: bool,
               pg_to_sqlite: bool,
               verbose: bool):
    """迁移扫雷宝数据（SQLite <-> PostgreSQL）"""
    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    if not sqlite_to_pg and not pg_to_sqlite:
        _CSL.print("请指定迁移方向：--sqlite-to-pg 或 --pg-to-sqlite")
        return

    sqlite_cfg = _CFG.get('sqlite', {})
    pg_cfg = _CFG.get('postgresql', {})

    if not sqlite_cfg or not pg_cfg:
        _CSL.print("❌ 配置文件必须同时包含 sqlite 和 postgresql 的连接配置")
        return

    from sqlalchemy import create_engine
    from slb_migration import sync_data_with_raw_sql

    try:
        if sqlite_to_pg:
            _CSL.print("--- 从 SQLite 迁移到 PostgreSQL ---")
            pg_url = generate_engine_url_str(**pg_cfg)
            sqlite_url = generate_engine_url_str(**sqlite_cfg)
            SLBDetail.init_db(pg_url)
            sync_data_with_raw_sql(create_engine(sqlite_url), SLBDetail)
            _CSL.print("✅ 迁移完成")
        elif pg_to_sqlite:
            _CSL.print("--- 从 PostgreSQL 迁移到 SQLite ---")
            pg_url = generate_engine_url_str(**pg_cfg)
            sqlite_url = generate_engine_url_str(**sqlite_cfg)
            SLBDetail.init_db(sqlite_url)
            sync_data_with_raw_sql(create_engine(pg_url), SLBDetail)
            _CSL.print("✅ 迁移完成")
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)

# --------------------------------------------------------------------------------
# 风险分析图命令（slb_detail.py 的 --risk-plot）
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--db-type', '-db', default='pg', show_default=True,
              type=click.Choice(['pg', 'postgresql', 'sqlite'], case_sensitive=False),
              help="数据库类型")
@click.option('--save', '-s', 'save_path', type=str, default=None, help="保存图片路径")
@click.option('--high-risk', is_flag=True, help="仅分析高风险（分数30以上）")
@click.option('--detailed', is_flag=True, help="生成详细分析报告")
@click.pass_context
def plot_risk(_ctx: click.Context,
              db_type: str,
              save_path: Optional[str],
              high_risk: bool,
              detailed: bool):
    """生成扫雷宝风险分析图"""

    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    if not init_database(db_type, _CFG):
        return

    if detailed:
        SLBDetail.plot_detailed_score_analysis(save_path=save_path or 'detailed_analysis.png')
        _CSL.print(f"✅ 详细分析报告已保存: {save_path or 'detailed_analysis.png'}")
    elif high_risk:
        SLBDetail.plot_score_distribution((30, 100), save_path=save_path or 'high_risk_stocks.png')
        _CSL.print(f"✅ 高风险股票分布图已保存: {save_path or 'high_risk_stocks.png'}")
    else:
        SLBDetail.plot_score_distribution(save_path=save_path or 'risk_score_distribution.png')
        _CSL.print(f"✅ 风险分数分布图已保存: {save_path or 'risk_score_distribution.png'}")

# --------------------------------------------------------------------------------
# 统计更新数量命令（slb_detail.py 的 --count）
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--db-type', '-db', default='pg', show_default=True,
              type=click.Choice(['pg', 'postgresql', 'sqlite'], case_sensitive=False),
              help="数据库类型")
@click.option('--date', '-d', 'date', type=DATETIME, default=None, help="统计日期")
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式（显示变更明细）')
@click.pass_context
def count_updates(_ctx: click.Context,
                  db_type: str,
                  date: Optional[datetime],
                  verbose: bool):
    """统计指定日期后的扫雷宝更新数量"""

    _CSL = _ctx.obj['console']  # type: Console
    _CFG = _ctx.obj['cfg']  # type: dict

    if date is None:
        date = datetime.now()

    if not init_database(db_type, _CFG, verbose):
        return

    belong_trading_date = calc_belong_trading_day(date, datetime_time(hour=15))
    交易日收盘时间 = datetime.combine(belong_trading_date, datetime_time(hour=15))

    records = SLBDetail.get_all_created_later(交易日收盘时间)

    _CSL.print(f"📊 统计 {belong_trading_date.strftime('%Y-%m-%d')} 收盘后更新记录：")

    if records:
        _CSL.print(f"✅ 收盘后更新: {len(records)} 条")
        if verbose:
            from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import enumerate_with_progress
            for i, record in enumerate_with_progress(records, task_name="分析变更"):
                old_record = SLBDetail.get_latest_by_code(
                    SecurityCode(record.InstrumentID, record.ExchangeID),
                    when=(record.created_at - timedelta(minutes=1)))
                if old_record:
                    _CSL.print(f"\n  {i}. {record.ExchangeID}.{record.InstrumentID} {record.name}:")
                    SLBDetail.show_differences(
                        old_record.to_dict(exclude_keys=['risk_data']),
                        record.to_dict(exclude_keys=['risk_data']))
    else:
        _CSL.print("📭 暂无更新记录")


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--market', '-m', 'markets', multiple=True, callback=split_comma_upper,
              type=click.Choice([*ALL_MARKET_LIST, 'ALL'], case_sensitive=False), default=['ALL'], help='市场代码（ALL：所有市场）')
@click.option('-db', '--db-type', default='pg', type=click.Choice(ALL_DB_LIST), help="数据库类型")
@click.option('-t', '--test', is_flag=True, help="测试模式")
@click.pass_context
def archive(_ctx: click.Context,
            markets: List[str],
            db_type: str,
            test: bool):
    """每日归档：自动下载、入库并生成自定义序列文件
    归档流程的核心逻辑：下载 -> 入库 -> 生成序列"""

    _CSL = _ctx.obj['console'] # type: Console

    markets = ALL_MARKET_LIST if 'ALL' in markets else []

    _CSL.print(f"[bold cyan]开始执行全网归档任务...[/bold cyan]")

    # 1. 下载（调用现有 download 逻辑完成）
    _CSL.print("[yellow]开始下载扫雷宝详情文件...[/yellow]")
    _ctx.invoke(download, markets=markets, save=True, verbose=False, quick=True)

    # 2. 入库（调用现有 import_to_db 逻辑完成）
    _CSL.print("[yellow]对最新下载的文件进行入库...[/yellow]")
    _ctx.invoke(import_to_db, db_type=db_type, date=None, test=test, verbose=False, debug=False)

    # 3. 生成序列文件
    _CSL.print("[yellow]正在生成自定义序列文件...[/yellow]")
    _ctx.invoke(generate_diy_files, db_type=db_type, date=None, verbose=False)

    _CSL.print("[bold green]归档任务完成！[/bold green]")

