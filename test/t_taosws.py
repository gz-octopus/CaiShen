import taosws
from difoss_stock_util.color_log_util import *

conn = None
host = "localhost"
port = 6041
try:
    conn = taosws.connect(user="root",
                          password="taosdata",
                          database="stock",
                          host=host,
                          port=port)

    cursor = conn.cursor()
    sql = "SELECT * FROM history_data_1d;"
    cursor.execute(sql)
    
    rows = cursor.fetchall()
    D(rows=rows)

except Exception as err:
    print(f"Failed to create database power or stable meters, ErrMessage:{err}") 
    raise err
finally:
    if conn:
        conn.close()
