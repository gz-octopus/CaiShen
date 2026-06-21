import unittest
from datetime import datetime, date, time, timedelta
from functools import lru_cache
from unittest.mock import patch, MagicMock
import pandas as pd

from difoss_stock_util.stock_util import TradingInfo

class TestTradingInfo(unittest.TestCase):

    def setUp(self):
        """测试前的设置"""
        self.now = datetime(2026, 3, 15, 10, 0, 0)  # 假设的当前时间

    def test_init_with_valid_period(self):
        """测试使用有效周期初始化"""
        trading_info = TradingInfo(period='1d')
        self.assertEqual(trading_info.period, '1d')
        self.assertIsNone(trading_info.start_time)
        self.assertIsNone(trading_info.end_time)
        self.assertIsNone(trading_info.count)

    def test_init_with_invalid_period(self):
        """测试使用无效周期初始化应该抛出异常"""
        with self.assertRaises(ValueError):
            TradingInfo(period='invalid')

    def test_init_with_string_times(self):
        """测试使用字符串时间初始化"""
        start_str = "2026-03-01"
        end_str = "2026-03-10"
        trading_info = TradingInfo(start_time=start_str, end_time=end_str, period='1d')
        self.assertIsInstance(trading_info.start_time, datetime)
        self.assertIsInstance(trading_info.end_time, datetime)

    @patch('difoss_stock_util.stock_util.datetime')
    @patch('difoss_stock_util.stock_util.calc_belong_trading_day')
    @patch('difoss_stock_util.stock_util.calc_previous_trading_day')
    def test_complete_no_times_no_count(self, mock_prev_trading, mock_belong_trading, mock_datetime):
        """测试complete方法：没有提供时间和计数"""
        mock_datetime.now.return_value = self.now
        mock_belong_trading.return_value = date(2026, 3, 15)
        mock_prev_trading.return_value = date(2026, 3, 15)

        trading_info = TradingInfo(period='1d')
        result = trading_info.complete()

        self.assertIsNotNone(result.start_time)
        self.assertIsNotNone(result.end_time)
        self.assertEqual(result.count, 1)

    @patch('difoss_stock_util.stock_util.calc_belong_trading_day')
    @patch('difoss_stock_util.stock_util.calc_previous_trading_day')
    def test_complete_only_end_time(self, mock_prev_trading, mock_belong_trading):
        """测试complete方法：只提供结束时间"""
        mock_belong_trading.return_value = date(2026, 3, 15)
        mock_prev_trading.return_value = date(2026, 3, 10)

        end_time = datetime(2026, 3, 15)
        trading_info = TradingInfo(end_time=end_time, count=5, period='1d')
        result = trading_info.complete()

        mock_belong_trading.assert_called()
        mock_prev_trading.assert_called_with(date(2026, 3, 15), 4)
        self.assertEqual(result.start_time, date(2026, 3, 10))
        self.assertEqual(result.end_time, date(2026, 3, 15))

    @patch('difoss_stock_util.stock_util.calc_belong_trading_day')
    @patch('difoss_stock_util.stock_util.calc_next_trading_day')
    def test_complete_only_start_time(self, mock_next_trading, mock_belong_trading):
        """测试complete方法：只提供开始时间"""
        mock_belong_trading.return_value = date(2026, 3, 10)
        mock_next_trading.return_value = date(2026, 3, 15)

        start_time = datetime(2026, 3, 10)
        trading_info = TradingInfo(start_time=start_time, count=5, period='1d')
        result = trading_info.complete()

        mock_belong_trading.assert_called()
        mock_next_trading.assert_called_with(date(2026, 3, 10), 4)
        self.assertEqual(result.start_time, date(2026, 3, 10))
        self.assertEqual(result.end_time, date(2026, 3, 15))

    @patch('difoss_stock_util.stock_util.calc_count_of_trading_days')
    def test_complete_both_times(self, mock_calc_count):
        """测试complete方法：提供开始和结束时间"""
        mock_calc_count.return_value = 5

        start_time = datetime(2026, 3, 10)
        end_time = datetime(2026, 3, 15)
        trading_info = TradingInfo(start_time=start_time, end_time=end_time, period='1d')
        result = trading_info.complete()

        mock_calc_count.assert_called_with(start_time, end_time)
        self.assertEqual(result.count, 5)

    def test_get_time_range_not_completed(self):
        """测试get_time_range方法：未完成时自动调用complete"""
        trading_info = TradingInfo(period='1d')
        with patch.object(trading_info, 'complete') as mock_complete:
            mock_complete.return_value = trading_info
            trading_info.start_time = None
            trading_info.end_time = None

            start, end = trading_info.get_time_range()
            mock_complete.assert_called_once()

    def test_get_periods_daily(self):
        """测试get_periods方法：日线周期"""
        trading_info = TradingInfo(
            start_time=datetime(2026, 3, 10, 15, 0),
            end_time=datetime(2026, 3, 12, 15, 0),
            period='1d'
        )
        periods = trading_info.get_periods()
        expected_periods = [
            datetime(2026, 3, 10, 15, 0),
            datetime(2026, 3, 11, 15, 0),
            datetime(2026, 3, 12, 15, 0)
        ]
        self.assertEqual(periods, expected_periods)

    def test_get_periods_minute(self):
        """测试get_periods方法：分钟周期"""
        trading_info = TradingInfo(
            start_time=datetime(2026, 3, 10, 9, 30),
            end_time=datetime(2026, 3, 10, 9, 45),
            period='15m'
        )
        periods = trading_info.get_periods()
        expected_periods = [
            datetime(2026, 3, 10, 9, 30),
            datetime(2026, 3, 10, 9, 45)
        ]
        self.assertEqual(periods, expected_periods)

    def test_repr(self):
        """测试__repr__方法"""
        trading_info = TradingInfo(
            start_time=datetime(2026, 3, 10),
            end_time=datetime(2026, 3, 15),
            count=5,
            period='1d'
        )
        repr_str = repr(trading_info)
        self.assertIn("TradingInfo", repr_str)
        self.assertIn("start_time=2026-03-10", repr_str)
        self.assertIn("end_time=2026-03-15", repr_str)
        self.assertIn("count=5", repr_str)
        self.assertIn("period=1d", repr_str)

    def test_align_to_period_minute(self):
        """测试_align_to_period方法：分钟对齐"""
        trading_info = TradingInfo(period='5m')

        # 测试5分钟对齐
        dt = datetime(2026, 3, 10, 9, 32, 30)
        aligned = trading_info._align_to_period(dt)
        self.assertEqual(aligned, datetime(2026, 3, 10, 9, 30, 0))

        dt = datetime(2026, 3, 10, 9, 37, 30)
        aligned = trading_info._align_to_period(dt)
        self.assertEqual(aligned, datetime(2026, 3, 10, 9, 35, 0))

    def test_align_to_period_daily(self):
        """测试_align_to_period方法：日线对齐"""
        trading_info = TradingInfo(period='1d')

        dt = datetime(2026, 3, 10, 10, 30)
        aligned = trading_info._align_to_period(dt)
        self.assertEqual(aligned, datetime(2026, 3, 10, 15, 0))

    def test_align_to_period_weekly(self):
        """测试_align_to_period方法：周线对齐"""
        trading_info = TradingInfo(period='1w')

        # 假设周五是交易日结束
        dt = datetime(2026, 3, 9, 10, 30)  # 2026-03-09是周一
        aligned = trading_info._align_to_period(dt)
        # 应该对齐到本周五
        expected = datetime(2026, 3, 13, 15, 0)  # 2026-03-13是周五
        self.assertEqual(aligned, expected)

    def test_get_period_delta(self):
        """测试_get_period_delta方法"""
        trading_info = TradingInfo(period='1d')
        delta_info = trading_info._get_period_delta()
        self.assertEqual(delta_info['delta'], pd.Timedelta(days=1))
        self.assertEqual(delta_info['align'], 'day')

        trading_info = TradingInfo(period='5m')
        delta_info = trading_info._get_period_delta()
        self.assertEqual(delta_info['delta'], pd.Timedelta(minutes=5))
        self.assertEqual(delta_info['align'], '5min')

    def test_adjust_to_trading_hours(self):
        """测试_adjust_to_trading_hours方法"""
        trading_info = TradingInfo(period='15m')

        # 测试上午交易时间内的时间
        dt = datetime(2026, 3, 10, 10, 30)
        adjusted = trading_info._adjust_to_trading_hours(dt)
        self.assertEqual(adjusted, dt)

        # 测试下午交易时间内的时间
        dt = datetime(2026, 3, 10, 14, 0)
        adjusted = trading_info._adjust_to_trading_hours(dt)
        self.assertEqual(adjusted, dt)

        # 测试早于开盘时间
        dt = datetime(2026, 3, 10, 9, 0)
        adjusted = trading_info._adjust_to_trading_hours(dt)
        expected = datetime(2026, 3, 10, 9, 30)
        self.assertEqual(adjusted, expected)

        # 测试午休时间
        dt = datetime(2026, 3, 10, 12, 30)
        adjusted = trading_info._adjust_to_trading_hours(dt)
        expected = datetime(2026, 3, 10, 13, 0)
        self.assertEqual(adjusted, expected)

        # 测试晚于收盘时间
        dt = datetime(2026, 3, 10, 16, 0)
        adjusted = trading_info._adjust_to_trading_hours(dt)
        expected = datetime(2026, 3, 10, 15, 0)
        self.assertEqual(adjusted, expected)

    def test_intraday_complete_no_times(self):
        """测试分钟级别的complete方法：没有提供时间"""
        trading_info = TradingInfo(count=5, period='5m')
        result = trading_info.complete()

        self.assertIsNotNone(result.start_time)
        self.assertIsNotNone(result.end_time)
        self.assertEqual(result.count, 5)

    def test_intraday_complete_only_end_time(self):
        """测试分钟级别的complete方法：只提供结束时间"""
        end_time = datetime(2026, 3, 10, 10, 0)
        trading_info = TradingInfo(end_time=end_time, count=3, period='15m')
        result = trading_info.complete()

        # 结束时间应该对齐到15分钟边界
        expected_end = datetime(2026, 3, 10, 10, 0)  # 已经是15分钟边界
        self.assertEqual(result.end_time, expected_end)

        # 开始时间应该是结束时间前2个15分钟周期
        expected_start = datetime(2026, 3, 10, 9, 30)  # 10:00 - 30分钟 = 9:30
        self.assertEqual(result.start_time, expected_start)

    def test_intraday_complete_both_times(self):
        """测试分钟级别的complete方法：提供开始和结束时间"""
        start_time = datetime(2026, 3, 10, 9, 24)
        end_time = datetime(2026, 3, 10, 10, 30)
        trading_info = TradingInfo(start_time=start_time, end_time=end_time, period='15m')
        result = trading_info.complete()

        # 时间应该对齐到15分钟边界并调整到交易时间
        expected_start = datetime(2026, 3, 10, 9, 30)  # 9:24 对齐到9:15，但调整到交易时间9:30
        expected_end = datetime(2026, 3, 10, 10, 30)   # 10:30 已经在交易时间内
        self.assertEqual(result.start_time, expected_start)
        self.assertEqual(result.end_time, expected_end)

        # 计算周期数：从9:30到10:30，每15分钟一个周期，应该有5个周期 (9:30, 9:45, 10:00, 10:15, 10:30)
        self.assertEqual(result.count, 5)


if __name__ == '__main__':
    unittest.main()