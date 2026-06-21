#!python
import MetaTrader5 as mt5
from datetime import datetime
import pandas as pd
import time # 用于可能的延时

# 设置 Pandas 显示选项（可选）
pd.set_option('display.max_columns', 500) # 显示更多列
pd.set_option('display.width', 1500)      # 设置显示宽度

if not mt5.initialize():
    print(f"MT5初始化失败，错误码={mt5.last_error()}")
    mt5.shutdown()
    exit()
