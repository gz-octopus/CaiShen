#!python
# -*- coding: utf-8 -*-
# Author: DifossChen
# Version: v0.0.2
# Description: 内存缓存功能（仅在REPL下有效）
# Changes:
#  v0.0.1 (2026-03-06): 初始版本
#  v0.0.2 (2026-05-27):
# 【修复】 _print_status 中即使主缓存为空，也能展示所有非空的分组。
#  v0.1.0 (2026-06-15):
# 【添加】memory_cache 添加保存 ebk,txt 文件的功能
# 【完善】stock_collector
import click
from typing import Optional, Callable, Dict, Iterable
from datetime import datetime
from collections import defaultdict

from rich import console
from rich.pretty import Pretty
import threading
import functools

from difoss_stock_util.util import *
from difoss_stock_util.click_util import *
from difoss_stock_util.color_log_util import *
from difoss_stock_util.tdx_util import TdxEbk

from difoss_stock_util.click_util import print_dataframe

import pandas as pd


# Constants
ACTIONS = (
    'show', 's',
    'clear', 'c',
    'add', '+',
    'remove', 'delete', 'del', '-',
    'difference', 'diff', 'd',
    'cross', 'intersection', 'intersect', 'i', # TODO: 实现交集功能
)

# Globals
STOCKS = set()
GROUPED_STOCKS = defaultdict(set) # type: Dict[int, set]
BLOCKS = set()
GROUPED_BLOCKS = defaultdict(set) # type: Dict[int, set]
STOCKS_DF = pd.DataFrame()
STOCK_2_DF = dict() # type: Dict[str, pd.DataFrame]
_STOCK_2_NAME = {}
_ST_STOCK_2_NAME = {}
_lock = threading.RLock()

