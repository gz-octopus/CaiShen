# -*- coding: utf-8 -*-
"""MCP Server 公共工具：TQ 初始化、click.Context 构造、统一输出"""

import inspect
import json
import sys
import threading
from collections import defaultdict
from io import StringIO

import click
import pandas as pd
from rich.console import Console

from difoss_stock_util.util import read_yaml_config
from difoss_stock_util.db_util import generate_engine_url_str
from tdx_quant.tqcenter import tq
from cache_cmd import cache_stock_name, cache_st_stock_name, cache_block_name, STOCKS

# 线程本地存储：log_tool_call → safe_result 传递调用信息
_tl = threading.local()


def log_tool_call() -> None:
    """记录当前 tool 名称和参数，存入线程本地 + 打印 stderr。

    自动通过调用栈检测函数名和参数，无需手动传参。
    每个 @mcp.tool() 函数在 try 块第一行调用即可。

    调用信息会：
    1. 打印到 stderr（服务端日志，用于调试）
    2. 存入 _tl.tool_call，供 safe_result() 自动注入到响应的 _tool 字段
    """
    frame = inspect.currentframe()
    if frame is None:
        return
    caller = frame.f_back
    if caller is None:
        return

    func_name = caller.f_code.co_name
    arg_info = inspect.getargvalues(caller)
    args_dict = {
        k: arg_info.locals[k]
        for k in arg_info.args
        if k not in ('self', 'cls')
    }

    parts = []
    for k, v in args_dict.items():
        v_str = repr(v)
        if len(v_str) > 500:
            v_str = v_str[:500] + "..."
        parts.append(f"{k}={v_str}")

    call_str = f"{func_name}({', '.join(parts)})"
    _tl.tool_call = call_str
    print(f"[caishen-mcp] {call_str}", file=sys.stderr, flush=True)


def safe_result(status: str, **kwargs) -> str:
    """构造统一 JSON 返回字符串。status: 'ok' | 'error' | 'partial'

    自动注入 log_tool_call() 记录的调用信息到 _tool 字段。
    """
    result = {"status": status}
    result.update(kwargs)
    # 注入调用信息：让每次 tool 返回结果的第一眼就看到命令和参数
    call_info = getattr(_tl, 'tool_call', None)
    if call_info:
        result['_tool'] = call_info
        _tl.tool_call = None
    return json.dumps(result, ensure_ascii=False, default=str)


def _cache_stock_name_of_market(market: str = None):
    """缓存 A 股 code → name 到 cache_cmd 全局变量"""
    code2name = {}
    st_code2name = {}
    stocks_info = tq.get_stock_list(market=market, list_type=1)
    for stock_info in (stocks_info or []):
        if isinstance(stock_info, dict):
            code = stock_info.get('Code')
            name = stock_info.get('Name')
            if code and name:
                code2name[code] = name
                from difoss_stock_util.stock_util import is_st_stock
                if is_st_stock(name):
                    st_code2name[code] = name
    cache_st_stock_name(st_code2name)
    cache_stock_name(code2name)
    return len(code2name)


def _cache_all_blocks_name():
    """缓存通达信板块 code → name 到 cache_cmd 全局变量"""
    sectors = tq.get_sector_list(list_type=1)
    if sectors and isinstance(sectors, list):
        c2n = {s['Code']: s['Name'] for s in sectors if isinstance(s, dict)}
        cache_block_name(c2n)
        return len(c2n)
    return 0


def _cache_stocks_for_screening():
    """缓存上证A股+深证A股+创业板代码到 STOCKS（排除ST），供 formula_multi 全市场选股使用"""
    from difoss_stock_util.stock_util import is_st_stock

    markets = ['7', '8', '51']  # 上证主板, 深证主板, 创业板
    total = 0
    for m in markets:
        stocks_info = tq.get_stock_list(market=m, list_type=1)
        if not stocks_info:
            continue
        codes = [
            s['Code'] for s in stocks_info
            if isinstance(s, dict) and s.get('Code')
            and not is_st_stock(s.get('Name', ''))
        ]
        STOCKS.update(codes)
        total += len(codes)
    return total


def init_tq_and_cache(config_path: str = 'config.yaml') -> tuple[dict, str, Console]:
    """初始化 TQ 连接并缓存股票名/板块名。

    Returns:
        (cfg, db_url, console) — 初始化后的配置字典、PG 连接串、Console 实例

    Raises:
        RuntimeError: TQ 初始化失败或 PG 配置缺失
    """
    console = Console(file=StringIO(), force_terminal=False)
    cfg = read_yaml_config(config_path)

    # 组装 PG URL
    pg_cfg = cfg.get('postgresql', {})
    if not pg_cfg:
        raise RuntimeError("PostgreSQL 配置缺失，请检查 config.yaml")
    db_url = generate_engine_url_str(**pg_cfg)

    # 初始化 TQ
    tq.initialize(__file__)
    stock_count = _cache_stock_name_of_market()
    block_count = _cache_all_blocks_name()
    stocks_cached = _cache_stocks_for_screening()
    console.file = StringIO()  # 重置 buffer

    print(f"[caishen-mcp] 已缓存 {stocks_cached} 只筛选用股票代码", file=sys.stderr)

    return cfg, db_url, console


def create_click_context(cfg: dict, db_url: str, console: Console) -> click.Context:
    """构造 click.Context，注入 ctx.obj 供策略 A 的 tdxdata_cmd 函数使用。

    ctx.obj 包含: config_path, console, cfg, db_url
    """
    from click.core import Context, Command

    dummy_cmd = Command(name='mcp_tool')
    ctx = Context(dummy_cmd)
    ctx.ensure_object(defaultdict)
    ctx.obj['config_path'] = 'config.yaml'
    ctx.obj['console'] = console
    ctx.obj['cfg'] = cfg
    ctx.obj['db_url'] = db_url
    return ctx


def check_tq_alive() -> bool:
    """检查 TQ 连接是否存活。通过尝试一个轻量 API 调用来判断。"""
    try:
        result = tq.get_trading_dates(market='SH', start_time='', end_time='', count=1)
        return result is not None and isinstance(result, list)
    except Exception:
        return False


def df_to_json_safe(df: pd.DataFrame) -> list[dict]:
    """将 DataFrame 转换为 JSON 安全的 list[dict]。
    处理 Timestamp/NaN/Inf 等非 JSON 类型。
    """
    if df is None:
        return []
    cleaned = df.where(pd.notna(df), None)
    cleaned = cleaned.replace([float('inf'), float('-inf')], [None, None])
    return cleaned.to_dict(orient='records')
