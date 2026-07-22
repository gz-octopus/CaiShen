# -*- coding: utf-8 -*-
"""Data tools: 数据查询类 — 策略 B（直接调 tdx_quant API 或 ORM model）"""

import json
from datetime import datetime

import pandas as pd

from caishen_mcp.server import mcp, get_server_state, require_tq
from caishen_mcp.ctx_helper import log_tool_call, safe_result, df_to_json_safe


# ═══════════════════════════════════════════════════════════════
# 通用 helper
# ═══════════════════════════════════════════════════════════════

def _normalize_stocks(stocks: list[str] | None) -> list[str]:
    """标准化股票列表：None → []，处理逗号分隔字符串"""
    if not stocks:
        return []
    from difoss_stock_util.click_util import split_comma_stocks
    result = []
    for s in stocks:
        if isinstance(s, str) and ',' in s:
            result.extend(split_comma_stocks(None, None, s))
        else:
            result.append(s)
    return result


def _json_dumps(obj, **kwargs) -> str:
    """JSON 序列化，默认处理 str 类型转换"""
    return json.dumps(obj, ensure_ascii=False, default=str, **kwargs)


# ═══════════════════════════════════════════════════════════════
# 核心数据查询
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def get_stock_metrics(
    stocks: list[str],
    formula_key: str | None = None,
    indicator_key: str | None = None,
    period: str = "1d",
    dividend_type: int = 1,
    count: int = 20,
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
    """从 stock_metrics 表查询已存储的指标数据。

    Args:
        stocks: 股票代码列表，如 ["603337.SH", "000001.SZ"]
        formula_key: 公式标识，如 "MACD|12,26,9" 或 "L2_DATA|0"。不指定则返回所有。
        indicator_key: 指标子键，如 "DIF"、"DDX"。不指定则返回该 formula_key 下所有指标。
        period: K线周期，默认 1d。
        dividend_type: 复权方式，默认 1（前复权）。
        count: 返回最近多少条，默认 20。
        start_time: 起始时间，格式 "YYYY-MM-DD"。
        end_time: 截止时间，格式 "YYYY-MM-DD"。
    """
    try:
        require_tq()
        log_tool_call()
        _, db_url, _ = get_server_state()

        from difoss_stock_util.metric_data.stock_metrics import StockMetrics
        StockMetrics.init_db(db_url)

        flat_stocks = _normalize_stocks(stocks)
        if not flat_stocks:
            return safe_result("error", message="股票列表为空")

        if not end_time:
            end_time = datetime.now().strftime("%Y-%m-%d")

        all_results = []
        for symbol in flat_stocks:
            rows = StockMetrics.query(
                db_url=db_url, symbol=symbol, period=period,
                start_time=start_time or "2000-01-01", end_time=end_time,
                dividend_type=dividend_type,
                formula_key=formula_key, indicator_key=indicator_key,
            )
            if rows:
                all_results.extend(rows[-count:] if count > 0 else rows)

        return safe_result(
            "ok",
            data=all_results,
            total=len(all_results),
            summary=f"查询到 {len(all_results)} 条记录",
        )
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"查询失败: {e}", detail=str(e))


@mcp.tool()
def get_market_data(
    stocks: list[str],
    period: str = "1d",
    dividend_type: str = "front",
    count: int = -1,
    start_time: str | None = None,
    end_time: str | None = None,
    fields: list[str] | None = None,
) -> str:
    """获取 K 线数据（OHLCV）。

    Args:
        stocks: 股票代码列表。
        period: K线周期。1d=日线, 1w=周线, 1mon=月线, 1m/5m/15m/30m/1h=分钟。
        dividend_type: 复权方式。none=不复权, front=前复权, back=后复权。
        count: K线数量，-1 表示全部。
        start_time: 起始时间 "YYYY-MM-DD"。
        end_time: 截止时间 "YYYY-MM-DD"。
        fields: 字段列表，如 ["Open","High","Low","Close","Volume"]。默认全部。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq

        flat_stocks = _normalize_stocks(stocks)
        if not flat_stocks:
            return safe_result("error", message="股票列表为空")

        if not end_time:
            end_time = datetime.now().strftime("%Y-%m-%d")

        result = tq.get_market_data(
            field_list=fields or [],
            stock_list=flat_stocks,
            period=period,
            start_time=start_time or '',
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            fill_data=True,
        )

        if not result:
            return safe_result("ok", data={}, summary="未获取到数据")

        records = []
        for field_name, df in result.items():
            if df is None or df.empty:
                continue
            for date_idx, row in df.iterrows():
                for col in df.columns:
                    val = row[col]
                    records.append({
                        "stock": str(col),
                        "date": str(date_idx),
                        "field": field_name,
                        "value": None if pd.isna(val) else float(val) if isinstance(val, (int, float)) else str(val),
                    })

        return safe_result("ok", data=records, total=len(records),
                          summary=f"获取到 {len(records)} 条 K 线数据记录")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"K 线数据获取失败: {e}", detail=str(e))


@mcp.tool()
def get_stock_list(market: str = "") -> str:
    """按市场列出股票列表。

    Args:
        market: 市场代码。空字符串=全部A股, "SH"=上海, "SZ"=深圳, "BJ"=北交所, "5"=全部A股。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq

        res = tq.get_stock_list(market=market, list_type=1)
        if not res:
            return safe_result("ok", data=[], summary="未获取到股票列表")

        stocks = [{"code": s.get("Code", ""), "name": s.get("Name", "")}
                  for s in res if isinstance(s, dict)]
        return safe_result("ok", data=stocks, total=len(stocks),
                          summary=f"获取到 {len(stocks)} 只股票")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"股票列表获取失败: {e}", detail=str(e))


