#!python
# encoding: utf-8
# author: DifossChen


import click
from rich.pretty import Pretty
from rich.console import Console

from difoss_stock_util import *
from difoss_stock_util.color_log_util import *

from cache_cmd import cache_stock_name, get_stock_name, STOCKS
from cache_cmd import memory_cache  # 引入 mc 命令

# --------------------------------------------------------------------------------
# 全局变量
CONSOLE = Console()
CFG = None
CONFIG_PATH = 'config.yaml'  # 默认配置文件路径


# --------------------------------------------------------------------------------
# 辅助工具



# --------------------------------------------------------------------------------
# 子命令

@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--source-type', '-t', 'source_type', type=click.Choice(['tdx', 'mootdx', 'mt5'], case_sensitive=False), required=True, help='数据来源类型')
@click.pass_context
def data_source_options(_ctx: click.Context,
    source_type: str,
):
    """"""
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        if source_type == 'tdx':
            CONSOLE.print("数据来源: 通达信")
        elif source_type == 'mootdx':
            CONSOLE.print("数据来源: mootdx")
        elif source_type == 'mt5':
            CONSOLE.print("数据来源: MetaTrader 5")
        else:
            CONSOLE.print(f"未知的数据来源类型: {source_type}")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)

# --------------------------------------------------------------------------------
# 常规函数
# ======================
# 初始化
def init(_ctx: click.Context):
    global CFG, CONSOLE, CONFIG_PATH
    _ctx.ensure_object(dict)
    _ctx.obj['config_path'] = CONFIG_PATH
    _ctx.obj['console'] = CONSOLE
    if not CFG:
        CFG = read_yaml_config(CONFIG_PATH)

    _ctx.obj['cfg'] = CFG

    try:
        # xtdata.enable_hello = False
        # tq.initialize(__file__)
        CONSOLE.print("✅ 初始化成功")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ======================
# main（根据参数决定模式）
if __name__ == '__main__':
    repl_cli_main(on_init=init, cmd_filenames=['win_rate_cmd'], console=CONSOLE)
