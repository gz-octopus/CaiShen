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
def security_code(_ctx: click.Context,
    stocks: list[str]
):
    """证券代码（SecurityCode）功能测试"""
    CONSOLE = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            _s_vec = full_code.split('.')
            if len(_s_vec) != 2:
                E(f"证券代码 {full_code} 不是股票")
                continue
            _s_code = _s_vec[0]
            _market = _s_vec[1]
            code = SecurityCode(code=_s_code, market=_market)
            print(f"code={code}, sc={code.security_type}")
            # CONSOLE.print(f"{full_code} :", )
            I(code=code, short_code=code.short_code, market=code.market_code, security_type=code.security_type)
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
        click.echo("✅ 初始化成功")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ======================
# main（根据参数决定模式）
if __name__ == '__main__':
    repl_cli_main(on_init=init, console=CONSOLE)
