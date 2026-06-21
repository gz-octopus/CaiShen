#!python
# -*- coding: utf-8 -*-

from difoss_stock_util.click_util import repl_cli_main, command_with_abbrev
import click


@command_with_abbrev(abbrev='h1')
@click.argument('name', default='World')
def hello(name):
    """问候命令"""
    print(f"Hello, {name}!")


@command_with_abbrev(abbrev='w')
def world():
    """世界命令"""
    print("Welcome to the world!")


@command_with_abbrev(abbrev=None)  # 使用默认缩写
@click.option('-c', '--count', type=int, default=3)
def greet(count):
    """多次问候"""
    for i in range(count):
        print(f"Greeting #{i+1}")


if __name__ == '__main__':
    repl_cli_main(
        doc='测试改良后的历史命令功能（不依赖 readline）',
        prompt='test> ',
        find_caller_cmds=True  # 自动查找当前模块中的 click 命令
    )