@mcp.tool()
def get_match_stkinfo(keyword: str) -> str:
    """按关键词模糊搜索股票代码/名称。

    Args:
        keyword: 搜索关键词，支持中文名、拼音首字母、代码片段。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq

        res = tq.get_match_stkinfo(key_word=keyword)
        if not res:
            return safe_result("ok", data=[], summary=f"未找到匹配 '{keyword}' 的股票")

        stocks = [{"code": s.get("code", s.get("Code", "")),
                   "name": s.get("name", s.get("Name", "")),
                   "market": s.get("market", s.get("Market", ""))}
                  for s in res if isinstance(s, dict)]
        return safe_result("ok", data=stocks, total=len(stocks),
                          summary=f"找到 {len(stocks)} 只匹配 '{keyword}' 的股票")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"搜索失败: {e}", detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 个股信息查询
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def get_stock_info(stock: str) -> str:
    """获取个股基本信息（财务指标摘要）。

    Args:
        stock: 股票代码，如 "603337.SH"。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        res = tq.get_stock_info(stock_code=stock)
        return safe_result("ok", data=res if isinstance(res, dict) else {},
                          summary=f"获取 {stock} 基本信息成功")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_more_info(stock: str) -> str:
    """获取个股扩展信息（资金流向、换手率等）。

    Args:
        stock: 股票代码，如 "603337.SH"。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        res = tq.get_more_info(stock_code=stock)
        return safe_result("ok", data=res if isinstance(res, dict) else {},
                          summary=f"获取 {stock} 扩展信息成功")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_market_snapshot(stock: str) -> str:
    """获取个股实时行情快照。

    Args:
        stock: 股票代码，如 "603337.SH"。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        res = tq.get_market_snapshot(stock_code=stock)
        return safe_result("ok", data=res if isinstance(res, dict) else {},
                          summary=f"获取 {stock} 行情快照成功")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_financial_data(
    stocks: list[str],
    start_time: str = "",
    end_time: str = "",
    report_type: str = "report_time",
) -> str:
    """获取个股财务数据。

    Args:
        stocks: 股票代码列表。
        start_time: 起始时间 "YYYY-MM-DD"。
        end_time: 截止时间 "YYYY-MM-DD"。
        report_type: 报表类型。report_time=报告期, announce_time=公告日。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        flat_stocks = _normalize_stocks(stocks)
        res = tq.get_financial_data(
            stock_list=flat_stocks, start_time=start_time,
            end_time=end_time, report_type=report_type,
        )
        return safe_result("ok", data=res if isinstance(res, dict) else {},
                          summary=f"获取 {len(flat_stocks)} 只股票财务数据成功")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_divide_factors(stock: str, start_time: str = "", end_time: str = "") -> str:
    """获取个股除权除息因子。

    Args:
        stock: 股票代码，如 "603337.SH"。
        start_time: 起始时间 "YYYY-MM-DD"。
        end_time: 截止时间 "YYYY-MM-DD"。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        df = tq.get_divid_factors(stock_code=stock, start_time=start_time, end_time=end_time)
        records = df_to_json_safe(df)
        return safe_result("ok", data=records, total=len(records),
                          summary=f"获取 {stock} 除权因子成功，{len(records)} 条")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_ipo_info(ipo_type: int = 0, ipo_date: int = 0) -> str:
    """获取新股申购信息。

    Args:
        ipo_type: IPO 类型，默认 0。
        ipo_date: IPO 日期（格式：YYYYMMDD），0 表示当天。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        res = tq.get_ipo_info(ipo_type=ipo_type, ipo_date=ipo_date)
        return safe_result("ok", data=res if isinstance(res, list) else [],
                          summary=f"获取 IPO 信息成功，{len(res) if res else 0} 条")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_gb_info(stock: str, count: int = 1) -> str:
    """获取个股股本信息。

    Args:
        stock: 股票代码，如 "603337.SH"。
        count: 返回最近多少期，默认 1。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        res = tq.get_gb_info(stock_code=stock, count=count)
        return safe_result("ok", data=res if isinstance(res, dict) else {},
                          summary=f"获取 {stock} 股本信息成功")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_cb_info(stock: str) -> str:
    """获取可转债信息（若该股票有可转债）。

    Args:
        stock: 正股代码，如 "603337.SH"。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        res = tq.get_cb_info(stock_code=stock)
        return safe_result("ok", data=res if isinstance(res, dict) else {},
                          summary=f"获取 {stock} 可转债信息成功")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_trading_dates(market: str = "SH", count: int = 20) -> str:
    """获取交易日列表。

    Args:
        market: 市场代码。SH=上海, SZ=深圳。
        count: 返回最近多少个交易日，默认 20。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        dates = tq.get_trading_dates(market=market, start_time="", end_time="", count=count)
        return safe_result("ok", data=dates if isinstance(dates, list) else [],
                          total=len(dates) if dates else 0,
                          summary=f"获取 {len(dates) if dates else 0} 个交易日")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


