
from difoss_stock_util import create_limiter

# 使用
limiter = create_limiter(3)

for i in range(10):
    if limiter():
        print(f"执行第 {i+1} 次循环中的受限代码")
        # 这里放置你想要限制执行次数的代码
    else:
        print(f"i={i}")
