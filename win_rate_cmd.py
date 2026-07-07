#! python
# encoding: utf-8
# author: DifossChen
# version: v0.1.0
# description: 计算股票的胜率
# changes:
#  v0.0.1 (2024-06-02): 初始版本
#  v0.1.0 (2026-06-11): 重构优化，增加完整功能

import pandas as pd
import numpy as np
import threading
import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import warnings
warnings.filterwarnings('ignore')

from difoss_stock_util import *

# =================================================================================
# 数据类型定义

class SignalType(Enum):
    """信号类型"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

class OrderDirection(Enum):
    """订单方向"""
    LONG = "long"      # 做多
    SHORT = "short"    # 做空

@dataclass
class Trade:
    """交易记录"""
    stock_code: str
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    direction: OrderDirection
    quantity: int = 100
    commission: float = 0.0003  # 手续费率
    
    @property
    def profit_pct(self) -> float:
        """盈亏百分比"""
        if self.direction == OrderDirection.LONG:
            pct = (self.exit_price - self.entry_price) / self.entry_price * 100
        else:
            pct = (self.entry_price - self.exit_price) / self.entry_price * 100
        return pct - self.commission * 2 * 100
    
    @property
    def profit_amount(self) -> float:
        """盈亏金额"""
        return self.profit_pct / 100 * self.entry_price * self.quantity

@dataclass
class BacktestResult:
    """回测结果"""
    stock_code: str
    strategy_name: str
    trades: List[Trade] = field(default_factory=list)
    start_date: datetime = None
    end_date: datetime = None
    
    @property
    def total_trades(self) -> int:
        return len(self.trades)
    
    @property
    def win_trades(self) -> int:
        return sum(1 for t in self.trades if t.profit_pct > 0)
    
    @property
    def loss_trades(self) -> int:
        return sum(1 for t in self.trades if t.profit_pct <= 0)
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.win_trades / self.total_trades * 100
    
    @property
    def avg_profit_pct(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return np.mean([t.profit_pct for t in self.trades])
    
    @property
    def total_profit_pct(self) -> float:
        return sum(t.profit_pct for t in self.trades)
    
    @property
    def max_profit_pct(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return max(t.profit_pct for t in self.trades)
    
    @property
    def max_loss_pct(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return min(t.profit_pct for t in self.trades)
    
    @property
    def profit_factor(self) -> float:
        """盈利因子 = 总盈利 / 总亏损的绝对值"""
        total_profit = sum(t.profit_pct for t in self.trades if t.profit_pct > 0)
        total_loss = abs(sum(t.profit_pct for t in self.trades if t.profit_pct < 0))
        if total_loss == 0:
            return float('inf') if total_profit > 0 else 0
        return total_profit / total_loss
    
    def to_dict(self) -> dict:
        return {
            'stock_code': self.stock_code,
            'strategy': self.strategy_name,
            'total_trades': self.total_trades,
            'win_trades': self.win_trades,
            'loss_trades': self.loss_trades,
            'win_rate': self.win_rate,
            'avg_profit_pct': self.avg_profit_pct,
            'total_profit_pct': self.total_profit_pct,
            'max_profit_pct': self.max_profit_pct,
            'max_loss_pct': self.max_loss_pct,
            'profit_factor': self.profit_factor
        }

# =================================================================================
# 数据源接口

class DataSource(ABC):
    """数据源抽象基类"""
    
    _instances = {}
    _lock = threading.RLock()
    
    def __new__(cls, source_type: str, config: dict = None):
        """单例模式"""
        with cls._lock:
            if source_type not in cls._instances:
                instance = super().__new__(cls)
                cls._instances[source_type] = instance
            return cls._instances[source_type]
    
    def __init__(self, source_type: str, config: dict = None):
        if not hasattr(self, '_initialized'):
            self.source_type = source_type
            self.config = config or {}
            self._initialized = False
    
    @abstractmethod
    def init(self) -> bool:
        """初始化数据源"""
        pass
    
    @abstractmethod
    def get_market_data(self, stock_code: str, start_date: datetime, 
                       end_date: datetime, period: str = '1d') -> pd.DataFrame:
        """获取市场数据"""
        pass
    
    @abstractmethod
    def get_realtime_data(self, stock_codes: List[str]) -> pd.DataFrame:
        """获取实时数据"""
        pass
    
    def destroy(self):
        """销毁数据源"""
        pass

class TDXDataSource(DataSource):
    """通达信数据源"""
    
    def init(self) -> bool:
        if self._initialized:
            return True
        
        try:
            from tdx_quant.tqcenter import tq
            self.tq = tq
            self.tq.initialize(__file__)
            self._initialized = True
            print("✅ 通达信数据源初始化成功")
            return True
        except Exception as e:
            print(f"通达信初始化失败: {e}")
            return False
    
    def get_market_data(self, stock_code: str, start_date: datetime, 
                       end_date: datetime, period: str = '1d') -> pd.DataFrame:
        """获取通达信数据"""
        try:
            data = self.tq.get_market_data(
                stock_list=[stock_code],
                start_time=start_date,
                end_time=end_date,
                period=period
            )
            if data and len(data) > 0:
                df = pd.DataFrame(data[stock_code])
                df.index = pd.to_datetime(df.index)
                return df
            return pd.DataFrame()
        except Exception as e:
            print(f"获取数据失败 {stock_code}: {e}")
            return pd.DataFrame()
    
    def get_realtime_data(self, stock_codes: List[str]) -> pd.DataFrame:
        """获取实时数据"""
        try:
            return self.tq.get_realtime_data(stock_codes)
        except Exception as e:
            print(f"获取实时数据失败: {e}")
            return pd.DataFrame()

class MootdxDataSource(DataSource):
    """Mootdx数据源"""
    
    def init(self) -> bool:
        if self._initialized:
            return True
        
        try:
            from mootdx.quotes import Quotes
            from mootdx.reader import Reader
            
            tdx_root = self.config.get('tdx_root', 'D:/finance_tool_/new_tdx_test')
            self.client = Quotes.factory(market='std', multithread=True)
            self.reader = Reader.factory(market='std', tdxdir=tdx_root)
            self._initialized = True
            return True
        except Exception as e:
            print(f"Mootdx初始化失败: {e}")
            return False
    
    def get_market_data(self, stock_code: str, start_date: datetime,
                       end_date: datetime, period: str = '1d') -> pd.DataFrame:
        """获取Mootdx数据"""
        try:
            # 转换股票代码格式
            code = stock_code.replace('.SH', '').replace('.SZ', '')
            market = 0 if 'SH' in stock_code else 1
            
            # 获取K线数据
            data = self.client.bars(
                symbol=code,
                frequency=period,
                start=start_date.strftime('%Y%m%d'),
                end=end_date.strftime('%Y%m%d'),
                offset=0
            )
            
            if data is not None and len(data) > 0:
                df = pd.DataFrame(data)
                df['datetime'] = pd.to_datetime(df['datetime'])
                df.set_index('datetime', inplace=True)
                return df
            return pd.DataFrame()
        except Exception as e:
            print(f"获取数据失败 {stock_code}: {e}")
            return pd.DataFrame()
    
    def get_realtime_data(self, stock_codes: List[str]) -> pd.DataFrame:
        """获取实时数据"""
        try:
            quotes = []
            for code in stock_codes:
                code_num = code.replace('.SH', '').replace('.SZ', '')
                market = 0 if 'SH' in code else 1
                quote = self.client.quote(symbol=code_num, market=market)
                if quote:
                    quotes.append(quote)
            return pd.DataFrame(quotes) if quotes else pd.DataFrame()
        except Exception as e:
            print(f"获取实时数据失败: {e}")
            return pd.DataFrame()

class MT5DataSource(DataSource):
    """MT5数据源"""
    
    def init(self) -> bool:
        if self._initialized:
            return True
        
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                print("MT5初始化失败")
                return False
            self.mt5 = mt5
            self._initialized = True
            return True
        except Exception as e:
            print(f"MT5初始化失败: {e}")
            return False
    
    def get_market_data(self, stock_code: str, start_date: datetime,
                       end_date: datetime, period: str = '1d') -> pd.DataFrame:
        """获取MT5数据"""
        try:
            # MT5使用不同的周期映射
            timeframe_map = {'1d': self.mt5.TIMEFRAME_D1, '1h': self.mt5.TIMEFRAME_H1}
            timeframe = timeframe_map.get(period, self.mt5.TIMEFRAME_D1)
            
            rates = self.mt5.copy_rates_range(stock_code, timeframe, start_date, end_date)
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df.set_index('time', inplace=True)
                return df
            return pd.DataFrame()
        except Exception as e:
            print(f"获取数据失败 {stock_code}: {e}")
            return pd.DataFrame()
    
    def get_realtime_data(self, stock_codes: List[str]) -> pd.DataFrame:
        """获取实时数据"""
        try:
            quotes = []
            for code in stock_codes:
                tick = self.mt5.symbol_info_tick(code)
                if tick:
                    quotes.append({'symbol': code, 'bid': tick.bid, 'ask': tick.ask})
            return pd.DataFrame(quotes) if quotes else pd.DataFrame()
        except Exception as e:
            print(f"获取实时数据失败: {e}")
            return pd.DataFrame()
    
    def destroy(self):
        if hasattr(self, 'mt5'):
            self.mt5.shutdown()

# =================================================================================
# 策略基类

class Strategy(ABC):
    """策略抽象基类"""
    
    def __init__(self, name: str, params: dict = None):
        self.name = name
        self.params = params or {}
    
    @abstractmethod
    def on_data(self, df: pd.DataFrame, idx: int) -> SignalType:
        """根据当前数据返回信号"""
        pass
    
    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """预处理数据，计算技术指标"""
        return df
    
    def can_buy(self, df: pd.DataFrame, idx: int) -> bool:
        """判断是否可以买入"""
        return self.on_data(df, idx) == SignalType.BUY
    
    def can_sell(self, df: pd.DataFrame, idx: int) -> bool:
        """判断是否可以卖出"""
        return self.on_data(df, idx) == SignalType.SELL

class DoubleYangStrategy(Strategy):
    """倍阳策略：今日阳线且成交量是昨日的2倍以上"""
    
    def __init__(self, params: dict = None):
        super().__init__("double_yang", params)
        self.volume_ratio = params.get('volume_ratio', 2.0)
    
    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备数据，计算所需指标"""
        df = df.copy()
        df['is_yang'] = df['close'] > df['open']
        df['volume_ratio'] = df['volume'] / df['volume'].shift(1)
        return df
    
    def on_data(self, df: pd.DataFrame, idx: int) -> SignalType:
        """判断信号"""
        if idx < 1:
            return SignalType.HOLD
        
        row = df.iloc[idx]
        prev_row = df.iloc[idx - 1]
        
        # 买入信号：今天阳线，且成交量是昨天的N倍以上
        if (row['is_yang'] and 
            row['volume'] >= self.volume_ratio * prev_row['volume']):
            return SignalType.BUY
        
        # 卖出信号：跌破5日均线
        if 'ma5' in df.columns and row['close'] < row['ma5']:
            return SignalType.SELL
        
        return SignalType.HOLD

