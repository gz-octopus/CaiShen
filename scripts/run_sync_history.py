"""sync-history 命令行入口 — 不通过 REPL，直接调用。

"""

import os
import sys
_CWD = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_CWD)
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

from rich.console import Console
from difoss_stock_util.util import read_yaml_config


def main():
    from tdxdata_cmd import sync_history

    # 构造 Click context（模拟 REPL 的 init）
    cfg = read_yaml_config("config.yaml")
    console = Console()

    os.chdir(_PROJ)  # 切换到项目根目录

    # 直接调用命令函数（绕过 Click 装饰器开销）
    # sync_history 的 Click 参数有默认值，手动传入
    import click
    ctx = click.Context(
        click.Command(name="sync-history"),
        obj={"cfg": cfg, "console": console},
    )

    # 用默认参数调用：从 20150101 开始，resume=True, include_delisted=True
    sync_history.callback(
        ctx,
        start_date="20150101",
        end_date=None,
        resume=True,
        include_delisted=True,
    )


if __name__ == "__main__":
    main()
