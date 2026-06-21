#!python

import os
import click
from click_shell import shell
from auto_click_auto import enable_click_shell_completion
from auto_click_auto.constants import ShellType

from difoss_stock_util.color_log_util import I

# 历史文件路径
HISTORY_FILE = os.path.expanduser("~/.mycli.history")

# ---------- 交互式 Shell 定义 ----------
@shell(
    prompt='mycli> ',
    intro='🎯 MyCLI 交互模式 | 按上箭头查看历史 | 输入 exit 退出',
    hist_file=HISTORY_FILE   # ✅ 自动保存命令历史
)
def cli():
    """交互式 Shell 主入口"""
    pass

@cli.command()
def history_file():
    """显示历史文件路径"""
    click.echo(f"历史文件路径: {HISTORY_FILE}")

# ---------- 子命令定义 ----------
@cli.command()
def hello():
    """打个招呼"""
    click.echo('Hello, World!')

@cli.command()
@click.argument('name')
def greet(name):
    """跟某人打招呼"""
    click.echo(f'Hello {name}!')

@cli.command()
def history():
    """查看本次会话的命令历史"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            lines = f.readlines()
            click.echo(''.join(lines[-20:]))  # 显示最近20条
    else:
        click.echo('暂无历史记录')

# ---------- 程序入口 ----------
if __name__ == '__main__':
    # ✅ 为命令行工具本身添加 Tab 补全
    enable_click_shell_completion(
        program_name="mycli",
        shells={ShellType.BASH, ShellType.ZSH, ShellType.FISH}
    )
    cli()