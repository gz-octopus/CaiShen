#!python
# -*- coding: utf-8 -*-
# description: TdxQuant资金数据实战指南：主力净额选股+自动化下单完整示例
# From: https://mp.weixin.qq.com/s/I6_CvAbLK0RhZm-wuag0lA

import sys
import time

import click
from rich import print as pprint
from rich.console import Console
from difoss_stock_util.util import *
from difoss_stock_util.color_log_util import *

sys.path.append('C:/new_tdx_test2025/PYPlugins/user')
from tdx_quant.tqcenter import tq

# 初始化
tq.initialize(__file__)

CONSOLE = Console()

# 先获取A股全部股票（测试时可以先限制数量）
all_stocks = tq.get_stock_list(market='5')[:100]
# all_stocks = ['300911.SZ', '600635.SH', '000890.SZ', '603155.SH', '301448.SZ']

# 强制刷新缓存
refresh_cache = tq.refresh_cache('ZS', True)

print("正在处理，请等待...")
start_date = '20240601'
end_date = '20240630'

# 初始化变量
pre_mul_zb_result = {}
mul_zb_result = {}
countjs = 1
max_iterations = 10  # 设置最大循环次数

while countjs <= max_iterations:
    # 保存之前的值
    pre_mul_zb_result = mul_zb_result.copy()

    # 获取最新的主力净额数据
    mul_zb_result = tq.formula_process_mul_zb(
        formula_name='ZLJE',
        formula_arg='',
        xsflag=6,
        return_count=2,
        return_date=True,
        stock_list=all_stocks,
        stock_period='1d',
        count=-1,
        start_time=start_date,
        end_time=end_date,
        dividend_type=1
    )

    print(f"\n=== 循环 {countjs} ===")
    countjs += 1

    # 检查是否有有效的数据
    if mul_zb_result and countjs >= 2:
        diff_list = []
        
        I(mul_zb_result=mul_zb_result)
        CONSOLE.print(f'个股: {all_stocks}')

        # 计算每只股票的主力净额变化差值
        for key in mul_zb_result:
            if key != "ErrorId":
                if (key in mul_zb_result
                    and '主力净额' in mul_zb_result[key]
                    and len(mul_zb_result[key]['主力净额']) >= 1
                    and key in pre_mul_zb_result
                    and '主力净额' in pre_mul_zb_result[key]
                    and len(pre_mul_zb_result[key]['主力净额']) >= 1):

                    curr_val = mul_zb_result[key]['主力净额'][-1]['Value']
                    pre_val = pre_mul_zb_result[key]['主力净额'][-1]['Value']
                    ce_val = float(curr_val) - float(pre_val)
                    diff_list.append((key, ce_val))

        # 按差值从大到小排序，输出前5名
        if diff_list:
            diff_list.sort(key=lambda x: x[1], reverse=True)
            print("🔥 **主力净额变化前5名:**")
            print("-" * 50)
            for i, (code, diff) in enumerate(diff_list[:5], 1):
                print(f"{i}. {code}: {diff:.2f} 万元")
            print("-" * 50)
        else:
            print("⚠️ 无有效差值数据")

    # 等待3分钟再进行下一次循环
    time.sleep(180)

print("✅ 处理完成")
