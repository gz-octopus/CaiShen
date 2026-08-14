# -*- coding: utf-8 -*-
"""数据就绪校验（T1 验收条目 2，两项任一不过拒绝回测）。

校验 1：tdxw.exe 进程在（权息接口与数据更新依赖通达信客户端）
校验 2：权息表非空 + 抽样 3~5 只 get_weight() 条数/最近权息日与 tqcenter 源比对

不校验日线尾部日期（用户决定，T1 定稿剔除）。
"""
from __future__ import annotations

import configparser
import subprocess
import sys
from pathlib import Path

import pandas as pd

from difoss_stock_util import E, I, P, W

# 通达信金融量化测试版 PYPlugins（tdxquant tqcenter 直取；T4 票负责正式适配）
TDX_PYPLUGINS_DIRS = [r'D:\new_tdx_tet\PYPlugins\user', r'D:\new_tdx_tet\PYPlugins']

# 权息抽样比对样本（固定列表，保证验收可复现）
SAMPLE_STOCKS = ['sh600000', 'sz000001', 'sh601318', 'sz300750', 'sh600519']


def check_tdxw_running() -> bool:
    """校验 1：tdxw.exe 进程是否在（tasklist 系统命令）。"""
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq tdxw.exe'],
                             capture_output=True, text=True, timeout=30)
        running = 'tdxw.exe' in out.stdout
    except Exception:
        running = False
    if running:
        I('就绪校验 1/2 通过：tdxw.exe 进程在')
    else:
        E('就绪校验 1/2 失败：tdxw.exe 进程不存在，请先打开通达信客户端')
    return running


def _get_stock_db_path(ini_path: Path) -> Path:
    """从 hikyuu.ini 的 [baseinfo] db 解析 stock.db 路径。"""
    parser = configparser.ConfigParser()
    parser.read(ini_path, encoding='utf-8')
    return Path(parser.get('baseinfo', 'db'))


def _query_tq_divid_factors(code: str) -> pd.DataFrame:
    """经 tqcenter 直取客户端权息（需 tdxw.exe 运行）。

    返回 DataFrame 与 tq.get_divid_factors 一致，Type=15 已剔除
    （导入侧跳过 Type=15，比对口径须一致，见 T2 SOP ④）。
    """
    for p in TDX_PYPLUGINS_DIRS:
        if p not in sys.path:
            sys.path.insert(0, p)
    from tqcenter import tq

    code_dot = f'{code[2:]}.{code[:2].upper()}'
    try:
        tq.initialize(__file__)
        df = tq.get_divid_factors(stock_code=code_dot, start_time='', end_time='')
        if df is not None and len(df) > 0 and 'Type' in df.columns:
            df = df[df['Type'] != 15]
        return df if df is not None else pd.DataFrame()
    finally:
        try:
            tq.close()
        except Exception:
            pass


def check_weight_ready(ini_path: Path, samples: list[str] | None = None,
                       print_table: bool = True) -> bool:
    """校验 2：权息表非空 + 抽样比对（条数 + 最近权息日）。

    高危背景（T2 风险 3）：权息表为空时 hikyuu 静默用未复权价、无任何报错，
    因此该项必须通过才允许回测。
    """
    if samples is None:
        samples = SAMPLE_STOCKS
    db_path = _get_stock_db_path(ini_path)

    # 权息表非空是前置门槛：空表时 hikyuu 静默用未复权价
    import sqlite3
    con = sqlite3.connect(str(db_path))
    try:
        count = con.execute('select count(*) from stkWeight').fetchone()[0]
    except sqlite3.OperationalError as e:
        E(f'就绪校验 2/2 失败：stkWeight 表不存在或不可读（{e}）')
        return False
    finally:
        con.close()
    if count == 0:
        E('就绪校验 2/2 失败：权息表为空（hikyuu 将静默使用未复权价，禁止回测）')
        return False

    # 抽样比对：hikyuu 权息表与 tqcenter 源数据须条数/最近权息日一致
    import hikyuu as hku
    rows = []
    ok = True
    for code in samples:
        stk = hku.sm[code]
        weights = stk.get_weight()
        hk_count = len(weights)
        hk_last = str(weights[-1].datetime.date()) if hk_count else '-'
        try:
            df = _query_tq_divid_factors(code)
            tq_count = len(df)
            tq_last = str(df.index.max().date()) if tq_count else '-'
        except Exception as e:
            W(f'{code} tqcenter 查询失败（{e}），该项无法比对，记为不一致')
            tq_count, tq_last = None, None
        match = (hk_count == tq_count) and (hk_last == tq_last)
        if not match:
            ok = False
        rows.append({'代码': code, 'hikyuu条数': hk_count, 'tq条数': tq_count,
                     'hikyuu最近权息日': hk_last, 'tq最近权息日': tq_last, '一致': '√' if match else '×'})

    if print_table:
        from difoss_stock_util import print_dataframe
        print_dataframe(pd.DataFrame(rows))
    if ok:
        I(f'就绪校验 2/2 通过：权息表 {count} 条非空，抽样 {len(samples)} 只条数/最近权息日全部一致')
    else:
        E('就绪校验 2/2 失败：抽样比对不一致，请重跑权息导入（见 T2 SOP ④）')
    return ok


def run_check(ini_path: Path | None = None, print_table: bool = True) -> bool:
    """执行全部就绪校验，返回是否通过（任一不过拒绝回测）。"""
    from . import config as cfg_mod

    P('====== 数据就绪校验（T1 两项） ======')
    if ini_path is None:
        # 必须先初始化 StockManager（包内 hikyuu.ini），否则 get_weight() 走默认配置读不到权息
        ini_path = cfg_mod.init_hikyuu().ini_path
    ok1 = check_tdxw_running()
    ok2 = check_weight_ready(ini_path, print_table=print_table) if ok1 else False
    if ok1 and ok2:
        I('数据就绪校验全部通过，可以回测')
        return True
    E('数据就绪校验未通过，拒绝回测')
    return False