# ═══════════════════════════════════════════════════════════════
# 交易数据查询
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def get_gpjy_value(
    stocks: list[str],
    start_time: str = "",
    end_time: str = "",
    date: str | None = None,
) -> str:
    """获取个股交易数据（主力动向、资金流向等）。

    Args:
        stocks: 股票代码列表。
        start_time: 起始时间 "YYYY-MM-DD"。
        end_time: 截止时间 "YYYY-MM-DD"。
        date: 指定日期（格式 MMDD，如 "0615"）。传入此参数将使用 by_date 接口。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        flat_stocks = _normalize_stocks(stocks)
        if date:
            res = tq.get_gpjy_value_by_date(stock_list=flat_stocks, field_list=[], mmdd=int(date))
        else:
            res = tq.get_gpjy_value(stock_list=flat_stocks, field_list=[],
                                     start_time=start_time, end_time=end_time)
        return safe_result("ok", data=res if isinstance(res, dict) else {},
                          summary=f"获取 {len(flat_stocks)} 只股票交易数据成功")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_bkjy_value(
    stocks: list[str] | None = None,
    start_time: str = "",
    end_time: str = "",
    date: str | None = None,
) -> str:
    """获取板块交易数据。

    Args:
        stocks: 板块代码列表（可选）。
        start_time: 起始时间 "YYYY-MM-DD"。
        end_time: 截止时间 "YYYY-MM-DD"。
        date: 指定日期（格式 MMDD）。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        flat = _normalize_stocks(stocks or [])
        if date:
            res = tq.get_bkjy_value_by_date(stock_list=flat, field_list=[], mmdd=int(date))
        else:
            res = tq.get_bkjy_value(stock_list=flat, field_list=[],
                                     start_time=start_time, end_time=end_time)
        return safe_result("ok", data=res if isinstance(res, dict) else {},
                          summary="获取板块交易数据成功")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def get_scjy_value(start_time: str = "", end_time: str = "", date: str | None = None) -> str:
    """获取市场整体交易数据。

    Args:
        start_time: 起始时间 "YYYY-MM-DD"。
        end_time: 截止时间 "YYYY-MM-DD"。
        date: 指定日期（格式 MMDD）。
    """
    try:
        require_tq()
        log_tool_call()
        from tdx_quant.tqcenter import tq
        if date:
            res = tq.get_scjy_value_by_date(field_list=[], mmdd=int(date))
        else:
            res = tq.get_scjy_value(field_list=[], start_time=start_time, end_time=end_time)
        return safe_result("ok", data=res if isinstance(res, dict) else {},
                          summary="获取市场交易数据成功")
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"获取失败: {e}", detail=str(e))


@mcp.tool()
def stock_block_stat(stocks: list[str] | None = None) -> str:
    """获取股票所属板块统计信息。

    Args:
        stocks: 股票代码列表（可选，默认使用缓存中的股票）。
    """
    try:
        require_tq()
        log_tool_call()
        cfg, db_url, _ = get_server_state()

        from tdxdata_cmd import stock_block_stat as _sbs
        from io import StringIO
        from rich.console import Console
        from caishen_mcp.ctx_helper import create_click_context

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        ctx = create_click_context(cfg, db_url, console)

        with ctx:
            _sbs.callback(stocks=_normalize_stocks(stocks) if stocks else None)
        return safe_result("ok", summary="板块统计完成", detail=string_io.getvalue()[:2000])
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"统计失败: {e}", detail=str(e))


@mcp.tool()
def stock_stat(stocks: list[str] | None = None) -> str:
    """获取股票分类统计信息。

    Args:
        stocks: 股票代码列表（可选）。
    """
    try:
        require_tq()
        log_tool_call()
        cfg, db_url, _ = get_server_state()

        from tdxdata_cmd import stock_stat as _ss
        from io import StringIO
        from rich.console import Console
        from caishen_mcp.ctx_helper import create_click_context

        string_io = StringIO()
        console = Console(file=string_io, force_terminal=False)
        ctx = create_click_context(cfg, db_url, console)

        with ctx:
            _ss.callback(stocks=_normalize_stocks(stocks) if stocks else None)
        return safe_result("ok", summary="分类统计完成", detail=string_io.getvalue()[:2000])
    except RuntimeError as e:
        return safe_result("error", message=str(e))
    except Exception as e:
        return safe_result("error", message=f"统计失败: {e}", detail=str(e))
