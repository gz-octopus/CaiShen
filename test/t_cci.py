from xtquant import xtdata
from difoss_stock_util import *
from difoss_stock_util.xtquant_util import connect_miniQMT
from difoss_stock_util.tdx_util import *
from difoss_stock_util.color_log_util import *
import pandas as pd
from typing import List, Union, Dict, Tuple

xtdata.enable_hello = False

trade_code_list = ['002415.SZ'] #,'601398.SH','601857.SH','601288.SH','000333.SZ','000002.SZ']
code_2_detail = {}

# 把扫雷宝存于 redis 中


@trace_function
def show_suspended_status(sectors=['沪深A股'], upper_limit=None):
    '''查看全市场股票停牌情况'''
    global code_2_detail
    code_2_detail = get_details(sectors=sectors, upper_limit=upper_limit)


    codes_normal = []
    codes_suspended = []
    codes_resumptive = []

    for stock_code, detail in code_2_detail.items():
        detail = xtdata.get_instrument_detail(stock_code)

        code_2_detail.update({stock_code: detail})

        InstrumentStatus = detail.get('InstrumentStatus', -2)
        InstrumentName = detail.get('InstrumentName', '')
        if InstrumentStatus == 1:
            W(停牌=stock_code, name=InstrumentName)
            codes_suspended.append(stock_code)
            continue

        if InstrumentStatus == -1:
            codes_resumptive.append(stock_code)
            W(当日起复牌=stock_code, name=InstrumentName)
            continue

        codes_normal.append(stock_code)


    P(**{"沪深A股个数": len(codes_normal) + len(codes_suspended) + len(codes_resumptive),
        "正常（只）": len(codes_normal),
        "停牌（只）": len(codes_suspended),
        "停牌个股": codes_suspended,
        "今日复牌（只）": len(codes_resumptive),
        "今日复牌个股": [f"{x} {code_2_detail.get(x, {}).get('InstrumentName', '')}" for x in codes_resumptive],
        }
    )


# ---------------------------------------------------
from datetime import datetime, timedelta
import talib
import numpy as np

# 注意 start_time 和 end_time 之间必须有 period 以上个交易日
period = 14
start_time = '20250101'
end_time = '20250931'


@trace_function
def handlebar(bar_index: int, ts_sec: int, dt: datetime):
    global trade_code_list, period, code_2_detail
    stock_codes = trade_code_list

    dateYYMMdd = dt.strftime('%Y%m%d')
    I(barpos=bar_index, time=dateYYMMdd, stock_codes=stock_codes, period=period)

    # 注意：先使用 download_history_data2 下载历史数据，再调用 get_market_data_ex
    mkdict = xtdata.get_market_data_ex(stock_list=stock_codes, end_time=dateYYMMdd, field_list=['high','low','close'], count=int(period)+1, dividend_type='front')

    # P(mkdict=mkdict)

    for stock_code, dataframe in mkdict.items():
        highs = np.array(dataframe['high'].values)
        lows = np.array(dataframe['low'].values)
        closes = np.array(dataframe['close'].values)
        cci_list = talib.CCI(highs, lows, closes, timeperiod=int(period))
        P(highs=highs, lows=lows, closes=closes,dateYYMMdd=dateYYMMdd)
        now_cci = cci_list[-1]
        ytd_cci = cci_list[-2]

        detail = code_2_detail.get(stock_code, '{}')

        ma10s = MA(closes, 10)
        D(**{'ma(close, 10)': ma10s, 'len(ma(close,10))': len(ma10s)})

        D(stock_code=stock_code, detail=detail, _indent=2)

        T(now_cci=now_cci, yesterday_cci=ytd_cci, cci_list=cci_list)

        return

def back_test():
    global start_time, end_time, trade_code_list, code_2_detail

    code_2_detail = get_details(stock_codes=trade_code_list, sectors=None)
    dates_ts = xtdata.get_trading_dates('SH', start_time, end_time)

    相隔交易日 = len(dates_ts)
    if 相隔交易日 < period:
        E(f'相隔交易日 {相隔交易日} < period({相隔交易日}), 请调整参数（不然无法算出cci）')
        return

    xtdata.download_history_data2(stock_list=trade_code_list, start_time=start_time, end_time=end_time, period='1d')

    bar_cnt = 0
    for date_ts in dates_ts:

        timestamp_seconds = date_ts / 1000
        dt = datetime.fromtimestamp(timestamp_seconds)
        readable_time = dt.strftime('%Y-%m-%d %H:%M:%S.%f')

        I(bar_cnt=bar_cnt, date=readable_time)
        bar_cnt += 1

        handlebar(bar_cnt, timestamp_seconds, dt)

        break # 测试目前只运行一次


connect_miniQMT(ip='192.168.0.107')
show_suspended_status()
# back_test()
#MA( [100, 102, 101, 104, 103, 105, 107, 106, 108, 109, 110, 112, 113, 115], 10)