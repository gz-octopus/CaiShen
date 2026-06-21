#!python
import click
from click_repl import ClickCompleter
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import ThreadedCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
import click
from click_repl import ClickCompleter
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import ThreadedCompleter
from prompt_toolkit.history import *
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
import shlex

@click.group()
@click.pass_context
def cli(ctx: click.Context):
    pass

@cli.command()
def start():
    click.echo("Service started.")

@cli.command()
def status():
    click.echo("Everything is fine.")

def run_repl():
    # --- 修复部分开始 ---
    # 1. 手动创建一个 Click 上下文对象
    ctx = click.Context(cli)

    # 2. 传入 cli (group) 和 ctx (context)
    completer = ClickCompleter(cli, ctx)
    # --- 修复部分结束 ---

    session = PromptSession(
        history=FileHistory(),
        completer=ThreadedCompleter(completer),
        auto_suggest=AutoSuggestFromHistory(),
        complete_while_typing=True
    )

    click.echo("--- 交互式终端 (输入字母自动补全) ---")
    click.echo("输入 'exit' 或 'quit' 退出")

    while True:
        try:
            text = session.prompt('my-tool > ')
            if not text.strip():
                continue
            if text.lower() in ('exit', 'quit'):
                break

            args = shlex.split(text)
            # 使用 standalone_mode=False 防止执行完命令后脚本直接退出
            cli.main(args=args, standalone_mode=False)

        except (EOFError, KeyboardInterrupt):
            break
        except click.ClickException as e:
            e.show() # 显示 Click 特有的错误（如命令拼错）
        except Exception as e:
            click.echo(f"Error: {e}")

if __name__ == "__main__":
    run_repl()