class MACrossoverStrategy(Strategy):
    """均线交叉策略：金叉买入，死叉卖出"""
    
    def __init__(self, params: dict = None):
        super().__init__("ma_cross", params)
        self.fast_period = params.get('fast_period', 5)
        self.slow_period = params.get('slow_period', 20)
    
    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算均线"""
        df = df.copy()
        df['ma_fast'] = df['close'].rolling(self.fast_period).mean()
        df['ma_slow'] = df['close'].rolling(self.slow_period).mean()
        df['ma_cross'] = (df['ma_fast'] > df['ma_slow']).astype(int)
        df['ma_cross_signal'] = df['ma_cross'].diff()
        return df
    
    def on_data(self, df: pd.DataFrame, idx: int) -> SignalType:
        """判断信号"""
        if idx < 1:
            return SignalType.HOLD
        
        signal = df.iloc[idx].get('ma_cross_signal', 0)
        
        if signal == 1:  # 金叉
            return SignalType.BUY
        elif signal == -1:  # 死叉
            return SignalType.SELL
        
        return SignalType.HOLD

class BreakoutStrategy(Strategy):
    """突破策略：突破前期高点买入"""
    
    def __init__(self, params: dict = None):
        super().__init__("breakout", params)
        self.lookback = params.get('lookback', 20)
        self.breakout_pct = params.get('breakout_pct', 0)
    
    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算前期高点"""
        df = df.copy()
        df['high_n'] = df['high'].rolling(self.lookback).max()
        df['breakout'] = df['close'] > df['high_n'].shift(1) * (1 + self.breakout_pct / 100)
        return df
    
    def on_data(self, df: pd.DataFrame, idx: int) -> SignalType:
        """判断信号"""
        if idx < self.lookback:
            return SignalType.HOLD
        
        if df.iloc[idx]['breakout']:
            return SignalType.BUY
        
        # 止损：跌破10日均线
        if 'ma10' in df.columns and df.iloc[idx]['close'] < df.iloc[idx]['ma10']:
            return SignalType.SELL
        
        return SignalType.HOLD

