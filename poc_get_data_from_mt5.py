import MetaTrader5 as mt5
import pandas as pd
import os
import time

def fetch_deep_history(symbol="XAGUSD.", timeframe=mt5.TIMEFRAME_M1, total_needed=5000000):
    # 1. 初始化
    if not mt5.initialize():
        print(f"MT5 初始化失败, 错误码 = {mt5.last_error()}")
        return

    # 2. 激活品种
    mt5.symbol_select(symbol, True)
    
    all_chunks = []
    start_index = 0
    chunk_size = 100000  # 每次拉取 10 万条
    
    print(f"开始分页拉取 {symbol} 历史数据...")

    while start_index < total_needed:
        # copy_rates_from_pos(品种, 周期, 起始索引, 数量)
        # 索引 0 是最旧的吗？不，0 是最新的（当前 K 线），索引越大越久远
        rates = mt5.copy_rates_from_pos(symbol, timeframe, start_index, chunk_size)
        
        if rates is None or len(rates) == 0:
            print(f"在索引 {start_index} 处无法获取更多数据，可能已达服务器上限。")
            break
            
        df_chunk = pd.DataFrame(rates)
        all_chunks.append(df_chunk)
        
        # 打印进度
        current_earliest = pd.to_datetime(df_chunk['time'].min(), unit='s')
        print(f"已拉取索引 [{start_index} 至 {start_index + len(rates)}]，最远到达: {current_earliest}")
        
        # 增加起始位置，准备拉取更老的数据
        start_index += len(rates)
        
        # 如果拉到的数量少于请求的数量，说明到头了
        if len(rates) < chunk_size:
            print("到达数据末尾。")
            break
            
        # 给终端一点喘息时间去解压数据
        time.sleep(0.1)

    # 3. 合并数据
    if not all_chunks:
        print("未获取到任何数据。")
        mt5.shutdown()
        return

    df = pd.concat(all_chunks)
    
    # 4. 转换时间并清洗
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.rename(columns={'tick_volume': 'volume'}, inplace=True)
    df = df[['time', 'open', 'high', 'low', 'close', 'volume']]
    
    # 去重（防止分页重叠）并按时间正序排列
    df = df.drop_duplicates(subset=['time']).sort_values('time')
    df.set_index('time', inplace=True)

    print(f"\n--- 获取成功 ---")
    print(f"总条数: {len(df)}")
    print(f"时间跨度: {df.index.min()} 至 {df.index.max()}")

    # 5. 保存
    output_path = f"D:\\quant\\POC\\{symbol.replace('.', '_')}_M1_Deep.parquet"
    df.to_parquet(output_path, engine='pyarrow', compression='snappy')
    print(f"数据已存至: {output_path}")

    mt5.shutdown()

if __name__ == "__main__":
    fetch_deep_history("EURUSD.")