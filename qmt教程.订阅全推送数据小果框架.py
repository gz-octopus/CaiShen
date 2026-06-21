# -*- coding: utf-8 -*-
import time
from qmt_trader.qmt_data import qmt_data
data=qmt_data()
code='600031.SH'
#订阅最新行情
def callback_func(datas):
    print('回调触发')
    stock_code=list(datas.keys())
    df=data.get_full_tick(code_list=stock_code)
    print(df)
    data.subscribe_quote(stock_code=code,start_time='20240101',end_time='20240525',period='1m')
    hist=data.get_market_data(stock_list=[code],start_time='20240101',end_time='20240525',period='1m')
    print(hist)
data.subscribe_whole_quote(code_list=[code],callback=callback_func)
#死循环 阻塞主线程退出
data.run()