class CacheManager:
    """统一管理缓存逻辑，避免装饰器直接操作 global 变量"""
    def update_stocks(self, codes: Iterable):
        if not codes:
            return
        global STOCKS
        old_len = len(STOCKS)
        STOCKS.update(codes)
        I(f"新增 {len(STOCKS) - old_len} 只个股", _level='CACHE')

    def update_group_stocks(self, group_index, codes: Iterable):
        """将数据处理后存入指定分组"""
        if not codes:
            return
        global GROUPED_STOCKS

        # 确保分组存在
        if group_index not in GROUPED_STOCKS:
            GROUPED_STOCKS[group_index] = set()

        old_len = len(GROUPED_STOCKS[group_index])

        GROUPED_STOCKS[group_index].update(codes)

        I(f"新增 {len(GROUPED_STOCKS[group_index]) - old_len} 只个股到分组 {group_index}", _level='CACHE')


    def update_dataframe_by_stock(self, code: str, new_df: pd.DataFrame, prefix: str=None):
        """以每个 stock code 作为索引，合并或更新对应的 df（通常 index 是 datetime）"""
        global STOCK_2_DF

        # click.echo(f"【update_dataframe_by_stock】code={code}, len(df)={new_df.shape}")
        # 确保索引为 datetime 类型，方便 merge
        new_df = new_df.copy()
        if not isinstance(new_df.index, pd.DatetimeIndex):
            new_df.index = pd.to_datetime(new_df.index)

        # 添加列前缀（幂等：已带前缀则跳过）
        if prefix:
            if not all(str(c).startswith(prefix) for c in new_df.columns):
                new_df.columns = [f"{prefix}{c}" for c in new_df.columns]
                I(f"股票 {code} 已添加列前缀 '{prefix}'", _level='CACHE')

        if code not in STOCK_2_DF:
            STOCK_2_DF[code] = new_df
        else:
            # 检测列/行重复：重复列+重复行跳过，新列或新行继续合并
            existing_cols = set(STOCK_2_DF[code].columns)
            incoming_cols = set(new_df.columns)
            dup_cols = existing_cols & incoming_cols
            new_cols = incoming_cols - existing_cols

            if dup_cols:
                existing_idx = STOCK_2_DF[code].index
                new_row_mask = ~new_df.index.isin(existing_idx)
                dup_rows_skipped = (~new_row_mask).sum()

                W(f"股票 {code} 的以下列已在缓存中存在: {sorted(dup_cols)}，"
                  f"跳过 {dup_rows_skipped} 行重复数据", _level='CACHE')

                if not new_row_mask.any() and not new_cols:
                    return  # 列重复且无新行、无新列，无需合并

                # 重建 new_df：新列保留全部行，重复列仅保留新行
                parts = []
                if new_cols:
                    parts.append(new_df[list(new_cols)])
                if new_row_mask.any():
                    parts.append(new_df.loc[new_row_mask, list(dup_cols)])
                new_df = pd.concat(parts, axis=1) if len(parts) > 1 else parts[0]

            # 核心：使用 outer join 合并，避免信息丢失，将原有与新数据对齐
            STOCK_2_DF[code] = pd.merge(
                STOCK_2_DF[code],
                new_df,
                left_index=True,
                right_index=True,
                how='outer',
            )
        # click.echo(f"【update_dataframe_by_stock】code={code}, len(df)={STOCK_2_DF[code].shape}")

    def update_blocks(self, codes: Iterable):
        if not codes:
            return
        global BLOCKS
        old_len = len(BLOCKS)
        BLOCKS.update(codes)
        I(f"新增 {len(BLOCKS) - old_len} 个板块", _level='CACHE')

    def update_group_blocks(self, group_index, codes: Iterable):
        """将板块数据存入指定分组"""
        global GROUPED_BLOCKS

        if group_index not in GROUPED_BLOCKS:
            GROUPED_BLOCKS[group_index] = set()

        old_len = len(GROUPED_BLOCKS[group_index])
        GROUPED_BLOCKS[group_index].update(codes)
        I(f"新增 {len(GROUPED_BLOCKS[group_index]) - old_len} 个板块到分组 {group_index}", _level='CACHE')

    def update_dataframe(self, df: pd.DataFrame, prefix: str=None):
        global STOCKS_DF

        # 添加列前缀（幂等：已带前缀则跳过）
        if prefix:
            if not all(str(c).startswith(prefix) for c in df.columns):
                df.columns = [f"{prefix}{c}" for c in df.columns]
                I(f"STOCKS_DF 已添加列前缀 '{prefix}'", _level='CACHE')

        # 核心合并逻辑
        if df.empty:
            STOCKS_DF = df # 清空
        if STOCKS_DF is None:
            STOCKS_DF = df
        else:
            STOCKS_DF = df.combine_first(STOCKS_DF)

    def _extract_codes(self, data):
        # 逻辑：从可能的字段提取代码
        if isinstance(data, (list, set)): return set(data)
        if isinstance(data, dict): return set(data.values())
        if isinstance(data, pd.DataFrame):
            # 提取列名为 code, codes, stock, stocks 的所有数据
            # 定义潜在的列名关键词
            target_cols = {'code', 'codes', 'stock', 'stocks', 'ts_code', 'ticker'}

            # 找到数据表中存在的列名
            cols_to_extract = [col for col in data.columns if col.lower() in target_cols]

            extracted = set()
            for col in cols_to_extract:
                # 转换为字符串并去重，同时排除 NaN 或空值
                codes = data[col].dropna().astype(str).unique()
                extracted.update(codes)

            return extracted
        return set()

CACHE = CacheManager()

# --------------------------------------------------------------------------------

def _print_status(targets: Dict[Optional[int], set],
                  contains: list[str],
                  console: console.Console,
                  max_to_show: int,
                  with_name: bool):
    """
    统一将缓存状态整理并展示，包含分组股票总数和省略提示
    """
    # 1. 构建全量显示数据源：包含主缓存 + 所有已有数据的分组
    all_targets = {None: STOCKS}  # 始终包含主缓存
    all_targets.update(GROUPED_STOCKS) # 合并所有分组

    data = []

    # 2. 扁平化数据
    for idx, stocks in all_targets.items():
        if not stocks: continue # 跳过空集合

        group_name = f"分组 {idx}" if idx is not None else "主缓存"
        for code in stocks:
            name = get_stock_name(code, "未知")
            data.append({"分组": group_name, "代码": code.upper(), "名称": name})

    if not data:
        console.print("[yellow]缓存中暂无股票。[/yellow]")
        return

    df = pd.DataFrame(data)

    # 2. 智能过滤逻辑
    if contains:
        combined_mask = pd.Series([False] * len(df))
        for item in contains:
            item_upper = item.upper()
            if '.' in item_upper or item.isdigit() or item_upper[:2].isascii():
                mask = df['代码'].str.contains(item_upper, na=False)
            else:
                mask = df['名称'].str.contains(item_upper, na=False)
            combined_mask |= mask
        df = df[combined_mask]

    if df.empty:
        console.print(f"[yellow]没有找到匹配 {contains} 的记录。[/yellow]")
        return

    # 3. 准备展示数据
    if with_name:
        df['item'] = df['代码'] + "|" + df['名称']
    else:
        df['item'] = df['代码']

    # 4. 聚合展示
    console.print(f"\n[bold]当前缓存概览:[/bold]")
    # 按照分组名称排序，确保主缓存排在前面
    grouped = df.groupby('分组', sort=False)['item'].apply(list)


    # 强制将主缓存放在第一位显示 (如果存在)
    if "主缓存" in grouped.index:
        order = ["主缓存"] + [g for g in grouped.index if g != "主缓存"]
        grouped = grouped.reindex(order)

    for group, items in grouped.items():
        total_count = len(items)

        # 确定显示内容
        if max_to_show > 0 and total_count > max_to_show:
            display_items = items[:max_to_show]
            omitted_count = total_count - max_to_show
            suffix = f", ... (省略 {omitted_count} 个)"
        else:
            display_items = items
            suffix = ""

        console.print(f"[cyan]{group}[/cyan] ([bold]{total_count}[/bold] 只): {', '.join(display_items)}{suffix}")


