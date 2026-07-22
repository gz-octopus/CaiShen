# -*- coding: utf-8 -*-
"""Sync tool: 全市场日 K 同步 — 策略 A（包 tdxdata_cmd.sync_history）"""

from io import StringIO

from rich.console import Console

from caishen_mcp.server import mcp, get_server_state, require_tq
from caishen_mcp.ctx_helper import log_tool_call, safe_result, create_click_context


@mcp.tool()
def sync_history(
    start_date: str = "20150101",
    end_date: str | None = None,
    include_delisted: bool = True,
) -> str:
    """全市场日 K 线数据同步到本地 PostgreSQL history_data_1d 表。

    注意：此操作可能耗时较长（数分钟到数十分钟），取决于数据量。

    Args:
        start_date: 起始日期，格式 YYYYMMDD，默认 20150101。
        end_date: 截止日期，格式 YYYYMMDD，默认今天。
        include_delisted: 是否包含已退市股票，默认 True。
    """
    try:
        require_tq()
        log_tool_call()
        cfg, db_url, _ = get_server_state()

        from tdxdata_cmd import sync_history as _sync_history

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        ctx = create_click_context(cfg, db_url, console)

        with ctx:
            _sync_history.callback(
                start_date=start_date,
            end_date=end_date,
            include_delisted=include_delisted,
        )

        output_text = string_io.getvalue()
        return safe_result(
            "ok",
            summary=f"日 K 同步完成（{start_date} ~ {end_date or '今天'}）",
            detail=output_text[:2000],
        )
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"同步失败: {e}", detail=str(e))
