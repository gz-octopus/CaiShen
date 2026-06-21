#!python
# encoding: utf-8
# author: DifossChen
#
"""扫雷宝数据 CLI 工具 - 使用 click_shell 实现交互模式（REPL）"""

import click
import click_shell
from rich import print as pprint
from rich.console import Console
from datetime import datetime, time as datetime_time
from pathlib import Path
import os
import json
import requests
from typing import List, Dict, Optional
from collections import defaultdict

from difoss_stock_util import *
from difoss_stock_util.color_log_util import *
from difoss_stock_util.click_util import *
from difoss_stock_util.util import read_yaml_config, print_locals
from difoss_stock_util.db_util import *
from difoss_stock_util.metric_data import SLBDetail
from difoss_stock_util.slb_file_mgr import SLBFileManager
from difoss_stock_util.security_util import SecurityCode

# ===== 临时修复 click-shell 与 click>=8.1 的兼容性问题 =====
import click.core

_original_parameter_init = click.core.Parameter.__init__

def _patched_parameter_init(self, *args, **kwargs):
    kwargs.pop('callable', None)  # 移除 click-shell 错误传入的参数
    return _original_parameter_init(self, *args, **kwargs)

click.core.Parameter.__init__ = _patched_parameter_init
# ===========================================================

# --------------------------------------------------------------------------------
# Global Variables
CONSOLE = Console()
CFG = None
CONFIG_PATH = 'config.yaml'  # 默认配置文件路径

# 扫雷宝相关常量
ALL_MARKET_LIST = ['SH', 'SZ']  # 扫雷宝只目前包含沪深两市
ALL_DB_LIST = ['pg', 'postgresql', 'sqlite']

# 全局时间变量
NOW_DT = datetime.now()
BELONG_TRADING_DATE = calc_belong_trading_day(NOW_DT, datetime_time(hour=15))
DEFAULT_OUTPUT_FOLDER = SLBFileManager.generate_dirname(BELONG_TRADING_DATE)

# --------------------------------------------------------------------------------
# 扫雷宝数据获取函数
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

# --------------------------------------------------------------------------------
# 初始化函数
def init(_ctx: click.Context):
    global CONSOLE, CFG
    
    _ctx.ensure_object(dict)
    _ctx.obj['config_path'] = CONFIG_PATH
    _ctx.obj['console'] = CONSOLE
    
    if not CFG:
        CFG = read_yaml_config(CONFIG_PATH)
    _ctx.obj['cfg'] = CFG

    try:
        # 读取扫雷宝基础目录配置
        SLB_BASE_DIR = Path(CFG['slb']['base_dir'])
        output_dir = SLB_BASE_DIR / DEFAULT_OUTPUT_FOLDER
        _ctx.obj['slb_base_dir'] = SLB_BASE_DIR
        _ctx.obj['output_dir'] = output_dir
        
        # 处理文件夹
        if not os.path.isdir(output_dir):
            os.mkdir(output_dir)
            CONSOLE.print(f"✅ 创建输出目录: {output_dir}")
        
        CONSOLE.print(f"✅ 扫雷宝工具初始化成功")
        CONSOLE.print(f"   基础目录: {SLB_BASE_DIR}")
        CONSOLE.print(f"   输出目录: {output_dir}")
        CONSOLE.print(f"   交易日: {BELONG_TRADING_DATE.strftime('%Y-%m-%d')}")
        
    except Exception as e:
        CONSOLE.print(f"⚠️ 扫雷宝初始化失败: {e}", err=True)
        raise

# ======================
# main（根据参数决定模式）
# ======================

if __name__ == '__main__':
    repl_cli_main(doc='扫雷宝数据工具', prompt='slb> ', on_init=init, cmd_filenames=['slb_cmd'], console=CONSOLE)