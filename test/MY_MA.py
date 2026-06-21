#encoding:utf-8
'''
本策略事先设定好交易的股票篮子，然后根据指数的CCI指标来判断超买和超卖
当有超买和超卖发生时，交易事先设定好的股票篮子
'''
import pandas as pd
import numpy as np
import talib

def init(ContextInfo):
    #hs300成分股中sh和sz市场各自流通市值最大的前3只股票
    ContextInfo.trade_code_list=['601398.SH','601857.SH','601288.SH','000333.SZ','002415.SZ','000002.SZ']
    ContextInfo.set_universe(ContextInfo.trade_code_list)
    ContextInfo.accID = '6000000058'
    ContextInfo.buy = True
    ContextInfo.sell = False

    """
    策略初始化函数
    Args:
        ContextInfo: 上下文信息对象
    """
    # 设置策略参数
    ContextInfo.ma_fast = 5    # 快速均线周期
    ContextInfo.ma_slow = 10    # 慢速均线周期
    #ContextInfo.barpos = 0       # K线位置计数器
    
    # 初始化均线数据列表
    ContextInfo.ma5_list = []
    ContextInfo.ma10_list = []
    
    # 初始化交易状态
    ContextInfo.position = 0     # 持仓状态：0-空仓，1-持多仓
    ContextInfo.last_signal = 0  # 上一次信号：0-无信号，1-买入，-1-卖出
    
    # 打印初始化信息
    print("MA均线交叉策略初始化完成")
    print(f"快速均线周期：{ContextInfo.ma_fast}，慢速均线周期：{ContextInfo.ma_slow}")


def handlebar(ContextInfo):
	print("ENTER handlebar()...")
    """
    K线处理函数 - 每根K线结束时调用
    Args:
        ContextInfo: 上下文信息对象
    """
    # 更新K线位置
    ContextInfo.barpos += 1
    
    # 获取当前标的代码
    stock_code = ContextInfo.get_stockcode()
    print(f"stock_code={stock_code}")
    
    # 获取历史数据计算均线
    hist_data = ContextInfo.get_market_data(
        ['close'], 
        stock_code=stock_code, 
        period='1d', 
        count=ContextInfo.ma_slow + 1
    )
    
    if hist_data is None or len(hist_data['close']) < ContextInfo.ma_slow:
        return
    
    close_prices = hist_data['close']
    
    # 计算MA5和MA10
    if len(close_prices) >= ContextInfo.ma_fast:
        ma5 = sum(close_prices[-ContextInfo.ma_fast:]) / ContextInfo.ma_fast
        ContextInfo.ma5_list.append(ma5)
    else:
        return
        
    if len(close_prices) >= ContextInfo.ma_slow:
        ma10 = sum(close_prices[-ContextInfo.ma_slow:]) / ContextInfo.ma_slow
        ContextInfo.ma10_list.append(ma10)
    else:
        return
    
    # 确保有足够的数据进行交叉判断
    if len(ContextInfo.ma5_list) < 2 or len(ContextInfo.ma10_list) < 2:
        return
    
    # 获取当前和前一根K线的均线值
    current_ma5 = ContextInfo.ma5_list[-1]
    current_ma10 = ContextInfo.ma10_list[-1]
    prev_ma5 = ContextInfo.ma5_list[-2]
    prev_ma10 = ContextInfo.ma10_list[-2]
    
    # 判断均线交叉信号
    # MA5上穿MA10：前一根K线MA5<=MA10，当前K线MA5>MA10
    if (prev_ma5 <= prev_ma10 and current_ma5 > current_ma10 and 
        ContextInfo.position == 0 and ContextInfo.last_signal != 1):
        
        # 执行买入操作
        buy_price = close_prices[-1]
        buy_quantity = int(ContextInfo.get_cash() / buy_price / 100) * 100  # 按手数买入
        
        if buy_quantity > 0:
            # 使用市价单买入
            order_result = ContextInfo.passorder(
                23,                    # 操作类型：23-买入
                1101,                  # 订单类型：1101-普通订单
                stock_code,           # 标的代码
                buy_quantity,         # 买入数量
                0,                     # 价格（0表示市价）
                'Market',             # 报价方式
                0,                     # 策略ID
                ''                     # 用户自定义字段
            )
            
            if order_result:
                ContextInfo.position = 1
                ContextInfo.last_signal = 1
                print(f"[买入信号] K线位置：{ContextInfo.barpos}，价格：{buy_price:.2f}，数量：{buy_quantity}")
    
    # MA5下穿MA10：前一根K线MA5>=MA10，当前K线MA5<MA10
    elif (prev_ma5 >= prev_ma10 and current_ma5 < current_ma10 and 
          ContextInfo.position == 1 and ContextInfo.last_signal != -1):
        
        # 执行卖出操作
        sell_price = close_prices[-1]
        sell_quantity = ContextInfo.get_position(stock_code)
        
        if sell_quantity > 0:
            # 使用市价单卖出
            order_result = ContextInfo.passorder(
                24,                    # 操作类型：24-卖出
                1101,                  # 订单类型：1101-普通订单
                stock_code,           # 标的代码
                sell_quantity,        # 卖出数量
                0,                     # 价格（0表示市价）
                'Market',             # 报价方式
                0,                     # 策略ID
                ''                     # 用户自定义字段
            )
            
            if order_result:
                ContextInfo.position = 0
                ContextInfo.last_signal = -1
                print(f"[卖出信号] K线位置：{ContextInfo.barpos}，价格：{sell_price:.2f}，数量：{sell_quantity}")
    
    # 记录均线数据（可选）
    if ContextInfo.barpos % 10 == 0:
        print(f"K线位置：{ContextInfo.barpos}，MA5：{current_ma5:.2f}，MA10：{current_ma10:.2f}")

