# -*- coding: utf-8 -*-
"""SLB tool: 扫雷宝风险查询 — 策略 A（包 slb_cmd.query_db）"""

from io import StringIO
from datetime import datetime

from rich.console import Console

from caishen_mcp.server import mcp, get_server_state, require_tq
from caishen_mcp.ctx_helper import safe_result, create_click_context


@mcp.tool()
def slb_query(
    stocks: list[str] | None = None,
    date: str | None = None,
    score_min: int = 0,
    score_max: int = 100,
    limit: int = 20,
    verbose: bool = False,
) -> str:
    """扫雷宝风险查询 — 查询个股的风险评分和埋雷检测结果。

    Args:
        stocks: 股票代码列表。为空则查询全部或按 score 范围筛选。
        date: 查询日期，格式 YYYY-MM-DD。默认最新。
        score_min: 最低 SLB 评分（0-100）。
        score_max: 最高 SLB 评分（0-100）。
        limit: 返回数量限制，默认 20。
        verbose: 是否输出详细信息。
    """
    try:
        require_tq()
        cfg, db_url, _ = get_server_state()

        from slb_cmd import query_db as _query_db

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        ctx = create_click_context(cfg, db_url, console)

        with ctx:
            _query_db.callback(
                db_type='pg',
            date=datetime.strptime(date, "%Y-%m-%d") if date else None,
            stocks=list(stocks) if stocks else [],
            markets=[],
            all_flag=False,
            latest_flag=(date is None),
            list_markets=False,
            slb_score_range=f"{score_min},{score_max}",
            risk_score_range=None,
            score_min=score_min,
            score_max=score_max,
            fill_market_code=False,
            limit=limit,
            verbose=verbose,
        )

        output_text = string_io.getvalue()
        return safe_result(
            "ok",
            summary="扫雷宝查询完成",
            detail=output_text[:2000] if verbose else None,
        )
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"扫雷宝查询失败: {e}", detail=str(e))
