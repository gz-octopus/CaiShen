#!python
from pytdx.exhq import TdxExHq_API
from pytdx.util.best_ip import select_best_ip

import click

ip = select_best_ip('future')
print("最佳IP:", ip)


api = TdxExHq_API()
with api.connect(ip['ip'], ip['port']):  # 使用上一步获取的IP
    data = api.get_instrument_bars(
        category=0,  # 0=分时, 4=1分钟
        market=4,    # 4=港股期货
        code="MHI2604"
    )
    print(data)

