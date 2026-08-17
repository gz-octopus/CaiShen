# -*- coding: utf-8 -*-
"""strategy_research 自算指标纯函数单测（回撤边角 case + 事件研究纯函数）。

运行：python strategy_research/_selfcheck/test_strategy_research.py
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

# 仓库根加入 sys.path（本文件在 strategy_research/_selfcheck/ 下，需上溯三级）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from strategy_research.report import calc_max_drawdown, calc_sharpe
from strategy_research.run_event import (_fwd_window_returns, _limit_price,
                                         _round_half_up, _t_stat)


class TestCalcSharpe(unittest.TestCase):
    def test_zero_std_returns_zero(self):
        """资金曲线恒不变（全程空仓）：std=0，夏普应为 0。"""
        self.assertEqual(calc_sharpe([0.0] * 100), 0.0)

    def test_positive_returns(self):
        """每日 +0.1% 恒定：std=0（无波动）→ 夏普 0（分母为零保护）。"""
        r = [0.001] * 252
        self.assertEqual(calc_sharpe(r), 0.0)

    def test_alternating_returns(self):
        """交替 +1%/-1%：mean=0 → 夏普 0。"""
        r = [0.01, -0.01] * 126
        self.assertAlmostEqual(calc_sharpe(r), 0.0, places=12)

    def test_known_value(self):
        """手工验证：日收益 [0.01, 0.02, 0.03]，样本 std。"""
        r = [0.01, 0.02, 0.03]
        mean = sum(r) / 3
        std = math.sqrt(sum((x - mean) ** 2 for x in r) / 2)  # ddof=1
        expected = mean / std * math.sqrt(252)
        self.assertAlmostEqual(calc_sharpe(r), expected, places=12)

    def test_nan_filtered(self):
        """含 NaN 的序列：NaN 剔除后计算，不报错。"""
        r = [0.01, float('nan'), 0.02, 0.03]
        self.assertTrue(math.isfinite(calc_sharpe(r)))

    def test_short_series(self):
        """少于 2 个有效值：返回 0。"""
        self.assertEqual(calc_sharpe([0.01]), 0.0)
        self.assertEqual(calc_sharpe([]), 0.0)


class TestCalcMaxDrawdown(unittest.TestCase):
    def test_flat_series(self):
        """全程空仓（资金不变）：回撤 0。"""
        self.assertEqual(calc_max_drawdown([100] * 50), 0.0)

    def test_single_day_crash(self):
        """单日暴跌：峰值 100 → 90，回撤 10%。"""
        self.assertAlmostEqual(calc_max_drawdown([100, 90]), 10.0, places=9)

    def test_peak_then_recovery(self):
        """先涨到 120 再跌回 100：最大回撤 (120-100)/120 = 16.67%。"""
        values = [100, 110, 120, 115, 100, 105]
        self.assertAlmostEqual(calc_max_drawdown(values), 20 / 120 * 100, places=9)

    def test_new_high_resets_peak(self):
        """创新高后回撤从新峰值计算：130 → 117 → 10%。"""
        values = [100, 130, 117]
        self.assertAlmostEqual(calc_max_drawdown(values), 13 / 130 * 100, places=9)

    def test_two_drawdowns_take_max(self):
        """两段回撤取最大：先 -5% 再 -15%。"""
        values = [100, 95, 100, 85]
        self.assertAlmostEqual(calc_max_drawdown(values), 15.0, places=9)

    def test_flat_segment_inside(self):
        """空仓段（持平）穿插：不影响峰值跟踪。"""
        values = [100, 100, 100, 90, 90, 90, 80]
        self.assertAlmostEqual(calc_max_drawdown(values), 20.0, places=9)

    def test_empty_and_nan(self):
        self.assertEqual(calc_max_drawdown([]), 0.0)
        self.assertAlmostEqual(calc_max_drawdown([100, float('nan'), 90]), 10.0, places=9)


class TestRoundHalfUp(unittest.TestCase):
    def test_round_up(self):
        self.assertEqual(_round_half_up(10.556), 10.56)

    def test_round_down(self):
        self.assertEqual(_round_half_up(10.554), 10.55)

    def test_half_up_not_bankers(self):
        """四舍五入而非银行家舍入：11.605 应进位到 11.61。"""
        self.assertEqual(_round_half_up(11.605), 11.61)


class TestLimitPrice(unittest.TestCase):
    def test_main_board(self):
        self.assertEqual(_limit_price(10.0, 'SH600000'), 11.0)

    def test_gem_and_star(self):
        """创业板/科创板 20% 幅度。"""
        self.assertEqual(_limit_price(10.0, 'SZ300001'), 12.0)
        self.assertEqual(_limit_price(10.0, 'SH688001'), 12.0)

    def test_rounding(self):
        self.assertEqual(_limit_price(10.55, 'SH600000'), 11.61)  # 11.605 → 11.61


class TestTStat(unittest.TestCase):
    def test_known_value(self):
        """[0.01, 0.02, 0.03]：mean=0.02, std=0.01, t = 0.02/(0.01/√3)。"""
        expected = 0.02 / (0.01 / math.sqrt(3))
        self.assertAlmostEqual(_t_stat(np.array([0.01, 0.02, 0.03])), expected, places=9)

    def test_nan_filtered(self):
        """含 NaN：剔除后计算，不报错。"""
        self.assertTrue(math.isfinite(
            _t_stat(np.array([0.01, float('nan'), 0.02, 0.03]))))

    def test_short_series(self):
        self.assertEqual(_t_stat(np.array([0.01])), 0.0)
        self.assertEqual(_t_stat(np.array([])), 0.0)

    def test_zero_variance(self):
        self.assertEqual(_t_stat(np.array([0.01, 0.01, 0.01])), 0.0)


class TestFwdWindowReturns(unittest.TestCase):
    """_fwd_window_returns 的 shift 语义：行 D 的值 = close(D+n)/open(D+1) - 1。"""
    IDX = pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08'])
    OPEN = pd.DataFrame({'A': [10.0, 10.5, 11.0, 11.5, 12.0],
                         'B': [20.0, 21.0, 22.0, 23.0, 24.0]}, index=IDX)
    CLOSE = pd.DataFrame({'A': [10.4, 10.9, 11.4, 11.9, 12.4],
                          'B': [20.8, 21.8, 22.8, 23.8, 24.8]}, index=IDX)

    def test_window_1(self):
        r = _fwd_window_returns(self.OPEN, self.CLOSE, 1)
        # D=01-02：close(01-03)/open(01-03)-1
        self.assertAlmostEqual(r.loc[self.IDX[0], 'A'], 10.9 / 10.5 - 1, places=12)
        # 最后一行为 NaN（无 D+1）
        self.assertTrue(np.isnan(r.iloc[-1, 0]))

    def test_window_3(self):
        r = _fwd_window_returns(self.OPEN, self.CLOSE, 3)
        # D=01-02：close(01-05)/open(01-03)-1；D=01-03：close(01-08)/open(01-04)-1
        self.assertAlmostEqual(r.loc[self.IDX[0], 'A'], 11.9 / 10.5 - 1, places=12)
        self.assertAlmostEqual(r.loc[self.IDX[1], 'B'], 24.8 / 22.0 - 1, places=12)

    def test_extreme_ratio_filtered(self):
        """窗口收益 |ret| > 10 倍记 NaN：前复权价穿越 0 的天文数字假收益视为噪声。"""
        o = self.OPEN.copy()
        c = self.CLOSE.copy()
        c.iloc[1, 0] = 1000.0      # A 股 01-03 收盘 1000：窗口 1 收益约 94 倍
        r = _fwd_window_returns(o, c, 1)
        self.assertTrue(np.isnan(r.loc[self.IDX[0], 'A']))
        # 正常样本不受影响
        self.assertAlmostEqual(r.loc[self.IDX[0], 'B'], 21.8 / 21.0 - 1, places=12)


if __name__ == '__main__':
    unittest.main(verbosity=2)
