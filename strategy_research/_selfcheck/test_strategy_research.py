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
from strategy_research.run_event import (_down_limit_price, _entry_fill, _fwd_ret,
                                         _limit_price, _pool_fwd_ret,
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


class TestDownLimitPrice(unittest.TestCase):
    def test_main_board(self):
        self.assertEqual(_down_limit_price(10.0, 'SH600000'), 9.0)

    def test_gem_and_star(self):
        """创业板/科创板 20% 幅度。"""
        self.assertEqual(_down_limit_price(10.0, 'SZ300001'), 8.0)
        self.assertEqual(_down_limit_price(10.0, 'SH688001'), 8.0)

    def test_nan_prev_close(self):
        """前收盘缺失（停牌）：返回 NaN 而非抛错。"""
        self.assertTrue(np.isnan(_down_limit_price(float('nan'), 'SH600000')))
        self.assertTrue(np.isnan(_limit_price(float('nan'), 'SH600000')))


class TestEntryFill(unittest.TestCase):
    """_entry_fill：入场变体的买入价与有效掩码（事件日 D = idx 1，D-1 = idx 0）。"""
    IDX = pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08'])
    # D-1 涨停日（9.5 → 10.45）；D 倍量阴（10.6 → 10.3）；D+1 低开回升（low 9.9）
    OPEN = pd.DataFrame({'A': [9.5, 10.6, 10.4, 11.0, 11.5]}, index=IDX)
    CLOSE = pd.DataFrame({'A': [10.45, 10.3, 10.6, 11.2, 11.8]}, index=IDX)
    LOW = pd.DataFrame({'A': [9.4, 10.2, 9.9, 10.9, 11.4]}, index=IDX)
    POS = np.array([1])
    COLS = np.array([0])
    CODES = np.array(['SH600000'])

    def _fill(self, entry, open_df=None, close_df=None, low_df=None):
        return _entry_fill(entry,
                           open_df if open_df is not None else self.OPEN,
                           close_df if close_df is not None else self.CLOSE,
                           low_df if low_df is not None else self.LOW,
                           self.POS, self.COLS, self.CODES)

    def test_d1_open(self):
        price, valid, hit = self._fill('d1_open')
        self.assertAlmostEqual(price[0], 10.4, places=9)
        self.assertTrue(valid[0])
        self.assertFalse(hit[0])

    def test_d_close(self):
        price, valid, _ = self._fill('d_close')
        self.assertAlmostEqual(price[0], 10.3, places=9)
        self.assertTrue(valid[0])

    def test_d1_close(self):
        price, valid, _ = self._fill('d1_close')
        self.assertAlmostEqual(price[0], 10.6, places=9)
        self.assertTrue(valid[0])

    def test_d1_dip_hit(self):
        """D+1 盘中触及涨停 K 线实体中分价 (9.5+10.45)/2=9.975（low1=9.9）→ 按中分价成交。"""
        price, valid, hit = self._fill('d1_dip')
        self.assertAlmostEqual(price[0], 9.975, places=9)
        self.assertTrue(valid[0])
        self.assertTrue(hit[0])

    def test_d1_dip_miss(self):
        """D+1 最低 10.05 > 中分价：未触及 → 不成交。"""
        low = self.LOW.copy()
        low.iloc[2, 0] = 10.05
        _, valid, hit = self._fill('d1_dip', low_df=low)
        self.assertFalse(valid[0])
        self.assertFalse(hit[0])

    def test_d1_dip_gap_open(self):
        """D+1 开盘跳空低于中分价（9.8 < 9.975）：按开盘价成交。"""
        opn = self.OPEN.copy()
        low = self.LOW.copy()
        opn.iloc[2, 0] = 9.8
        low.iloc[2, 0] = 9.7
        price, valid, _ = self._fill('d1_dip', open_df=opn, low_df=low)
        self.assertAlmostEqual(price[0], 9.8, places=9)
        self.assertTrue(valid[0])

    def test_limit_up_excluded(self):
        """D+1 一字涨停（open = 涨停价 10.3×1.1=11.33）：d1_open/d1_close 均不成交。"""
        opn = self.OPEN.copy()
        cls = self.CLOSE.copy()
        opn.iloc[2, 0] = 11.33
        cls.iloc[2, 0] = 11.33
        _, valid_open, _ = self._fill('d1_open', open_df=opn, close_df=cls)
        _, valid_close, _ = self._fill('d1_close', open_df=opn, close_df=cls)
        self.assertFalse(valid_open[0])
        self.assertFalse(valid_close[0])

    def test_unknown_entry(self):
        with self.assertRaises(ValueError):
            self._fill('bad_entry')


class TestFwdRet(unittest.TestCase):
    """_fwd_ret：买入日后第 n 个交易日收盘卖出的逐事件收益 + 卖端跌停剔除。"""
    IDX = pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08'])
    CLOSE = pd.DataFrame({'A': [10.45, 10.3, 10.6, 11.2, 11.8]}, index=IDX)
    POS = np.array([1])
    COLS = np.array([0])
    CODES = np.array(['SH600000'])
    PRICE = np.array([10.4])      # d1_open 口径买入价

    def _ret(self, n, buy_offset=1, close_df=None):
        return _fwd_ret(close_df if close_df is not None else self.CLOSE,
                        self.PRICE, self.POS, self.COLS,
                        self.CODES, n, buy_offset)

    def test_d1_open_n1_sells_next_day(self):
        """n=1 且买入日 = D+1：卖出日 = D+2（idx 3 收盘 11.2），不再同日回转。"""
        self.assertAlmostEqual(self._ret(1)[0], 11.2 / 10.4 - 1, places=9)

    def test_d_close_n1(self):
        """d_close 口径（buy_offset=0）n=1：D 收盘 10.3 → D+1 收盘 10.6。"""
        r = _fwd_ret(self.CLOSE, np.array([10.3]), self.POS, self.COLS,
                     self.CODES, 1, buy_offset=0)
        self.assertAlmostEqual(r[0], 10.6 / 10.3 - 1, places=9)

    def test_sell_day_down_limit_excluded(self):
        """卖出日收盘 = 跌停价（10.6×0.9=9.54）：封跌停卖不出 → 剔除。"""
        cls = self.CLOSE.copy()
        cls.iloc[3, 0] = 9.54
        self.assertTrue(np.isnan(self._ret(1, close_df=cls)[0]))

    def test_sell_day_above_down_limit_kept(self):
        """卖出日收盘高于跌停价（9.55，仅高 1 分）：正常计入。"""
        cls = self.CLOSE.copy()
        cls.iloc[3, 0] = 9.55
        self.assertAlmostEqual(self._ret(1, close_df=cls)[0], 9.55 / 10.4 - 1, places=9)

    def test_extreme_ratio_filtered(self):
        """|ret| > 10 倍记 NaN：前复权假收益视为噪声。"""
        cls = self.CLOSE.copy()
        cls.iloc[3, 0] = 1000.0
        self.assertTrue(np.isnan(self._ret(1, close_df=cls)[0]))


class TestPoolFwdRet(unittest.TestCase):
    """_pool_fwd_ret：全池同口径收益矩阵（基准用）。"""
    IDX = pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08'])
    OPEN = pd.DataFrame({'A': [9.5, 10.6, 10.4, 11.0, 11.5]}, index=IDX)
    CLOSE = pd.DataFrame({'A': [10.45, 10.3, 10.6, 11.2, 11.8]}, index=IDX)
    LOW = pd.DataFrame({'A': [9.4, 10.2, 9.9, 10.9, 11.4]}, index=IDX)

    def test_d1_open_n1(self):
        """行 idx1（事件日 D）：close(D+2)/open(D+1)-1 = 11.2/10.4-1。"""
        r = _pool_fwd_ret('d1_open', self.OPEN, self.CLOSE, self.LOW, 1)
        self.assertAlmostEqual(r.loc[self.IDX[1], 'A'], 11.2 / 10.4 - 1, places=9)

    def test_d1_dip_hit(self):
        """行 idx1：低吸触及 → 按中分价 9.975 成交。"""
        r = _pool_fwd_ret('d1_dip', self.OPEN, self.CLOSE, self.LOW, 1)
        self.assertAlmostEqual(r.loc[self.IDX[1], 'A'], 11.2 / 9.975 - 1, places=9)

    def test_d1_dip_miss_is_nan(self):
        """D+1 未触及中分价：无成交价 → NaN。"""
        low = self.LOW.copy()
        low.iloc[2, 0] = 10.05
        r = _pool_fwd_ret('d1_dip', self.OPEN, self.CLOSE, low, 1)
        self.assertTrue(np.isnan(r.loc[self.IDX[1], 'A']))

    def test_unknown_entry(self):
        with self.assertRaises(ValueError):
            _pool_fwd_ret('bad_entry', self.OPEN, self.CLOSE, self.LOW, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
