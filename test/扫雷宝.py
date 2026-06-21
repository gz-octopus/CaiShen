import requests
import json
import sys

def fetch_tdx_json(stock_code):
    """
    抓取通达信股票 JSON 数据
    
    Args:
        stock_code (str): 6位股票代码（如 "000507"）
    
    Returns:
        dict: 解析后的 JSON 数据（如果成功）
        str: 错误信息（如果失败）
    """
    url = f"http://page3.tdx.com.cn:7615/site/pcwebcall_static/bxb/json/{stock_code}.json"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Referer": "http://page3.tdx.com.cn:7615/site/pcwebcall_static/bxb/bxb.html",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        return json.loads(response.text)
    
    return None


def calculate_total_fs(data):
    total_minus_fs = 0
    
    # 遍历所有data条目
    for category in data.get("data", []):
        # 遍历每个category中的rows
        for row in category.get("rows", []):
            # 检查row本身的trig
            if row.get("trig") == 1:
                total_minus_fs += row.get("fs", 0)

    return 100 - total_minus_fs

from difoss_stock_util import *
from difoss_stock_util.color_log_util import *

# 测试代码
if __name__ == "__main__":
    
    # 处理输入参数
    argv = sys.argv[1:]
    
    flag_wanna_detail = False
    flag_wanna_save = False
    
    if '-d' in argv:
        flag_wanna_detail = True
        argv.remove('-d')
    if '-s' in argv:
        flag_wanna_save = True
        argv.remove('-s')
    
    argc = len(argv)
    
    if argc == 0:
        stock_code_list = ["301316"] # 默认参数
    else:
        stock_code_list = argv
        
    # 正式逻辑
    for stock_code in stock_code_list:
        result = fetch_tdx_json(stock_code)
        json_str = json.dumps(result, indent=2, ensure_ascii=False)
        
        if result:
            stock_name = result.get('name', '(未知股票)')
            if flag_wanna_detail:
                D(f"成功获取股票 {stock_code} 的 JSON 数据：{json_str}")
            total_fs = calculate_total_fs(result)
            
            if flag_wanna_save:
                with open(f'SLB.{stock_code}.json', 'w', encoding='utf-8') as F:
                    F.write(json_str)

            I(code=stock_code, name=stock_name, 扫雷宝总分=total_fs)
        else:
            E("无法获取股票JSON 数据", code=stock_code, name=stock_code)
    
