# -*- coding: utf-8 -*-
"""Formula tools: 通达信公式计算 — 策略 A（包 tdxdata_cmd 函数）"""

import json
from io import StringIO

import pandas as pd
from rich.console import Console

from caishen_mcp.server import mcp, get_server_state, require_tq
from caishen_mcp.ctx_helper import log_tool_call, safe_result, create_click_context, df_to_json_safe


@mcp.tool()
def formula_list_all(formula_type: str = "zb") -> str:
    """列出所有可用的通达信公式。

    Args:
        formula_type: 公式类型。zb=技术指标, xg=条件选股, exp=专家系统
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq

        ft_int = {"zb": 0, "xg": 1, "exp": 2}.get(formula_type)
        if ft_int is None:
            return safe_result("error", message=f"不支持的公式类型: {formula_type}，可选: zb, xg, exp")

        res = tq.formula_get_all(formula_type=ft_int)
        if not res or not isinstance(res, list):
            return safe_result("ok", data=[], summary=f"未找到任何 {formula_type} 公式")

        formulas = [
            {"code": f.get("acCode", ""), "name": f.get("acName", ""), "description": f.get("acDesc", "")}
            for f in res if isinstance(f, dict)
        ]
        return safe_result("ok", data=formulas, total=len(formulas),
                          summary=f"找到 {len(formulas)} 个 {'技术指标' if formula_type == 'zb' else '条件选股' if formula_type == 'xg' else '专家系统'} 公式")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"公式列表查询失败: {e}", detail=str(e))


@mcp.tool()
def formula(
    formula_type: str,
    name: str,
    stocks: list[str] | None = None,
    args: list[str] | None = None,
    count: int = 20,
    period: str = "1d",
    dividend_type: int = 1,
    save_db: bool = False,
    replace: bool = False,
    jump_tdx: float | None = None,
    verbose: bool = False,
) -> str:
    """调用通达信公式进行计算（技术指标zb/条件选股xg/专家系统exp）。

    计算结果可选择性存入 PostgreSQL stock_metrics 表。

    Args:
        formula_type: 公式类型。zb=技术指标, xg=条件选股, exp=专家系统
        name: 公式名称，如 MACD、KDJ。先用 formula_list_all 查看可用公式。
        stocks: 股票代码列表，如 ["603337.SH", "000001.SZ"]。为空则使用内存缓存。
        args: 公式参数列表。MACD 为 ["12","26","9"]，KDJ 为 ["9","3","3"]。
        count: K线数量，默认 20。
        period: K线周期。1d=日线, 1w=周线, 1mon=月线, 1m=1分钟, 5m=5分钟。
        dividend_type: 复权方式。0=不复权, 1=前复权（默认）, 2=后复权。
        save_db: 是否直接存入 PostgreSQL stock_metrics 表。
        replace: 入库时是否替换已有记录（默认合并）。
        jump_tdx: 跳转到通达信个股页面并等待 N 秒（用于触发 L2 数据拉取）。
        verbose: 是否输出详细信息。
    """
    try:
        require_tq()
        log_tool_call()
        cfg, db_url, _ = get_server_state()

        from tdxdata_cmd import formula as _formula
        from difoss_stock_util.click_util import split_comma_stocks

        if stocks is None:
            stocks = []
        flat_stocks = []
        for s in stocks:
            flat_stocks.extend(split_comma_stocks(None, None, s) if isinstance(s, str) else [s])
        if not flat_stocks:
            return safe_result("error", message="股票列表为空，请通过 stocks 参数指定")

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        ctx = create_click_context(cfg, db_url, console)

        with ctx:
            _formula.callback(
                formula_type=formula_type,
                stocks=flat_stocks,
            count=count,
            period=period,
            dividend_type=dividend_type,
            name=name,
            args=args or [],
            xs_flag=0,
            max_to_show=300,
            verbose=verbose,
            list_all=False,
            field_exclusions=[],
            field_regex_exclusions=[r'^OUTPUT\d+'],
            field_inclusions=[],
            field_regex_inclusions=[],
            jump_tdx=jump_tdx,
            is_save_db=save_db,
            is_replace=replace,
            is_with_name=False,
        )

        output_text = string_io.getvalue()
        return safe_result(
            "ok",
            summary=f"公式 {name} 计算完成，{len(flat_stocks)} 只股票" + ("，已入库" if save_db else ""),
            detail=output_text[:2000] if verbose else None,
            stocks_count=len(flat_stocks),
            formula_name=name,
            saved_to_db=save_db,
        )
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"公式计算失败: {e}", detail=str(e))


@mcp.tool()
def formula_multi(
    formula_type: str,
    name: str,
    stocks: list[str] | None = None,
    args: list[str] | None = None,
    count: int = -1,
    period: str = "1d",
    dividend_type: int = 1,
    return_count: int = -1,
    save_db: bool = False,
    save_user_sector: bool = False,
    is_with_name: bool = False,
    verbose: bool = False,
) -> str:
    """批量多股票公式计算，支持选股结果存为用户板块。

    Args:
        formula_type: 公式类型。zb=技术指标, xg=条件选股（xg 支持选股结果存板块）。
        name: 公式名称。先用 formula_list_all 查看可用公式。
        stocks: 股票代码列表。为空则对全市场执行（xg 模式常用）。
        args: 公式参数列表。
        count: K线数量，-1 表示使用 return_count 指定的数量。
        period: K线周期，默认日线。
        dividend_type: 复权方式。0=不复权, 1=前复权, 2=后复权。
        return_count: 返回结果数量，-1 表示全部。
        save_db: 是否存入 PostgreSQL stock_metrics 表。
        save_user_sector: 是否将选股结果存为通达信用户板块（仅 xg 模式有效）。
        is_with_name: 是否输出时附带股票名称（--with-name）。
        verbose: 是否输出详细信息。
    """
    try:
        require_tq()
        log_tool_call()
        cfg, db_url, _ = get_server_state()

        from tdxdata_cmd import formula_multi as _formula_multi

        if not stocks:
            # stocks 为空时，从 TQ 拉取上证+深证+创业板（排除ST），约4400只
            from tdx_quant.tqcenter import tq
            from difoss_stock_util.stock_util import is_st_stock
            stocks = []
            for m in ['7', '8', '51']:
                info = tq.get_stock_list(market=m, list_type=1)
                if info:
                    stocks.extend([
                        s['Code'] for s in info
                        if isinstance(s, dict) and s.get('Code')
                        and not is_st_stock(s.get('Name', ''))
                    ])

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        ctx = create_click_context(cfg, db_url, console)

        with ctx:
            _formula_multi.callback(
                stocks=stocks,
                formula_type=formula_type,
            name=name,
            args=args or [],
            return_count=return_count,
            return_start_time=None,
            return_end_time=None,
            count=count,
            start_time=None,
            end_time=None,
            period=period,
            dividend_type=dividend_type,
            xs_flag=0,
            verbose=verbose,
            field_exclusions=[],
            field_regex_exclusions=[r'^OUTPUT\d+'],
            field_inclusions=[],
            field_regex_inclusions=[],
            is_with_name=is_with_name,
            output_style='stock',
            sum_columns=[],
            is_save_user_sector=save_user_sector,
            is_save_db=save_db,
            cache_stocks=False,
            stock_group_index=0,
            cache_df=False,
        )

        output_text = string_io.getvalue()
        return safe_result(
            "ok",
            summary=f"批量公式 {name} 计算完成" + ("，已入库" if save_db else ""),
            detail=output_text[:2000] if verbose else None,
            formula_name=name,
            saved_to_db=save_db,
        )
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"批量公式计算失败: {e}", detail=str(e))