def _handle_transfer(move_to, copy_to, move_from, copy_from):
    """处理集合间的移动与复制逻辑"""
    global STOCKS, GROUPED_STOCKS

    # 移动到分组
    if move_to or copy_to:
        idx = move_to or copy_to
        GROUPED_STOCKS[idx].update(STOCKS)
        if move_to:
            STOCKS.clear()

    # 从分组移动到主缓存
    if move_from or copy_from:
        idx = move_from or copy_from
        if idx in GROUPED_STOCKS:
            STOCKS.update(GROUPED_STOCKS[idx])
            if move_from:
                GROUPED_STOCKS[idx].clear()

# ---------------------------------------------------------------------------------------------
# 缓存功能（仅REPL下有效）
@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--action', '-a', 'action', default='show',
            type=click.Choice(ACTIONS, case_sensitive=False))
@click.option('--contains', '-c', 'contains', multiple=True, callback=split_comma_upper, help='包含的字串（代码或者名称）')
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
            help='股票代码列表 (如: 688318.SH 或 688318)，支持半角逗号分隔')
@click.option('--with-name', '-wn', 'with_name', is_flag=True, help='显示时是否包含名称（仅在 action=show 时有效）')
@click.option('--max-to-show', '-max', 'max_to_show', default=20, show_default=True, type=int, help='显示时的最大股票数量')
@click.option('--save-file-type', '-t', 'save_type_file', type=click.Choice(['txt', 'ebk'], case_sensitive=False), help='是否将结果输出到文件（仅在 action=show 时有效）')
@click.option('--filename', '-f', 'filename_to_save', help='输出文件名（仅在 action=show 时有效，默认 cache_YYYYMMDD-HHMMSS）')
@click.option('--group-index', '-i', 'group_indexes', default=[], type=list, callback=split_comma_int,
              help='分组索引（当 action=difference 时带多个）')
