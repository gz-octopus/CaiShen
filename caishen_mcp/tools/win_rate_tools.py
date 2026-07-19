# -*- coding: utf-8 -*-
"""Win Rate tool: 胜率分析报告 — 策略 A（包 win_rate_cmd.report_cmd）"""

from io import StringIO
from datetime import datetime, timedelta

from rich.console import Console

from caishen_mcp.server import mcp, get_server_state, require_tq
from caishen_mcp.ctx_helper import safe_result, create_click_context


@mcp.tool()
def win_rate_report(
    stocks: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    source_type: str = "tdx",
) -> str:
    """胜率分析报告 — 分析指定股票在历史区间内的胜率表现。

    Args:
        stocks: 股票代码列表。
        start_date: 起始日期 YYYY-MM-DD。默认 3 年前。
        end_date: 截止日期 YYYY-MM-DD。默认今天。
        source_type: 数据源。tdx=通达信, mootdx, mt5。
    """
    try:
        require_tq()
        cfg, db_url, _ = get_server_state()

        from win_rate_cmd import report_cmd as _report

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        ctx = create_click_context(cfg, db_url, console)

        _report(
            ctx=ctx,
            stocks=list(stocks) if stocks else [],
            start_date=datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime.now() - timedelta(days=3*365),
            end_date=datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now(),
            source_type=source_type,
        )

        output_text = string_io.getvalue()
        return safe_result(
            "ok",
            summary=f"胜率分析完成，{len(stocks)} 只股票",
            detail=output_text[:2000],
        )
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"胜率分析失败: {e}", detail=str(e))
