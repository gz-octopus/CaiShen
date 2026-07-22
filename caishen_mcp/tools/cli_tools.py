# -*- coding: utf-8 -*-
"""透传工具：直接执行 CLI 命令，无需参数翻译。"""

import shlex
from io import StringIO

from click.testing import CliRunner
from rich.console import Console

from caishen_mcp.server import mcp, get_server_state, require_tq
from caishen_mcp.ctx_helper import log_tool_call, safe_result


# 支持的命令名 → click command 函数映射
def _cmd_map():
    from tdxdata_cmd import formula, formula_multi
    return {
        'f': formula,
        'formula': formula,
        'fm': formula_multi,
        'formula_multi': formula_multi,
    }


@mcp.tool()
def caishen_run(command: str) -> str:
    """透传执行 CLI 命令，直接粘贴原生命令字符串，无需翻译参数。

    支持的快捷命令:
        fm    — formula_multi（批量公式/选股）
        f     — formula（单/多股票公式计算）
        fl    — formula_list（列出公式）

    示例:
        "fm -t xg --name 吸完·首倍阳 -a 5 --with-name -c 250 -rc 1 -sus"
        "f -t zb --name MACD -s 603337.SH -a 12,26,9 -v"
        "fl -t xg"

    Args:
        command: 完整 CLI 命令字符串，以命令名开头
    """
    try:
        require_tq()
        log_tool_call()
        cfg, db_url, _ = get_server_state()

        parts = shlex.split(command)
        if not parts:
            return safe_result("error", message="命令为空")

        cmd_name = parts[0]
        cmd_args = parts[1:]

        cmd_map = _cmd_map()
        if cmd_name not in cmd_map:
            return safe_result("error",
                message=f"不支持的命令: {cmd_name}",
                detail=f"支持: {list(cmd_map.keys())}")

        click_cmd = cmd_map[cmd_name]
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)

        # 用 CliRunner 执行，注入 caishen 的全局状态
        runner = CliRunner()
        result = runner.invoke(
            click_cmd, cmd_args,
            obj={
                'config_path': 'config.yaml',
                'console': console,
                'cfg': cfg,
                'db_url': db_url,
            },
            catch_exceptions=False,
        )

        output = result.output or ""
        if result.exit_code != 0:
            return safe_result(
                "error",
                summary=f"命令失败 (exit={result.exit_code})",
                detail=output[:3000],
                exit_code=result.exit_code,
            )

        return safe_result(
            "ok",
            summary="命令执行成功",
            detail=output[:3000],
            exit_code=result.exit_code,
        )
    except Exception as e:
        return safe_result("error", message=f"命令执行异常: {e}", detail=str(e))
