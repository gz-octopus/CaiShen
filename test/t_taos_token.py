# -*- coding: utf-8 -*-

import taos
import os

from difoss_stock_util.color_log_util import *

try:

    # url = os.environ["TDENGINE_URL"]
    # token = os.environ["TDENGINE_TOKEN"]

    # conn = taos.connect(url=url, token=token)
    
    
    conn = taos.connect()
    conn.select_db("stock")
    
    result = conn.query("SELECT * FROM history_data_1d")
    for row in result:
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