import requests
import json
from datetime import datetime

def fetch_jisilu_json(dt: datetime = datetime.now()):
    """
    抓取集思录（jisilu.cn）JSON 数据

    Args:
        dt: 需要获取哪个时刻的数据（默认为当前时间）

    Returns:
        dict: 解析后的 JSON 数据（如果成功）
        str: 错误信息（如果失败）
    """

    url = f"https://www.jisilu.cn/data/cbnew/cb_list_new/?___jsl=LST___t={int(dt.timestamp())}"

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


def main():
    result = fetch_jisilu_json()
    json_str = json.dumps(result, indent=2, ensure_ascii=False)

    if result:
        print(json_str)

if __name__ == "__main__":
    main()