#!python
# encoding: utf-8

import click
import click_shell
from rich import print as pprint
from rich.console import Console

from difoss_stock_util import *
from difoss_stock_util.color_log_util import *
from difoss_stock_util.util import read_yaml_config, print_locals
from difoss_stock_util.click_util import *

# --------------------------------------------------------------------------------
# 全局变量
CONSOLE = Console()
CFG = None
CONFIG_PATH = 'config.yaml'  # 默认配置文件路径

# --------------------------------------------------------------------------------
# 辅助工具


# --------------------------------------------------------------------------------
# 子命令

# ======================
# 例子
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.pass_context
def _example(_ctx: click.Context,
    stocks: list[str]
):
    """"""
    global CONSOLE
    try:
        for full_code in stocks:
            # TODO:
            CONSOLE.print(f"{full_code} :", )
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
    
    print_locals()

    try:
        # xtdata.enable_hello = False
        # tq.initialize(__file__)
        click.echo("✅ 初始化成功")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ======================
# main（根据参数决定模式）
if __name__ == '__main__':
    repl_cli_main(on_init=init, console=CONSOLE)