# 策略注册表
STRATEGY_REGISTRY = {
    'double_yang': DoubleYangStrategy,
    'ma_cross': MACrossoverStrategy,
    'breakout': BreakoutStrategy,
}

# =================================================================================
# 回测引擎

class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, data_source: DataSource, console: Console = None):
        self.data_source = data_source
        self.console = console or Console()
    
    def run(self, stock_code: str, strategy: Strategy, 
            start_date: datetime, end_date: datetime,
            initial_capital: float = 100000,
            position_pct: float = 1.0) -> BacktestResult:
        """
        运行回测
        stock_code: 股票代码
        strategy: 策略实例
        start_date: 开始日期
        end_date: 结束日期
        initial_capital: 初始资金
        position_pct: 每次开仓仓位比例
        """
        # 获取数据
        df = self.data_source.get_market_data(stock_code, start_date, end_date)
        
        if df.empty:
            self.console.print(f"[red]未获取到 {stock_code} 的数据[/red]")
            return BacktestResult(stock_code, strategy.name)
        
        # 准备策略数据
        df = strategy.prepare_data(df)
        
        # 运行回测
        trades = []
        position = None
        capital = initial_capital
        
        for idx in range(len(df)):
            current_date = df.index[idx]
            current_price = df.iloc[idx]['close']
            
            # 检查卖出信号
            if position is not None and strategy.can_sell(df, idx):
                trade = Trade(
                    stock_code=stock_code,
                    entry_date=position['entry_date'],
                    exit_date=current_date,
                    entry_price=position['entry_price'],
                    exit_price=current_price,
                    direction=OrderDirection.LONG
                )
                trades.append(trade)
                capital += trade.profit_amount
                position = None
            
            # 检查买入信号
            if position is None and strategy.can_buy(df, idx):
                position = {
                    'entry_date': current_date,
                    'entry_price': current_price,
                }
        
        # 返回结果
        result = BacktestResult(stock_code, strategy.name, trades, start_date, end_date)
        return result
    
    def run_multiple(self, stock_codes: List[str], strategy: Strategy,
                    start_date: datetime, end_date: datetime) -> List[BacktestResult]:
        """批量回测多只股票"""
        results = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console
        ) as progress:
            task = progress.add_task("[cyan]回测中...", total=len(stock_codes))
            
            for code in stock_codes:
                result = self.run(code, strategy, start_date, end_date)
                if result.total_trades > 0:
                    results.append(result)
                progress.update(task, advance=1)
        
        return results

