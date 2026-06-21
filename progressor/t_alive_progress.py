from alive_progress import alive_bar
import time
from difoss_stock_util.color_log_util import cursor_set_x, cursor_set_position

with alive_bar(100, title="Downloading", spinner='classic') as bar:
    for i in range(100):
        time.sleep(0.05)
        bar()  # 更新进度
        # 可以在这里打印子任务信息
        if i % 10 == 0:
            print(f"{cursor_set_position(0,0)}  Processing file_{i//10}.txt")
