#!python
# encoding: utf-8
# author: DifossChen
# ref: https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h12t4q6fg29o.html#%E4%BB%80%E4%B9%88%E6%98%AF%E9%87%8F%E5%8C%96%E4%BA%A4%E6%98%93

import pandas as pd
import vectorbt as vbt
from tdx_quant.tqcenter import tq

tq.initialize(__file__)

# 解决 pandas future warning
pd.set_option('future.no_silent_downcasting', True)

# ========================= 核心配置（用户可直接修改这里）=========================
target_start = '20240930'  # 【目标回测开始时间】（真正想回测的起始日）
target_end = '20250930'    # 【目标回测结束时间】
stock_code_list = ['688318.SH']     # 股票代码
window = 5         # MA指标周期（如MA5、MA10、MA20，改这里自动适配历史数据）
# ================================================================================

start_time = (pd.to_datetime(target_start) - pd.Timedelta(days=window + 10)).strftime('%Y%m%d')

# 1.获取价格数据
df_real = tq.get_market_data(
    field_list=['Close', 'Open'],
    stock_list=stock_code_list,
    start_time=start_time,
    end_time=target_end,
    dividend_type='front',
    period='1d',
    fill_data=True
)
close_df = tq.price_df(df_real, 'Close', column_names=stock_code_list)
open_df = tq.price_df(df_real, 'Open', column_names=stock_code_list)


# 2.买卖信号计算与生成
ma5_dynamic = vbt.MA.run(close_df, window=window).ma
ma5_dynamic.columns = close_df.columns

entries_raw = close_df.vbt.crossed_above(ma5_dynamic)
exits_raw = close_df.vbt.crossed_below(ma5_dynamic)

# 信号移位+1
entries_df = entries_raw.shift(1).fillna(False).astype(bool)
exits_df = exits_raw.shift(1).fillna(False).astype(bool)


# 3. 执行回测
portfolio = vbt.Portfolio.from_signals(
    close=close_df,             # 净值计算用未复权收盘价
    entries=entries_df,              # 延迟后的买入信号
    exits=exits_df,                  # 延迟后的卖出信号
    price=open_df,                # 含滑点的成交价格
    init_cash=100000,            #  初始资金10万元
    fees=0.0003,                  # 手续费0.03%（双边）
    freq='D',                     # 日线频率
    size_granularity=100          # A股最小交易单位100股
)


# 4. 输出回测结果
print(f"\n======投资组合回测表现=====")
print(portfolio.stats())
print(f"\n======投资组合回测记录======")
print(portfolio.trades.records_readable)

