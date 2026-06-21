#! python
# encoding: utf-8

# REF: https://www.mql5.com/zh/book/advanced/python/python_copyrates

import MetaTrader5 as mt5
import pandas as pd              # connect the pandas module to output data
import matplotlib.pyplot as plt  # connect the matplotlib module for drawing

# let's establish a connection to the MetaTrader 5 terminal
if not mt5.initialize():
    print("initialize() failed, error code =", mt5.last_error())
    mt5.shutdown()
    quit()

# create a path in the sandbox for the image with the result
image = mt5.terminal_info().data_path + r'\MQL5\Files\MQL5Book\ratescorr'

# the list of working currencies for calculating correlation
sym = ['EURUSD','GBPUSD','USDJPY','USDCHF','AUDUSD','USDCAD','NZDUSD','XAUUSD']
sym = [f"{x}.s" for x in sym]  # TODO: Add .s caz fucking Doo Tech

# copy the closing prices of bars into DataFrame structures
d = pd.DataFrame()
for i in sym:        # last 1000 M1 bars for each symbol
    rates = mt5.copy_rates_from_pos(i, mt5.TIMEFRAME_M1, 0, 1000)
    d[i] = [y['close'] for y in rates]

# complete the connection to the MetaTrader 5 terminal
mt5.shutdown()

# calculate the price change as a percentage
rets = d.pct_change()

# compute correlations
corr = rets.corr()

# draw the correlation matrix
fig = plt.figure(figsize = (5, 5))
fig.add_axes([0.15, 0.1, 0.8, 0.8])
plt.imshow(corr, cmap = 'RdYlGn', interpolation = 'none', aspect = 'equal')
plt.colorbar()
plt.xticks(range(len(corr)), corr.columns, rotation = 'vertical')
plt.yticks(range(len(corr)), corr.columns)
plt.show()
plt.savefig(image)