#!python
import re
from collections import defaultdict
from xtquant import xtdata
xtdata.enable_hello = False # 关闭数据获取的输出日志

import click
from rich.console import Console
from rich import console
from difoss_stock_util.click_util import split_comma_stocks, split_comma


# ----------------------------------------------------------------------------
# 全局变量
CONSOLE = Console()

# ----------------------------------------------------------------------------

def classify_stock_symbol(symbol: str) -> str:
    """
    根据中划线、字母与数字的位置特征对股票代码进行分类

    分类规则：
    - 纯数字
    - 纯字母
    - 数字开头+中划线+数字/字母
    - 字母开头+中划线+数字/字母
    - 数字+字母混合（无中划线）
    - 字母+数字混合（无中划线）
    - 其他模式
    """

    # 去除可能的空格
    symbol = symbol.strip()
    
    # 去掉尾部市场标识（如 .SH、.SZ）
    symbol = re.sub(r'\.[A-Za-z]+$', '', symbol)

    # 定义模式
    patterns = {
        '纯数字': r'^\d+$',
        '纯字母': r'^[A-Za-z]+$',
        '数字-数字': r'^\d+-\d+$',
        '数字-字母': r'^\d+-[A-Za-z]+$',
        '字母-数字': r'^[A-Za-z]+-\d+$',
        '字母-字母': r'^[A-Za-z]+-[A-Za-z]+$',
        '数字+字母(无分隔符)': r'^\d+[A-Za-z]+$',
        '字母+数字(无分隔符)': r'^[A-Za-z]+\d+$',
        '包含多个中划线': r'.*-.*-.*',
        '带前缀和&的两个合约代码': 
            r'^[A-Za-z]+\s+'              # 前缀：纯字母（1个或多个）
            r'[A-Za-z]+\d+[A-Za-z]?&'     # 第一个代码：字母+数字+可选字母
            r'[A-Za-z]+\d+[A-Za-z]?',     # 第二个代码：字母+数字+可选字母
        '期货期权': r'^[A-Za-z]+\d+[A-Za-z]+\d+$',
        '其他': r'.*'
    }

    # 按优先级匹配
    for category, pattern in patterns.items():
        if re.match(pattern, symbol):
            # 对于包含中划线但不是简单模式的特殊处理
            if category == '其他' and '-' in symbol and not re.match(r'.*-.*-.*', symbol):
                return '其他(含中划线)'
            return category

    return '未分类'

def analyze_stock_symbols(sector=None):
    """
    分析股票代码的分类统计

    参数:
    sector: 板块名称，如果为None则获取所有可交易标的

    返回:
    分类统计字典
    """
    try:
        # 获取股票列表
        if sector:
            stock_list = xtdata.get_stock_list_in_sector(sector)
        else:
            return {}
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        return {}

    # 统计分类
    category_stats = defaultdict(int)
    detailed_results = []

    for stock in stock_list:
        # 获取股票代码
        code = stock.get('code', '') if isinstance(stock, dict) else str(stock)

        # 分类
        category = classify_stock_symbol(code)
        category_stats[category] += 1

        # 保存详细结果
        detailed_results.append({
            'code': code,
            'category': category
        })

    return {
        '统计结果': dict(category_stats),
        '详细信息': detailed_results,
        '总数量': len(stock_list)
    }

def print_statistics(stats, console=None):
    """
    打印统计结果
    """
    if console is None:
        global CONSOLE
        console = CONSOLE
        
    if not stats:
        console.print("无统计数据")
        return

    console.print("=" * 60)
    console.print("股票代码分类统计")
    console.print("=" * 60)
    console.print(f"总数量: {stats['总数量']}")
    console.print("-" * 60)
    console.print("分类统计:")

    # 按数量排序
    sorted_stats = sorted(stats['统计结果'].items(), key=lambda x: x[1], reverse=True)

    for category, count in sorted_stats:
        percentage = (count / stats['总数量']) * 100
        console.print(f"  {category}: {count} ({percentage:.2f}%)")

    console.print("=" * 60)

    # 可选：显示示例
    console.print("\n分类示例 (前5个):")
    sample_by_category = {}
    for item in stats['详细信息']:
        category = item['category']
        if category not in sample_by_category:
            sample_by_category[category] = []
        if len(sample_by_category[category]) < 5:
            sample_by_category[category].append(item['code'])

    for category, samples in sample_by_category.items():
        print(f"  {category}: {', '.join(samples)}")

# 使用示例
def demo_test():
    # 演示数据（如果没有真实数据）
    demo_stocks = [
        '000001', '600001', '300001',  # 纯数字
        'AAPL', 'MSFT', 'GOOGL',       # 纯字母
        '000001-001', '600001-01',      # 数字-数字
        '000001-HK', '600001-US',       # 数字-字母
        'HK-000001', 'US-600001',       # 字母-数字
        'HK-AAPL', 'US-GOOGL',          # 字母-字母
        '000001A', '600001B',           # 数字+字母
        'AAPL2023', 'MSFT2024',         # 字母+数字
        'HK-000001-01', 'US-600001-01', # 多个中划线
    ]

    print("\n使用演示数据进行统计分析:")
    stats = defaultdict(int)
    for stock in demo_stocks:
        category = classify_stock_symbol(stock)
        stats[category] += 1

    print(f"总数量: {len(demo_stocks)}")
    for category, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        print(f"  {category}: {count}")


@click.command(context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('-s', '--sector', 'sectors', multiple=True, callback=split_comma, default=None, help='板块名称')
def _main(sectors: list
):
    """
    主函数
    """
    global CONSOLE
    
    if not sectors:
        demo_test()
        return

    try:
        for sector in sectors:
            print(f"正在分析板块: {sector}")
            results = analyze_stock_symbols(sector)
            if results:
                print_statistics(results)
            else:
                print("获取数据失败")
                continue

    except NameError:
        print("提示: xtdata 模块未导入或不存在")
        print("请确保已正确导入 xtdata 模块")

        demo_test()
        
    except Exception as e:
        CONSOLE.print_exception(extra_lines=5, show_locals=True)


if __name__ == "__main__":
    _main()