#!python3
# coding: utf-8
import pandas as pd
from difoss_stock_util.rich_util.rich_table import print_dataframe

if __name__ == "__main__":
    data = {
        "代码": ["300368", "300040", "300317"],
        "名称": ["汇金股份", "九洲集团", "珈伟新能"],
        "收盘": [9.41, 6.52, 4.55],
        "盈亏.收盘%": [20.03, 12.80, 10.17],
        "盈亏.最高%": [20.03, 15.74, 13.56],
        "盈亏.最低%": [-2.93, -3.11, -4.84],
    }
    df_test = pd.DataFrame(data)

    # 多级表头（含 . 的列名自动拆两行）
    print_dataframe(df_test, title="持仓盈亏示例", show_index=True,
                    sum_cols=["收盘", "盈亏.收盘%"],
                    avg_cols=["盈亏.收盘%", "盈亏.最高%"])

    # 单级表头（无 . 时等价原行为）
    df_single = df_test[["代码", "名称", "收盘"]]
    print_dataframe(df_single, title="基本信息", show_index=True)
