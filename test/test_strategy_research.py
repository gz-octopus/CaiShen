# -*- coding: utf-8 -*-
"""strategy_research 自算指标纯函数单测（T5 落地约束：回撤边角 case 覆盖）。

运行：python test/test_strategy_research.py
"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy_research.report import calc_max_drawdown, calc_sharpe


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