@click.option('--move-to-group-index', '-mti', 'move_to_group_index', type=int, help='从 缓存 到分组缓存')
@click.option('--move-from-group-index', '-mfi', 'move_from_group_index', type=int, help='从分组缓存 到 缓存')
@click.option('--copy-to-group-index', '-cti', 'copy_to_group_index', type=int, help='从 缓存 复制 到分组缓存（保留缓存不变）')
@click.option('--copy-from-group-index', '-cfi', 'copy_from_group_index', type=int, help='从分组缓存 复制 到缓存（保留缓存不变）')
@click.pass_context
def memory_cache(_ctx: click.Context,
    action: str,
    contains: list[str],
    stocks: list[str],
    with_name: bool,
    max_to_show: int,
    save_type_file: str,
    filename_to_save: Optional[str],
    group_indexes: list[int],
    move_to_group_index: Optional[int],
    move_from_group_index: Optional[int],
    copy_to_group_index: Optional[int],
    copy_from_group_index: Optional[int],
):
    """内存缓存（仅在REPL下有效）"""
    # print_locals() # DEBUG

    CONSOLE = _ctx.obj['console'] # type: console.Console
    global STOCKS, GROUPED_STOCKS, _lock

    # 1. 确定操作目标集
    targets = {idx: GROUPED_STOCKS[idx] for idx in group_indexes} if group_indexes else {None: STOCKS}

    try:
        with _lock:
            # --- 步骤 2: 执行逻辑 ---
            if action in ['show', 's']:
                _print_status(GROUPED_STOCKS, contains, CONSOLE, max_to_show, with_name)

                # 保存成文件
                if save_type_file:
                    _stocks_to_save = set()
                    if filename_to_save is None:
                        filename_to_save = f"cache_{datetime.now().strftime('%Y%m%d-%H%M%S')}"

                    # 添加后缀
                    if '.' not in filename_to_save:
                        filename_to_save += f'.{save_type_file}'

                    if group_indexes: # 可指定分组存入文件
                        for g in group_indexes:
                            _stocks_to_save.update(GROUPED_STOCKS[g])
                    else:
                        _stocks_to_save.update(STOCKS if STOCKS else [])

                    if _stocks_to_save:
                        if save_type_file == 'ebk':
                            ebk = TdxEbk
                            ebk.add_batch(_stocks_to_save)
                            ebk.save(filename_to_save) # 保存成 ebk 文件
                        elif save_type_file == 'txt':
                            # 写入txt不带 .SH/.SZ/.BJ
                            with open(filename_to_save, 'w', encoding='utf-8') as f:
                                for code in _stocks_to_save:
                                    short_code = str(code).split(".")[0]
                                    f.write(short_code + '\n')
                return

            elif action in ['add', '+']:
                for _, target_set in targets.items():
                    target_set.update(stocks)

            elif action in ['remove', '-', 'delete']:
                for _, target_set in targets.items():
                    for s in stocks:
                        target_set.discard(s) # 使用 discard 避免 keyerror

            elif action in ['clear', 'c']:
                total_cnt = sum([len(target_set) if target_set else 0 for target_set in targets.items()])
                if not click.confirm(f"❓ 当前缓存中有 {total_cnt} 只股票，是否清空？"):
                    CONSOLE.print('🔽 操作取消，并无删除任何股票。')
                    return
                for _, target_set in targets.items():
                    target_set.clear()

            # --- 步骤 3: 差集与查询 (Read-only) ---
            elif action in ['difference', 'diff', 'd']:
                # 特殊处理：差集逻辑较特殊，保持独立
                for idx, target_set in targets.items():
                    diff = STOCKS.difference(target_set) if idx is not None else STOCKS
                    CONSOLE.print(f"与分组 {idx or '缓存'} 的差集: {len(diff)} 只")
                    CONSOLE.print(Pretty(diff, max_length=max_to_show))
                return

            elif action in ['cross', 'intersection', 'intersect', 'i']:
                for idx, target_set in targets.items():
                    inter = STOCKS.intersection(target_set) if idx is not None else STOCKS
                    CONSOLE.print(f"与分组 {idx or '缓存'} 的交集: {len(inter)} 只")
                    CONSOLE.print(Pretty(inter, max_length=max_to_show))
                return

            # --- 步骤 4: 移动与复制 ---
            # 统一处理移动逻辑
            _handle_transfer(move_to_group_index, copy_to_group_index, move_from_group_index, copy_from_group_index)

            # --- 步骤 5: 统一显示逻辑 ---
            # 这里使用一个简单的函数来打印结果，避免重复代码
            _print_status(targets, contains, CONSOLE, max_to_show, with_name)

    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, callback=split_comma_stocks,
            help='指定查看某只股票的详细宽表 (例如: 688318.SH)')
@click.option('--number', '-n', 'number_n', default=0, show_default=True, type=int,
            help='显示数据的最前 N 行（负数时显示最后 N 行）')
@click.option('-fc', '--field-contain', 'field_contains', multiple=True, callback=split_comma,
            help='显示字段包含特定字符串')
@click.option('-rmf', '--remove-field', 'remove_fields', multiple=True, callback=split_comma,
            help='删除某列')
@click.option('-rnf', '--rename-field', 'rename_fields', multiple=True, callback=split_comma,
            help='重命名某列。格式：old_name:new_name')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='详细模式')
