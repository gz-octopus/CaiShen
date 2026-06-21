from xtquant import xtdata
import pandas as pd
from difoss_stock_util import *
from difoss_stock_util.color_log_util import *

from datetime import datetime

xtdata.enable_hello = False
# stocks = ['600051.SH', '002772.SZ']
stocks = ['002415.SZ']

period = 10
start_date = None
end_date = datetime.now().strftime("%Y%m%d")

# 获取交易日列表
trading_dates = xtdata.get_trading_dates(market='SH', end_time=end_date, count=period)

if not trading_dates:
    E(error='无法获取交易日列表')
    exit()
    
D(trading_dates=trading_dates, period=period, end_date=end_date)

# 反推历史数据开始日期
start_datetime = TimeUtils.ms_to_datetime(trading_dates[0])
start_date = start_datetime.strftime("%Y%m%d")
D(start_date=start_date)

xtdata.download_history_data2(stock_list=stocks, period='1d', start_time=start_date)
res = xtdata.get_market_data(stock_list=stocks, end_time=end_date, period='1d', count=period)
D(RETURN='get_market_data()', type=type(res), keys=res.keys())
for field, df in res.items():
    D(field=field, df=df)

res_ex = xtdata.get_market_data_ex(stock_list=stocks, end_time=end_date, period='1d', count=period)
D(RETURN='get_market_data_ex()', type=type(res_ex), keys=res_ex.keys())    
for stock_code, df in res_ex.items():
    D(stock_code=stock_code, df=df)
