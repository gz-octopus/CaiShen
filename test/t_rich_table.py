#!python
import pandas as pd
from rich.table import Table
from rich.console import Console
from difoss_stock_util.rich_util.rich_table import dataframe_to_rich_table

console = Console()

# 创建示例 DataFrame
data = {
    '股票代码': ['000001', '000002', '600000', '600036', '601318'],
    '名称': ['平安银行', '万科A', '浦发银行', '招商银行', '中国平安'],
    '当前价': [15.23, 25.67, 12.45, 38.91, 68.34],
    '涨跌幅': [2.34, -1.23, 0.56, 3.45, -0.89],
    '成交量(万手)': [1234, 567, 890, 2345, 1789],
    '市值(亿)': [2956.7, 2890.1, 3567.8, 8765.4, 13456.9]
}

df = pd.DataFrame(data)


# 转换并打印
table = dataframe_to_rich_table(df, "📈 股票行情")
console.print(table)
