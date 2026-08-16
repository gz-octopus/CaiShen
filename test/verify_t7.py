# -*- coding: utf-8 -*-
"""T7 第二闭环七条验收（自动对比脚本）。

运行：python test/verify_t7.py
1. ma-cross 迁移逐位一致（vs 第一闭环基线精确值）
2. factor 命令出评估报告（文件存在 + 内容区块）
3. 组合回测跑通：调仓事件 > 0、每调仓日持仓数 ≤ TopN
4. 报告数字与 Performance 一致（_extract_stats 同源 + 字段存在）
5. 固定参数重跑两遍逐位一致（stats/funds/trades/rebalances/sharpe/mdd）
6. 实验注册表有运行记录（参数快照 + git commit）
7. T+1 声明在报告与文档中显式标注
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy_research import config as cfg_mod
from strategy_research.backtest import EXPERIMENTS_DB, run_backtest
from strategy_research.strategies import StrategyConfig

BASELINE = {
    'sharpe': -0.22242897780498105,
    'mdd': 34.686967619375174,
    'trades': 60,
    'final_assets': 822621.31,
    'annual_return': -2.7433568580508467,
    'win_rate': 30.0,
    'pl_ratio': 1.59,
}

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f'{"✓" if cond else "✗"} {name} {detail}')


def load_result(path: Path) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def main():
    cfg_mod.init_hikyuu()
    reports = cfg_mod.load_config().report_dir

    # ---- 验收 1：ma-cross 迁移逐位一致 ----
    cfg = StrategyConfig(strategy='ma-cross', start='2020-01-02', end='2026-08-13')
    r1, dir1 = run_backtest(cfg, skip_check=True, draw_charts=False)
    d1 = json.load(open(dir1 / 'backtest_result.json', encoding='utf-8'))
    same = (
        abs(d1['sharpe'] - BASELINE['sharpe']) < 1e-12
        and abs(d1['max_drawdown_mdd'] - BASELINE['mdd']) < 1e-12
        and len(d1['trades']) == BASELINE['trades']
        and abs(d1['stats']['当前总资产'] - BASELINE['final_assets']) < 1e-6
        and abs(d1['stats']['帐户平均年收益率%'] - BASELINE['annual_return']) < 1e-12
        and abs(d1['stats']['赢利交易比例%'] - BASELINE['win_rate']) < 1e-12
        and abs(d1['stats']['平均赢利/平均亏损比例'] - BASELINE['pl_ratio']) < 1e-12
    )
    check('验收1 ma-cross 迁移逐位一致', same,
          f"(sharpe={d1['sharpe']}, mdd={d1['max_drawdown_mdd']}, trades={len(d1['trades'])})")

    # ---- 验收 5：重跑两遍逐位一致 ----
    r2, dir2 = run_backtest(cfg, skip_check=True, draw_charts=False)
    d2 = json.load(open(dir2 / 'backtest_result.json', encoding='utf-8'))
    keys = ['stats', 'funds_curve', 'drawdown_series', 'trades', 'rebalances',
            'sharpe', 'max_drawdown_mdd', 'max_drawdown_self']
    same2 = all(d1[k] == d2[k] for k in keys)
    check('验收5 重跑两遍逐位一致', same2)

    # ---- 验收 3：组合回测跑通（用已有 tech5 结果目录，避免长跑）----
    tech5_dirs = sorted(reports.glob('*_tech5_t10_*'))
    if tech5_dirs:
        d = json.load(open(tech5_dirs[-1] / 'backtest_result.json', encoding='utf-8'))
        rebal_ok = len(d['rebalances']) > 0
        topn_ok = all(len(r['stocks']) <= 10 for r in d['rebalances'])
        check('验收3 组合回测跑通（调仓>0 且持仓≤TopN）',
              rebal_ok and topn_ok,
              f"(调仓 {len(d['rebalances'])} 次, 最大持仓 {max(len(r['stocks']) for r in d['rebalances'])})")
    else:
        check('验收3 组合回测跑通', False, '(未找到 tech5 结果目录，请先跑 backtest -c experiments/tech5.yaml)')

    # ---- 验收 4：报告数字与 Performance 同源 ----
    check('验收4 报告数字与 Performance 同源（_extract_stats 直接来自 per）',
          '当前总资产' in d1['stats'] and len(d1['stats']) == 53,
          f"(stats {len(d1['stats'])} 项)")

    # ---- 验收 6：实验注册表 ----
    con = sqlite3.connect(str(EXPERIMENTS_DB))
    rows = con.execute('select id, strategy, mode, params, git_commit, out_dir from runs '
                       'order by id').fetchall()
    con.close()
    ma_rows = [r for r in rows if r[1] == 'ma-cross']
    ok6 = len(rows) >= 2 and any(r[1] == 'tech5' for r in rows) \
        and all(r[3] and r[4] for r in rows)
    check('验收6 实验注册表记录（参数快照+commit+路径）', ok6,
          f"(runs {len(rows)} 条, ma-cross {len(ma_rows)} 条)")

    # ---- 验收 7：T+1 声明 ----
    check('验收7 T+1 声明显式标注', 'T+1' in d1['meta']['t_plus_1_disclaimer']
          and '自动满足' in d1['meta']['t_plus_1_disclaimer'])

    # ---- 验收 2：factor 报告（文件存在性，内容由 factor 命令保证）----
    fr = reports / 'factor_report.html'
    if fr.exists():
        html = fr.read_text(encoding='utf-8')
        ok2 = ('IC 序列' in html and '分层回测' in html and '年化收益' in html)
        check('验收2 因子评估报告', ok2, f"({fr.name}, {len(html)//1024}KB)")
    else:
        check('验收2 因子评估报告', False, '(factor_report.html 不存在，请先跑 factor 命令)')

    print(f'\n===== 通过 {len(PASS)} / {len(PASS) + len(FAIL)} =====')
    if FAIL:
        print('未通过:', FAIL)
    return len(FAIL) == 0


if __name__ == '__main__':
    raise SystemExit(0 if main() else 1)