@click.option('--max-to-show', '-max', 'max_to_show', default=20, show_default=True, type=int, help='显示时的最大股票数量')
@click.option('--clean', '-clean', 'is_clean', is_flag=True, help='清空所有 DF 缓存')
@click.option('--prefix', '-p', 'prefix', help='添加到 DataFrame 时所有列都带如的前缀')
@click.pass_context
def data_frame(_ctx: click.Context,
               stocks: list[str],
               number_n: int,
               field_contains: list[str],
               remove_fields: list[str],
               rename_fields: list[str],
               verbose: bool,
               max_to_show: int,
               is_clean: bool,
               prefix: str,
):
    """显示 DataFrame 缓存状态 (STOCKS_DF 和 STOCK_2_DF)"""
    CONSOLE = _ctx.obj['console'] # type: console.Console

    print_locals(printer=CONSOLE.print)
    global STOCKS_DF, STOCK_2_DF

    def _process_df(df: pd.DataFrame, is_permanent: bool) -> pd.DataFrame:
        """
        处理 DataFrame：
        如果 is_permanent=True (用于删除/重命名)，直接在原对象上修改。
        如果 is_permanent=False (用于过滤显示)，使用 copy() 并在副本上处理。
        """
        # 如果是永久性修改，直接操作引用；否则操作副本
        if not is_permanent:
            df = df.copy()

        # 1. 永久/临时删除列 (Remove)
        if remove_fields:
            df.drop(columns=[f for f in remove_fields if f in df.columns], inplace=True, errors='ignore')

        # 2. 永久/临时重命名列 (Rename)
        if rename_fields:
            rename_map = {}
            for item in rename_fields:
                if ':' in item:
                    old, new = item.split(':', 1)
                    rename_map[old] = new
            df.rename(columns=rename_map, inplace=True)

        # 3. 添加列前缀 (Prefix) — 永久修改 STOCK_2_DF
        if prefix:
            if not all(str(c).startswith(prefix) for c in df.columns):
                df.columns = [f"{prefix}{c}" for c in df.columns]

        # 4. 临时过滤字段 (Field Contains - 仅针对显示)
        # 注意：这里我们仅在显示时过滤，不影响原始 DataFrame 的列结构
        display_df = df.copy()
        if field_contains:
            cols_to_keep = [c for c in display_df.columns if any(fc in c for fc in field_contains)]
            # 始终保留索引 (如 Date)
            idx_name = [display_df.index.name] if display_df.index.name else []
            display_df = display_df[list(set(cols_to_keep + idx_name))]

        # 5. 切片 (Slice)
        if number_n != 0:
            display_df = display_df.head(number_n) if number_n > 0 else display_df.tail(abs(number_n))

        return display_df


    with _lock:

        keys = list(STOCK_2_DF.keys())

        # 0. 检查是否清空
        if is_clean:
            total_cnt = len(keys)
            if not click.confirm(f"❓ 当前 STOCK_2_DF 缓存中有 {total_cnt} 只股票，是否清空？"):
                CONSOLE.print('🔽 操作取消，并无删除任何股票。')
                return
            STOCK_2_DF.clear()
            keys = []

        # 1. 概览核心 STOCKS_DF
        CONSOLE.print(f"\n[bold magenta]=== 核心行情 DataFrame (STOCKS_DF) ===[/bold magenta]")
        if STOCKS_DF is not None and not STOCKS_DF.empty:
            print_dataframe(_process_df(STOCKS_DF))
        else:
            CONSOLE.print("STOCKS_DF 为空。")

        # 2. 查看特定股票的详细数据 STOCK_2_DF
        target_stocks = keys if (verbose or remove_fields or rename_fields) else stocks

        if target_stocks:
            for s in target_stocks:
                matched_key = next((k for k in STOCK_2_DF if k.split('.')[0] == s.split('.')[0]), None)
                if matched_key:
                    # 1. 先进行永久性修改 (删除和重命名)
                    # 这一步直接修改 STOCK_2_DF 里的原始数据
                    _process_df(STOCK_2_DF[matched_key], is_permanent=True)

                    # 2. 再进行显示处理 (过滤和切片)
                    # 这一步返回一个用于显示的副本
                    display_df = _process_df(STOCK_2_DF[matched_key], is_permanent=False)

                    if verbose:
                        CONSOLE.print(f"\n[bold cyan]>>> 股票 {matched_key} 详情:[/bold cyan]")
                        print_dataframe(display_df, title=f'{matched_key}')
                else:
                    CONSOLE.print(f"[yellow]未找到股票 {s} 的 DataFrame 缓存。[/yellow]")
        else:
            # 3. 概览扩展缓存清单（没有指定 stocks 或没有 --verbose/-v）
            CONSOLE.print(f"\n[bold magenta]=== 股票扩展缓存清单 (STOCK_2_DF) ===[/bold magenta]")
            if keys:
                CONSOLE.print(f"当前共有 [bold]{len(keys)}[/bold] 只股票缓存：")
                CONSOLE.print(Pretty(keys, max_length=max_to_show if max_to_show else len(keys)))

                for code, df in STOCK_2_DF.items():
                    CONSOLE.print(f"（第一个数据作为展示）")
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        display_df = _process_df(df, is_permanent=False)
                        print_dataframe(display_df, title=f"股票代码：{code} 缓存的 DataFrame")
                    break # 只显示一个就足够
            else:
                CONSOLE.print("STOCK_2_DF 缓存为空。")


