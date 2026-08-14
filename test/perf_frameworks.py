# -*- coding: utf-8 -*-
"""三框架性能对比：sh000001 MA(10)/MA(30) 金叉择时。

数据源：通达信 vipdoc 直读（struct 解析 .day，纯 Python 读文件）；
同一份 pandas DataFrame 喂 Backtrader / vectorbt / hikyuu 三框架，
hikyuu 额外计时其原生 KData 直读路径（TdxKDataDriver + 预载）。

口径说明（如实标注）：
- 本测试只比计算速度，不复权（复权口径见第一闭环，不在此范围）；
- 三框架并行模型不同：hikyuu=C++ 内核+直读、vectorbt=numpy 矩阵向量化、
  Backtrader=纯 Python 事件循环，结果差距即框架本质差异；
- 多标的场景：hikyuu 循环 SYS.run；vectorbt 矩阵一次算；
  Backtrader 单 Cerebro 多 data feed（每标的自动一个策略实例）。

用法：
    python test/perf_frameworks.py              # 默认 3 档规模：1 / 100 / 500 只
    python test/perf_frameworks.py --full       # 追加全市场 9700 只（Backtrader 很慢，慎用）
"""
from __future__ import annotations

import glob
import os
import struct
import sys
import time
from pathlib import Path

import click
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VPD = r'D:\TDX\vipdoc'
CONTEXT_SETTINGS = {'help_option_names': ['-?', '--help', '-h']}
REPEAT = 3          # 每项计时重复次数（取中位数）
MA_FAST, MA_SLOW = 10, 30


# ---------------------------------------------------------------- 数据读取

def read_day_file(path: str) -> pd.DataFrame:
    """通达信 .day 文件 → DataFrame。

    记录格式（32 字节/条，小端）：date uint32 + OHLC uint32×4（价格×100 定点）
    + amount float32 + volume uint32 + 保留 uint32。逐条 iter_unpack 解包。
    """
    with open(path, 'rb') as f:
        raw = f.read()
    n = len(raw) // 32
    rec = struct.iter_unpack('<IIIIIfII', raw[: n * 32])
    dates, opens, highs, lows, closes, amounts, vols, _ = zip(*rec)
    df = pd.DataFrame({
        'date': pd.to_datetime([str(d) for d in dates], format='%Y%m%d'),
        'open': [p / 100.0 for p in opens],
        'high': [p / 100.0 for p in highs],
        'low': [p / 100.0 for p in lows],
        'close': [p / 100.0 for p in closes],
        'volume': vols,
        'amount': amounts,
    })
    return df.set_index('date')


def load_vipdoc(n_stocks: int) -> dict[str, pd.DataFrame]:
    """vipdoc 直读 n 只（sh000001 优先 + 其余按 sh 市场文件名序）。

    只选股票+指数（排除 5/11/12 开头的债券基金等，它们的日期区间与股票不一致）；
    过滤起点晚于 2020-01-10 的标的（新股），保证各标的同区间对齐。
    """
    files = sorted(glob.glob(os.path.join(VPD, 'sh', 'lday', 'sh*.day')))
    files = [f for f in files
             if os.path.basename(f) == 'sh000001.day' or os.path.basename(f)[2:3] == '6']
    files.sort(key=lambda f: '000001' not in f)  # sh000001 排最前
    out = {}
    for f in files:
        code = os.path.basename(f)[2:-4]
        df = read_day_file(f)
        # 对齐区间：2020-01-02 起（与第一闭环一致）
        df = df[df.index >= pd.Timestamp('2020-01-02')]
        if len(df) < 100 or df.index.min() > pd.Timestamp('2020-01-10'):
            continue
        out[f'sh{code}'] = df
        if len(out) >= n_stocks:
            break
    return out


def to_wide(data: dict[str, pd.DataFrame], col: str) -> pd.DataFrame:
    """多标的字典 → 宽表（列=标的，inner join 取公共交易日交集）。"""
    return pd.concat({c: d[col] for c, d in data.items()}, axis=1, join='inner')


# ---------------------------------------------------------------- 计时工具