# =================================================================================
# Click 命令

def create_data_source(ctx, source_type: str):
    """创建数据源"""
    cfg = ctx.obj.get('cfg', {})
    data_source_config = cfg.get('data_source', {})
    
    if source_type == 'tdx':
        ds = TDXDataSource(source_type, data_source_config)
    elif source_type == 'mootdx':
        ds = MootdxDataSource(source_type, data_source_config)
    elif source_type == 'mt5':
        ds = MT5DataSource(source_type, data_source_config)
    else:
        raise ValueError(f"未知数据源: {source_type}")
    
    if ds.init():
        ctx.obj['data_source'] = ds
        return ds
    return None

@click_util.command_with_abbrev(abbrev='bt', context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--stock', '-s', 'stocks', multiple=True, required=True, help='股票代码')
@click.option('--strategy', '-g', 'strategy', type=click.Choice(list(STRATEGY_REGISTRY.keys())), 
              default='ma_cross', help='策略名称')
@click.option('--start-date', '-st', type=click.DateTime(formats=["%Y%m%d"]), 
              default=lambda: datetime.now() - timedelta(days=365), help='开始时间 YYYYMMDD')
@click.option('--end-date', '-et', type=click.DateTime(formats=["%Y%m%d"]), 
              default=lambda: datetime.now(), help='结束时间 YYYYMMDD')
@click.option('--source-type', '-t', 'source_type', type=click.Choice(['tdx', 'mootdx', 'mt5']),
              default='mootdx', help='数据源类型')
@click.pass_context
def backtest_cmd(ctx, stocks, strategy, start_date, end_date, source_type):
    """回测策略胜率"""
    console = ctx.obj.get('console', Console())
    
    # 创建数据源
    ds = create_data_source(ctx, source_type)
    if not ds:
        console.print("[red]数据源初始化失败[/red]")
        return
    
    # 创建策略
    strategy_class = STRATEGY_REGISTRY.get(strategy)
    if not strategy_class:
        console.print(f"[red]未知策略: {strategy}[/red]")
        return
    
    strategy_instance = strategy_class()
    
    # 运行回测
    engine = BacktestEngine(ds, console)
    results = engine.run_multiple(list(stocks), strategy_instance, start_date, end_date)
    
    if not results:
        console.print("[yellow]没有产生任何交易记录[/yellow]")
        return
    
    # 显示结果表格
    table = Table(title=f"📊 策略回测结果 - {strategy}")
    table.add_column("股票代码", style="cyan")
    table.add_column("交易次数", justify="right")
    table.add_column("胜率", justify="right")
    table.add_column("平均盈亏%", justify="right")
    table.add_column("总盈亏%", justify="right")
    table.add_column("最大盈利%", justify="right")
    table.add_column("最大亏损%", justify="right")
    table.add_column("盈利因子", justify="right")
    
    # 汇总统计
    total_wins = 0
    total_trades = 0
    
    for r in sorted(results, key=lambda x: x.win_rate, reverse=True):
        win_rate_color = "green" if r.win_rate >= 50 else "yellow" if r.win_rate >= 40 else "red"
        table.add_row(
            r.stock_code,
            str(r.total_trades),
            f"[{win_rate_color}]{r.win_rate:.1f}%[/{win_rate_color}]",
            f"{r.avg_profit_pct:+.2f}",
            f"{r.total_profit_pct:+.2f}",
            f"{r.max_profit_pct:+.2f}",
            f"{r.max_loss_pct:+.2f}",
            f"{r.profit_factor:.2f}"
        )
        total_wins += r.win_trades
        total_trades += r.total_trades
    
    console.print(table)
    
    # 显示总体统计
    if total_trades > 0:
        overall_win_rate = total_wins / total_trades * 100
        console.print(f"\n[bold]📈 总体统计:[/bold] 总交易次数={total_trades}, "
                     f"总盈利次数={total_wins}, 总体胜率={overall_win_rate:.1f}%")

@click_util.command_with_abbrev(abbrev='xg', context_settings={'help_option_names': ['-?', '--help', '-h']})
@click.option('--strategy', '-g', 'strategy', type=click.Choice(list(STRATEGY_REGISTRY.keys())),
              required=True, help='选股策略')
@click.option('--source-type', '-t', 'source_type', type=click.Choice(['tdx', 'mootdx', 'mt5']),
              default='mootdx', help='数据源类型')
@click.option('--top-n', '-n', default=20, help='返回前N只股票')
@click.pass_context
def xg_cmd(ctx, strategy, source_type, top_n):
    """选股"""
    console = ctx.obj.get('console', Console())
    
    # 创建数据源
    ds = create_data_source(ctx, source_type)
    if not ds:
        console.print("[red]数据源初始化失败[/red]")
        return
    
    # 获取股票列表（从配置或缓存）
    stock_list = ctx.obj.get('stock_list', [])
    if not stock_list:
        console.print("[yellow]请先设置股票池[/yellow]")
        return
    
    # 创建策略
    strategy_class = STRATEGY_REGISTRY.get(strategy)
    if not strategy_class:
        console.print(f"[red]未知策略: {strategy}[/red]")
        return
    
    strategy_instance = strategy_class()
    
    # 选股
    selected = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)  # 获取最近30天数据
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]选股中...", total=len(stock_list))
        
        for code in stock_list:
            df = ds.get_market_data(code, start_date, end_date)
            if not df.empty:
                df = strategy_instance.prepare_data(df)
                if strategy_instance.can_buy(df, len(df) - 1):
                    selected.append(code)
            progress.update(task, advance=1)
    
    # 显示结果
    if selected:
        table = Table(title=f"📋 选股结果 - {strategy}")
        table.add_column("序号", style="cyan", justify="right")
        table.add_column("股票代码", style="green")
        
        for i, code in enumerate(selected[:top_n], 1):
            table.add_row(str(i), code)
        
        console.print(table)
        console.print(f"\n[green]共选出 {len(selected)} 只股票[/green]")
        
        # 保存选股结果
        ctx.obj['xg_result'] = selected
    else:
        console.print("[yellow]未选出符合条件的股票[/yellow]")