def _stocks_collector_v0(func):
    """
    装饰器：将被装饰函数的返回值收集到全局 STOCKS 变量中

    如果返回值是 list，则转换为 set 后合并
    如果返回值是 set，直接合并
    其他类型则直接添加
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        global STOCKS

        # 调用原函数获取返回值
        result = func(*args, **kwargs)

        # 处理返回值并合并到 STOCKS
        if isinstance(result, list):
            # list 转换为 set 后合并
            STOCKS.update(set(result))
        elif isinstance(result, set):
            # set 直接合并
            STOCKS.update(result)
        elif result:
            # 其他非空值直接添加
            STOCKS.add(result)

        return result

    return wrapper


def _generate_long_short_param(param_name :str) -> tuple[str, str]:
    """
    根据 param_name 和 group_index_param 生成 click.option 的参数列表
    """
    # 1. 构造 -- 开头的长参数
    long_param = f"--{param_name.replace('_', '-')}"
    # 2. - 开头的短参数（取短语的首字母）
    first_letters = [word[0] for word in param_name.split('_') if word]
    short_param = f"-{''.join(first_letters)}" if first_letters else None

    return long_param, short_param

def stocks_collector(
    func=None, *,
    save_memory_param='cache_stocks',
    group_index_param='stock_group_index',
    help='把查询到的结果存于内存以做后续处理（REPL有效）'
):
    """
    智能装饰器：自动处理 --save-memory 参数
    注意：
 * 被装饰函数请手动添加上 cache_stocks: bool 参数
 * 被装饰函数返回一个 dict: {'stocks': [<stock>...] }

    参数:
        save_memory_param: 参数名，默认为 'cache_stocks'

    使用方式1：无参数
        @stocks_collector
        def your_func(cache_stocks: bool,
            group_index_param: int):
            ... ...
            return {'stocks': [<stock>...] } # 直接返回带有 codes 的列表

    使用方式2：有参数
        @stocks_collector(save_memory_param='save_result')
        def your_func(save_result: bool,
            group_index_param: int):
            ... ...
            return {'stocks': [<stock>...] } # 直接返回带有 codes 的列表
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            global STOCKS, CACHE

            # DEBUG:
            # I("[stocks_collector.decorator.wrapper] ", **kwargs)

            # 检查是否需要保存到内存
            should_save = kwargs.get(save_memory_param, False)
            target_group = kwargs.get(group_index_param, False)

            # 调用原函数
            result = f(*args, **kwargs)

            if should_save and result:
                res_stocks = result.get('stocks') if isinstance(result, dict) else None

                with _lock:
                    # 分发逻辑：存入对应目标
                    if target_group is not None:
                        CACHE.update_group_stocks(target_group, res_stocks)
                    else:
                        CACHE.update_stocks(res_stocks)

            return result

        # 动态添加两个参数
        long_param, short_param = _generate_long_short_param(save_memory_param)
        f = click.option(long_param, short_param, save_memory_param, is_flag=True,
                         help='把查询到的结果存于内存')(f)
        long_param, short_param = _generate_long_short_param(group_index_param)
        f = click.option(long_param, short_param, group_index_param, type=int,
                         help='指定存入的分组索引（不填则存入默认缓存）')(f)

        return functools.update_wrapper(wrapper, f)

    return decorator(func) if func else decorator


