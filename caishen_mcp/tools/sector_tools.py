# -*- coding: utf-8 -*-
"""Sector tools: 板块查询 — 策略 B（直接调 tdx_quant API）"""

from caishen_mcp.server import mcp, require_tq
from caishen_mcp.ctx_helper import log_tool_call, safe_result


@mcp.tool()
def get_sector_list() -> str:
    """列出通达信所有板块（行业板块、概念板块等）。"""
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq

        sectors = tq.get_sector_list(list_type=1)
        if not sectors:
            return safe_result("ok", data=[], summary="未获取到板块列表")

        result = [{"code": s.get("Code", ""), "name": s.get("Name", ""),
                   "type": s.get("Type", "")}
                  for s in sectors if isinstance(s, dict)]
        return safe_result("ok", data=result, total=len(result),
                          summary=f"获取到 {len(result)} 个板块")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"板块列表获取失败: {e}", detail=str(e))


@mcp.tool()
def get_stocks_in_sector(block_code: str, block_type: int = 0) -> str:
    """获取板块成分股列表。

    Args:
        block_code: 板块代码，如 "880301"（行业板块）。
        block_type: 板块类型。0=通达信系统板块, 1=用户自定义板块。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq

        stocks = tq.get_stock_list_in_sector(block_code=block_code,
                                              block_type=block_type, list_type=1)
        if not stocks:
            return safe_result("ok", data=[], summary=f"板块 {block_code} 无成分股")

        result = [{"code": s.get("Code", ""), "name": s.get("Name", "")}
                  for s in stocks if isinstance(s, dict)]
        return safe_result("ok", data=result, total=len(result),
                          summary=f"板块 {block_code} 包含 {len(result)} 只成分股")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"成分股查询失败: {e}", detail=str(e))


@mcp.tool()
def get_user_sector_list() -> str:
    """列出所有用户自定义板块。"""
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq

        sectors = tq.get_user_sector()
        if not sectors:
            return safe_result("ok", data=[], summary="无用户自定义板块")

        result = [{"code": s.get("Code", s.get("code", "")),
                   "name": s.get("Name", s.get("name", ""))}
                  for s in sectors if isinstance(s, dict)]
        return safe_result("ok", data=result, total=len(result),
                          summary=f"获取到 {len(result)} 个用户板块")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"用户板块列表获取失败: {e}", detail=str(e))


@mcp.tool()
def get_user_sector_stocks(block_code: str) -> str:
    """获取用户自定义板块的成分股列表。

    Args:
        block_code: 用户板块代码。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq

        stocks = tq.get_stock_list_in_sector(block_code=block_code,
                                              block_type=1, list_type=1)
        if not stocks:
            return safe_result("ok", data=[], summary=f"用户板块 {block_code} 无成分股")

        result = [{"code": s.get("Code", ""), "name": s.get("Name", "")}
                  for s in stocks if isinstance(s, dict)]
        return safe_result("ok", data=result, total=len(result),
                          summary=f"用户板块 {block_code} 包含 {len(result)} 只成分股")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"查询失败: {e}", detail=str(e))
