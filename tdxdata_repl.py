#!python
# -*- coding: utf-8 -*-
"""通达信量化数据 CLI 工具 - 使用 click_shell 实现交互模式（REPL）"""

# ===== 临时修复 click-shell 与 click>=8.1 的兼容性问题 =====
import click.core

_original_parameter_init = click.core.Parameter.__init__

def _patched_parameter_init(self, *args, **kwargs):
    kwargs.pop('callable', None)  # 移除 click-shell 错误传入的参数
    return _original_parameter_init(self, *args, **kwargs)

click.core.Parameter.__init__ = _patched_parameter_init
# ===========================================================

import click
import click_shell
from rich import print as pprint
from rich.console import Console
from tdx_quant.tqcenter import tq
from collections import defaultdict

from difoss_stock_util.click_util import *
from difoss_stock_util.util import read_yaml_config, print_locals
from difoss_stock_util.db_util import *
from difoss_stock_util.metric_data.history_data_1d import *

from cache_cmd import cache_stock_name, cache_st_stock_name
from typing import Dict

# DEBUG:
# from difoss_stock_util.util import trace_func, trace_function

# --------------------------------------------------------------------------------
# Global Variables
CONSOLE = Console()
CFG = None
CONFIG_PATH = 'config.yaml'  # 默认配置文件路径

def cache_stock_name_of_market(market='所有A股'):
    """把 market 指定的个股 code -> name 缓存到 cache_cmd 中"""
    # 获取A股 Code -> Name
    code2name = {}
    st_code2name = {}
    stocks_info = tq.get_stock_list(market='所有A股', list_type=1)
    for stock_info in stocks_info:
        if isinstance(stock_info, dict):
            code = stock_info.get('Code') # type: str | None
            name = stock_info.get('Name') # type: str | None
            if code and name:
                code2name.update({code: name})
                if 'ST' in name.upper() or name.startswith('退'):
                    st_code2name.update({code: name})

    cache_st_stock_name(st_code2name) # 缓存ST
    cache_stock_name(code2name) # 存于缓存
    click.echo(f"✅ 缓存 A股（{len(code2name)}只）股票代码和名称")


# 初始化
def init(_ctx: click.Context):
    
    global CONSOLE, CFG, CONFIG_PATH
    _ctx.ensure_object(defaultdict)
    _ctx.obj['config_path'] = CONFIG_PATH
    _ctx.obj['console'] = CONSOLE
    if not CFG:
        CFG = read_yaml_config(CONFIG_PATH)
    _ctx.obj['cfg'] = CFG

    try:
        # PostgreSQL连接字符串
        pg_cfg = CFG.get('postgresql', {})
        if not pg_cfg:
            raise ValueError("PostgreSQL 配置缺失或不完整，请检查配置文件")
        _ctx.obj['db_url'] = generate_engine_url_str(**pg_cfg)

        # 初始化 tq 连接
        tq.initialize(__file__)
        click.echo("✅ TQ 初始化成功")
        cache_stock_name_of_market()

    except Exception as e:
        click.echo(f"⚠️ TQ 初始化失败: {e}", err=True)
        exit(-1)


if __name__ == '__main__':
    repl_cli_main(doc='通达信量化工具', prompt='tdx> ', on_init=init, cmd_filenames=['tdxdata_cmd'], console=CONSOLE)
