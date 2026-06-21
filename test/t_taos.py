# -*- coding: utf-8 -*-
"""
Created on Sun Nov  9 03:02:19 2025

@author: DifossChen
"""

import taos
from difoss_stock_util.color_log_util import *

conn = None
host = "127.0.0.1"
port = 6030

try:
    conn = taos.connect(host=host, port=port,
                        user="root", password="taosdata",
                        database="stock", timezone="Asia/Shanghai")

    cursor = conn.cursor()
    sql = "SELECT * FROM history_data_1d"
    cursor.execute(sql)

    for row in cursor:
        print(row)

    D(**locals())

except ConnectionError as ce:
    print(f"Failed connect, ErrMessage: {ce} no: {ce.errno}")
    raise ce

except Exception as err:
    print(f"Failed to create database power or stable meters, ErrMessage:{err}")
    raise err
    
finally:
    if conn:
        conn.close()