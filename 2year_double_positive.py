#!python
import pandas as pd
import numpy as np
import akshare as ak
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')
from difoss_stock_util import *
from difoss_stock_util.color_log_util import *
from difoss_stock_util.rich_util.fixed_progress_simple_v2_Qwen3Max import *
from rich import print

class DoubleYangBacktest:
    def __init__(self):
        self.stock_data = {}

    def get_stock_data(self, stock_code, start_date, end_date):
        """获取股票数据"""
        try:
            if stock_code.startswith('6'):
                code = f"sh{stock_code}"
            else:
                code = f"sz{stock_code}"

            df = ak.stock_zh_a_hist(symbol=stock_code, period="daily",
                                    start_date=start_date, end_date=end_date,
                                    adjust="hfq")
            if not df.empty:
                df['代码'] = stock_code
                df['日期'] = pd.to_datetime(df['日期'])
                df = df.sort_values('日期')
                return df
        except Exception as e:
            print(f"获取{stock_code}数据失败: {e}")
            exit(1)
        return None

    def detect_double_yang(self, df: pd.DataFrame):
        """检测倍阳形态"""
        signals = []

        for i in range(1, len(df)):
            # 当前成交量是前一日成交量的2倍以上
            volume_condition = df.iloc[i]['成交量'] >= 2 * df.iloc[i-1]['成交量']
            # 当前收盘价上涨
            price_condition = df.iloc[i]['收盘'] > df.iloc[i-1]['收盘']
            # 振幅适中，排除异常波动
            amplitude = (df.iloc[i]['最高'] - df.iloc[i]['最低']) / df.iloc[i-1]['收盘']
            amplitude_condition = amplitude < 0.15  # 振幅小于15%

            if volume_condition and price_condition and amplitude_condition:
                signals.append({
                    'date': df.iloc[i]['日期'],
                    'close': df.iloc[i]['收盘'],
                    'volume': df.iloc[i]['成交量'],
                    'prev_volume': df.iloc[i-1]['成交量'],
                    'amplitude': amplitude
                })

        return signals

    def calculate_returns(self, df, signal_date, max_days=30):
        """计算倍阳后不同持股天数的收益率"""
        signal_idx = df[df['日期'] == signal_date].index[0]
        returns = {}

        for days in range(1, max_days + 1):
            target_idx = signal_idx + days
            if target_idx < len(df):
                buy_price = df.iloc[signal_idx]['收盘']
                sell_price = df.iloc[target_idx]['收盘']
                returns[days] = (sell_price - buy_price) / buy_price * 100
            else:
                returns[days] = None

        return returns

    def backtest_single_stock(self, stock_code, start_date, end_date):
        """单只股票回测"""
        df = self.get_stock_data(stock_code, start_date, end_date)
        if df is None or len(df) < 50:
            return []

        signals = self.detect_double_yang(df)
        results = []

        for signal in signals:
            signal_date = signal['date']
            returns = self.calculate_returns(df, signal_date)

            for days, ret in returns.items():
                if ret is not None:
                    results.append({
                        'stock_code': stock_code,
                        'signal_date': signal_date,
                        'volume_ratio': signal['volume'] / signal['prev_volume'],
                        'amplitude': signal['amplitude'],
                        'hold_days': days,
                        'return': ret
                    })

        return results

    def run_backtest(self, stock_list, start_date, end_date):
        """运行回测"""
        all_results = []

        for i, stock_code in enumerate_with_progress(stock_list):
            # print(f"回测进度: {i+1}/{len(stock_list)} - {stock_code}")
            results = self.backtest_single_stock(stock_code, start_date, end_date)
            all_results.extend(results)

        return pd.DataFrame(all_results)

    def analyze_results(self, df: pd.DataFrame):
        """分析回测结果"""
        if df.empty:
            print("没有找到有效的倍阳信号")
            return

        # 按持股天数分组统计
        analysis = df.groupby('hold_days').agg({
            'return': ['mean', 'median', 'std', 'count',
                      lambda x: (x > 0).mean() * 100]  # 胜率
        }).round(3)

        analysis.columns = ['平均收益率%', '中位数收益率%', '标准差', '信号数量', '胜率%']

        # 找到最佳持股天数
        best_days = analysis['平均收益率%'].idxmax()
        best_return = analysis.loc[best_days, '平均收益率%']

        收益分析表 = dataframe_to_rich_table(analysis, title="倍阳后持股天数收益分析", show_footer=True)
        progress_print(收益分析表)  # 显示前15天

        progress_print(f"\n最佳持股天数: {best_days}天")
        progress_print(f"最佳平均收益率: {best_return}%")
        progress_print(f"该天数胜率: {analysis.loc[best_days, '胜率%']}%")

        return analysis

import click

@click.command(context_settings=dict(help_option_names=['-?', '--help', '-h']))
@click.option('-l', '--limit', default=100, show_default=True, help='个数限制')
def main(
    limit: int,
):
    # 初始化回测器
    backtester = DoubleYangBacktest()

    # 获取A股股票列表
    print("获取A股股票列表...")
    stock_info = ak.stock_info_a_code_name()
    I(stock_info=stock_info)
    stock_list = stock_info['code'].tolist()[:limit]  # 先用100只股票测试

    # 设置回测时间范围（2年）
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=730)).strftime('%Y%m%d')

    print(f"回测时间范围: {start_date} 至 {end_date}")
    print(f"回测股票数量: {len(stock_list)}")

    # 运行回测
    results_df = backtester.run_backtest(stock_list, start_date, end_date)

    if not results_df.empty:
        # 分析结果
        analysis = backtester.analyze_results(results_df)

        # 保存结果
        results_df.to_csv('倍阳回测结果.csv', index=False, encoding='utf-8-sig')
        analysis.to_csv('倍阳持股天数分析.csv', encoding='utf-8-sig')
        print("\n详细结果已保存到 '倍阳回测结果.csv' 和 '倍阳持股天数分析.csv'")

        # 可视化最佳持股区间
        visualize_results(analysis)
    else:
        print("没有找到有效的回测数据")

def visualize_results(analysis):
    """可视化结果"""
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns

        plt.rcParams['font.sans-serif'] = ['SimHei']
        plt.rcParams['axes.unicode_minus'] = False

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

        # 收益率曲线
        days = analysis.index[:20]
        returns = analysis['平均收益率%'][:20]
        win_rates = analysis['胜率%'][:20]

        ax1.plot(days, returns, 'b-o', linewidth=2, markersize=6, label='平均收益率')
        ax1.set_xlabel('持股天数')
        ax1.set_ylabel('平均收益率 (%)')
        ax1.set_title('倍阳后不同持股天数的平均收益率')
        ax1.grid(True, alpha=0.3)
        ax1.legend()

        # 标注最佳点
        best_day = analysis['平均收益率%'].idxmax()
        best_return = analysis.loc[best_day, '平均收益率%']
        ax1.annotate(f'最佳: {best_day}天\n收益: {best_return:.2f}%',
                    xy=(best_day, best_return),
                    xytext=(best_day+2, best_return+0.5),
                    arrowprops=dict(arrowstyle='->', color='red'))

        # 胜率曲线
        ax2.bar(days, win_rates, alpha=0.7, color='green')
        ax2.set_xlabel('持股天数')
        ax2.set_ylabel('胜率 (%)')
        ax2.set_title('倍阳后不同持股天数的胜率')
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig('倍阳持股天数分析.png', dpi=300, bbox_inches='tight')
        plt.show()

    except ImportError:
        print("如需可视化请安装matplotlib和seaborn")

if __name__ == "__main__":
    main()
