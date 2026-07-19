# -*- coding: utf-8 -*-
"""MCP Server 公共工具：TQ 初始化、click.Context 构造、统一输出"""

import json
from collections import defaultdict
from io import StringIO

import click
import pandas as pd
from rich.console import Console

from difoss_stock_util.util import read_yaml_config
from difoss_stock_util.db_util import generate_engine_url_str
from tdx_quant.tqcenter import tq
from cache_cmd import cache_stock_name, cache_st_stock_name, cache_block_name


def safe_result(status: str, **kwargs) -> str:
    """构造统一 JSON 返回字符串。status: 'ok' | 'error' | 'partial'"""
    result = {"status": status}
    result.update(kwargs)
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
    console.file = StringIO()  # 重置 buffer

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
