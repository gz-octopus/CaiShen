import json
import sys
import io
import click
import time
from datetime import timedelta
from colorama import just_fix_windows_console
from typing import Callable, Any
import functools
from difoss_stock_util import *
from difoss_stock_util.color_log_util import *

# 测试代码
if __name__ == "__main__":

    @trace_function
    def quick_function():
        """快速执行的函数"""
        time.sleep(0.1)
        return "quick done"

    @trace_function
    def slow_function():
        """慢速执行的函数"""
        time.sleep(2.5)
        return "slow done"

    @trace_function
    def very_slow_function():
        """非常慢的函数"""
        time.sleep(5.5)
        return "very slow done"

    @trace_function
    def failing_function():
        """会抛出异常的函数"""
        time.sleep(0.5)
        raise ValueError("测试异常")

    # 测试不同时长的函数
    print("=== 测试快速函数 ===")
    result1 = quick_function()
    print(f"结果: {result1}\n")

    print("=== 测试慢速函数 ===")
    result2 = slow_function()
    print(f"结果: {result2}\n")

    print("=== 测试非常慢的函数 ===")
    result3 = very_slow_function()
    print(f"结果: {result3}\n")

    print("=== 测试异常函数 ===")
    try:
        failing_function()
    except Exception as e:
        print(f"捕获到异常: {e}\n")