def blocks_collector(
    func=None, *,
    save_memory_param='cache_blocks',
    group_index_param='block_group_index',
    help='把查询到的板块结果存于内存以做后续处理（REPL有效）'
):
    """
    智能装饰器：自动处理 --save-memory 参数，缓存板块代码（block_code）
    注意：
 * 被装饰函数请手动添加上 cache_stocks: bool 参数
 * 被装饰函数返回一个 dict: {'blocks': [<block_code>...] }

    参数:
        save_memory_param: 参数名，默认为 'cache_stocks'

    使用方式1：无参数
        @blocks_collector
        def your_func(cache_stocks: bool,
            group_index: int):
            ... ...
            return {'blocks': [<block_code>...] }

    使用方式2：有参数
        @blocks_collector(save_memory_param='save_result')
        def your_func(save_result: bool,
            group_index: int):
            ... ...
            return {'blocks': [<block_code>...] }
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            global BLOCKS, CACHE

            should_save = kwargs.get(save_memory_param, False)
            target_group = kwargs.get(group_index_param, False)

            result = f(*args, **kwargs)

            if should_save and result:
                res_blocks = result.get('blocks') if isinstance(result, dict) else None

                with _lock:
                    if target_group is not None:
                        CACHE.update_group_blocks(target_group, res_blocks)
                    else:
                        CACHE.update_blocks(res_blocks)

            return result

        # 动态添加两个参数
        long_param, short_param = _generate_long_short_param(save_memory_param)
        f = click.option(long_param, short_param, save_memory_param, is_flag=True,
                         help='把查询到的板块结果存于内存')(f)
        long_param, short_param = _generate_long_short_param(group_index_param)
        f = click.option(long_param, short_param, group_index_param, type=int,
                         help='指定存入的分组索引（不填则存入默认板块缓存）')(f)

        return functools.update_wrapper(wrapper, f)

    return decorator(func) if func else decorator


def df_collector(func=None, *, save_memory_param='is_save_df'):
    """处理 DataFrame 合并与清洗
    注意：
 * 被装饰函数请手动添加上 is_save_df: bool 参数
 * 被装饰函数返回一个 dict:
    {
        'df': <DataFrame>,
        'dfs': {
            <stock's code>: <DataFrame>
        }
    }
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            should_save = kwargs.get(save_memory_param, False)
            prefix = kwargs.get('prefix', None)
            result = f(*args, **kwargs)

            if should_save and result:
                if isinstance(result, dict):
                    res_df = result.get('df')
                    res_dfs = result.get('dfs')

                    if isinstance(res_df, pd.DataFrame):
                        with _lock:
                            # 1. 更新 DF 缓存
                            CACHE.update_dataframe(res_df, prefix=prefix)

                    if isinstance(res_dfs, dict) and len(result) > 0:
                        with _lock:
                            for code, df in res_dfs.items():
                                if not isinstance(df, pd.DataFrame):
                                    raise TypeError(f"df (类型为：{type(df)}），不是 DataFrame 类型")

                                # DEBUG: 检查 DataFrame 的函数
                                # click.echo(f"code={code}, len(df)={df.shape}")

                                # 1. 根据 stock 逐一更新 DFs 缓存
                                CACHE.update_dataframe_by_stock(code, df, prefix=prefix)

            return result

        # 动态添加两个参数
        f = click.option('--save-df', '-sdf', save_memory_param, is_flag=True,
                         help='缓存 DateFrame 或 stock -> DataFrame')(f)
        f = click.option('--prefix', '-df-p', 'prefix', help='添加到 DataFrame 时所有列都带如的前缀')(f)

        return functools.update_wrapper(wrapper, f)
    return decorator(func) if func else decorator


def cache_stock_name(c2n: Dict[str, str]):
    """追加个股（code -> name）"""
    global _STOCK_2_NAME
    with _lock:
        _STOCK_2_NAME.update(c2n)

def get_stock_name(code: str, default=None) -> Optional[str]:
    global _STOCK_2_NAME
    with _lock:
        return _STOCK_2_NAME.get(code, default)


def cache_st_stock_name(c2n: Dict[str, str]):
    """追加 ST 股个股"""
    global _ST_STOCK_2_NAME
    with _lock:
        _ST_STOCK_2_NAME.update(c2n)


def is_st(code: str):
    global _ST_STOCK_2_NAME
    with _lock:
        return _ST_STOCK_2_NAME.get(code) is not None


def get_st_stocks():
    global _ST_STOCK_2_NAME
    with _lock:
        return dict(_ST_STOCK_2_NAME)
