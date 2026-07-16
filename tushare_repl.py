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

import tushare as ts
from tushare.pro.client import DataApi

# --------------------------------------------------------------------------------
# 全局变量
CONSOLE = Console()
CFG = None
CONFIG_PATH = 'config.yaml'  # 默认配置文件路径

# --------------------------------------------------------------------------------
# 辅助工具


# --------------------------------------------------------------------------------
# 子命令

@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.option('-l', '--limit', type=int, default=-1, help='限制处理股票的数量')
@click.pass_context
def stock_basic(
    _ctx: click.Context,
    limit: int,
):
    _CSL = _ctx.obj['console'] # type: Console
    _ts_pro_api = _ctx.obj['ts_pro_api']  # type: DataApi

    # 拉取数据
    df = _ts_pro_api.stock_basic(market = 'SZ',
        fields=[
            "ts_code",
            "symbol",
            "name",
            "area",
            "industry",
            "cnspell",
            "market",
            "list_date",
            "act_name",
            "act_ent_type"
    ])

    print_dataframe(df)


# ======================
# 例子
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks, required=True, help='股票代码列表 (如: 688318.SH)')
@click.pass_context
def _example(_ctx: click.Context,
    stocks: list[str]
):
    """"""
    _CSL = _ctx.obj['console'] # type: Console
    try:
        for full_code in stocks:
            # TODO:
            _CSL.print(f"{full_code} :", )
    except Exception as e:
        _CSL.print_exception(extra_lines=5, show_locals=True)


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
        # 初始化pro接口
        ts_pro_api = ts.pro_api(CFG['tushare']['token'])
        _ctx.obj['ts_pro_api'] = ts_pro_api
        
        click.echo("✅ 初始化成功")
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


# ======================
# main（根据参数决定模式）
if __name__ == '__main__':
    repl_cli_main(doc='tushare工具', prompt='ts> ', on_init=init, console=CONSOLE)