@click.command(name='report', help='生成胜率分析报告')
@click.option('--stock', '-s', 'stocks', multiple=True, required=True, help='股票代码')
@click.option('--start-date', '-st', type=click.DateTime(formats=["%Y%m%d"]),
              default=lambda: datetime.now() - timedelta(days=365*3), help='开始时间')
@click.option('--end-date', '-et', type=click.DateTime(formats=["%Y%m%d"]),
              default=lambda: datetime.now(), help='结束时间')
@click.option('--source-type', '-t', 'source_type', type=click.Choice(['tdx', 'mootdx', 'mt5']),
              default='mootdx', help='数据源类型')
@click.pass_context
def report_cmd(ctx, stocks, start_date, end_date, source_type):
    """生成详细的分析报告"""
    console = ctx.obj.get('console', Console())
    
    # 创建数据源
    ds = create_data_source(ctx, source_type)
    if not ds:
        console.print("[red]数据源初始化失败[/red]")
        return
    
    # 对所有策略进行回测
    all_results = {}
    
    for strategy_name in STRATEGY_REGISTRY.keys():
        strategy_class = STRATEGY_REGISTRY[strategy_name]
        strategy_instance = strategy_class()
        
        engine = BacktestEngine(ds, console)
        results = engine.run_multiple(list(stocks), strategy_instance, start_date, end_date)
        all_results[strategy_name] = results
    
    # 生成综合报告
    console.print(f"\n[bold cyan]📊 胜率分析报告[/bold cyan]")
    console.print(f"分析期间: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
    console.print(f"股票数量: {len(stocks)}")
    console.print()
    
    # 策略对比表格
    comp_table = Table(title="策略对比")
    comp_table.add_column("策略", style="cyan")
    comp_table.add_column("总交易次数", justify="right")
    comp_table.add_column("总胜率", justify="right")
    comp_table.add_column("平均盈亏%", justify="right")
    comp_table.add_column("总盈亏%", justify="right")
    comp_table.add_column("盈利因子", justify="right")
    
    for strategy_name, results in all_results.items():
        if not results:
            continue
        
        total_trades = sum(r.total_trades for r in results)
        total_wins = sum(r.win_trades for r in results)
        overall_win_rate = total_wins / total_trades * 100 if total_trades > 0 else 0
        avg_profit = np.mean([r.avg_profit_pct for r in results if r.total_trades > 0])
        total_profit = sum(r.total_profit_pct for r in results)
        avg_factor = np.mean([r.profit_factor for r in results if r.total_trades > 0])
        
        win_rate_color = "green" if overall_win_rate >= 50 else "yellow" if overall_win_rate >= 40 else "red"
        comp_table.add_row(
            strategy_name,
            str(total_trades),
            f"[{win_rate_color}]{overall_win_rate:.1f}%[/{win_rate_color}]",
            f"{avg_profit:+.2f}",
            f"{total_profit:+.2f}",
            f"{avg_factor:.2f}"
        )
    
    console.print(comp_table)