def timeit(fn, repeat: int = REPEAT) -> float:
    ts = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return sorted(ts)[len(ts) // 2]


# ---------------------------------------------------------------- Backtrader

def run_backtrader(close: pd.DataFrame) -> None:
    import backtrader as bt

    class MACross(bt.Strategy):
        def __init__(self):
            self.ma_fast = bt.ind.SMA(self.data.close, period=MA_FAST)
            self.ma_slow = bt.ind.SMA(self.data.close, period=MA_SLOW)
            self.cross = bt.ind.CrossOver(self.ma_fast, self.ma_slow)

        def next(self):
            if self.cross > 0:
                self.buy()
            elif self.cross < 0:
                self.close()

    cerebro = bt.Cerebro(stdstats=False)
    for code in close.columns:
        df = pd.DataFrame({
            'open': close[code], 'high': close[code], 'low': close[code],
            'close': close[code], 'volume': close[code] * 0 + 1.0,
        })
        cerebro.adddata(bt.feeds.PandasData(dataname=df), name=code)
    cerebro.addstrategy(MACross)
    cerebro.broker.setcash(1_000_000)
    cerebro.run()


# ---------------------------------------------------------------- vectorbt

def run_vectorbt(close: pd.DataFrame) -> None:
    import vectorbt as vbt

    ma_fast = vbt.MA.run(close, window=MA_FAST).ma
    ma_slow = vbt.MA.run(close, window=MA_SLOW).ma
    entries = ma_fast.vbt.crossed_above(ma_slow)
    exits = ma_fast.vbt.crossed_below(ma_slow)
    vbt.Portfolio.from_signals(
        close=close, entries=entries, exits=exits,
        init_cash=1_000_000, freq='D',
    )


# ---------------------------------------------------------------- hikyuu

def run_hikyuu(close: pd.DataFrame, preloaded: bool = True) -> None:
    import hikyuu as hku
    from strategy_research.strategy import create_system

    for code in close.columns:
        stk = hku.sm[code]
        q = hku.Query(hku.Datetime(2020, 1, 2), hku.Datetime(2026, 8, 14),
                      hku.Query.DAY, recover_type=hku.Query.FORWARD)
        tm = hku.crtTM(date=hku.Datetime(2020, 1, 2), init_cash=1_000_000,
                       cost_func=hku.TC_FixedA2017(), name=f't_{code}')
        sys_ = create_system(tm)
        sys_.run(stk, q)


# ---------------------------------------------------------------- 主流程

def bench_scale(n: int, full: bool = False) -> list[dict]:
    from rich.table import Table
    from rich.console import Console

    console = Console()

    # 阶段 0：数据读取（通达信 vipdoc 直读）
    t_load = timeit(lambda: load_vipdoc(n))
    data = load_vipdoc(n)
    close = to_wide(data, 'close')
    console.print(f'[bold]== 规模：{n} 只 × {len(close)} 根（vipdoc 直读 {t_load:.3f}s） ==[/bold]')

    rows = []
    rows.append({'框架': '数据读取(vipdoc 直读)', '耗时(s)': t_load, '备注': '纯 Python struct 解析'})

    # Backtrader
    t = timeit(lambda: run_backtrader(close))
    rows.append({'框架': 'Backtrader', '耗时(s)': t, '备注': '单 Cerebro 多 data，事件循环'})

    # vectorbt
    t = timeit(lambda: run_vectorbt(close))
    rows.append({'框架': 'vectorbt', '耗时(s)': t, '备注': 'numpy 矩阵向量化'})

    # hikyuu（含 KData 查询；预载已由 load_hikyuu 完成）
    t = timeit(lambda: run_hikyuu(close))
    rows.append({'框架': 'hikyuu', '耗时(s)': t, '备注': 'C++ 内核，KData 直读+System 回测'})

    table = Table(title=f'{n} 只标的')
    table.add_column('框架', style='cyan')
    table.add_column('中位耗时 (s)', justify='right')
    table.add_column('备注', style='dim')
    for r in rows:
        table.add_row(r['框架'], f"{r['耗时(s)']:.4f}", r['备注'])
    console.print(table)
    return rows


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('--full', is_flag=True, help='追加全市场 9700 只规模（Backtrader 很慢，慎用）')
def main(full: bool):
    """三框架性能对比：通达信数据 → Backtrader / vectorbt / hikyuu 跑 MA(10)/MA(30) 金叉。"""
    import matplotlib
    matplotlib.use('Agg')

    from strategy_research import config as cfg_mod
    t0 = time.perf_counter()
    cfg_mod.init_hikyuu()
    print(f'hikyuu 初始化（含全市场预载）: {time.perf_counter() - t0:.2f}s')

    all_rows = []
    for n in (1, 100, 500):
        all_rows.extend(bench_scale(n))
    if full:
        all_rows.extend(bench_scale(9700))

    # 汇总对比表
    summary = pd.DataFrame(all_rows)
    print('\n===== 汇总（各规模中位耗时，秒） =====')
    for n in (['1', '100', '500'] + (['9700'] if full else [])):
        pass
    print(summary.to_string(index=False))


if __name__ == '__main__':
    main()
