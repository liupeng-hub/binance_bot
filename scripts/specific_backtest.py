
import os
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import traceback
from collections import defaultdict

def fetch_history_range(symbol="BTCUSDT", timeframe="1m", start_str="2022-04-01", end_str="2023-04-01"):
    """
    获取指定时间范围的历史数据
    start_str, end_str: "YYYY-MM-DD"
    """
    safe_symbol = symbol.replace("/", "")
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    
    # 解析日期
    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_str, "%Y-%m-%d")
    
    filename_start = start_dt.strftime("%Y%m%d")
    filename_end = end_dt.strftime("%Y%m%d")
    
    # 检查本地缓存
    expected_file = os.path.join(data_dir, f"{safe_symbol}_{timeframe}_{filename_start}_{filename_end}.csv")
    if os.path.exists(expected_file):
        print(f"发现本地缓存: {expected_file}")
        df = pd.read_csv(expected_file)
        df['datetime'] = pd.to_datetime(df['datetime'])
        return df
        
    print(f"正在下载 {symbol} {timeframe} 数据: {start_str} 至 {end_str} ...")
    
    exchange = ccxt.binanceusdm({
        'enableRateLimit': True,
        'proxies': {
            'http': 'http://127.0.0.1:1087',
            'https': 'http://127.0.0.1:1087',
        }
    })
    
    try:
        exchange.load_markets()
    except Exception as e:
        print(f"加载市场失败: {e}")
        return pd.DataFrame()
        
    since = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    
    all_candles = []
    
    while since < end_ts:
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
            if not candles:
                break
            
            # 过滤超出结束时间的数据
            candles = [c for c in candles if c[0] < end_ts]
            if not candles:
                break
                
            all_candles.extend(candles)
            since = candles[-1][0] + 1
            
            # 进度
            current_date = datetime.fromtimestamp(candles[-1][0]/1000)
            progress = (candles[-1][0] - start_dt.timestamp()*1000) / (end_ts - start_dt.timestamp()*1000) * 100
            print(f"\r  进度: {progress:.1f}% | 当前: {current_date} | 总数: {len(all_candles)}", end="")
            
        except Exception as e:
            print(f"\n下载出错: {e}")
            time.sleep(5)
            
    print(f"\n下载完成。保存至: {expected_file}")
    df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.to_csv(expected_file, index=False)
    
    return df

def analyze_amplitude_distribution(df, timeframe):
    """
    统计振幅分布 (模拟博主逻辑: 互斥区间，且可能剔除小波动)
    """
    if len(df) == 0: return

    # 计算振幅
    df['amplitude'] = (df['high'] - df['low']) / df['open']
    df['amp_pct'] = df['amplitude'] * 100
    
    # 筛选 >= 1% 的有效波动
    valid_df = df[df['amp_pct'] >= 1.0]
    total_valid = len(valid_df)
    total_all = len(df)
    
    print(f"\n=== 周期 {timeframe} 分析 ===")
    print(f"总K线数: {total_all}")
    print(f"有效波动(>=1%)数: {total_valid} (占比 {total_valid/total_all:.2%})")
    
    if total_valid == 0:
        print("没有 >= 1% 的波动。")
        return

    print(f"\n{'振幅区间':<15} | {'次数':<10} | {'在有效波动中的占比':<15}")
    print("-" * 50)
    
    # 统计 1% - 10%
    # 1% 代表 1% <= x < 2%
    for i in range(1, 11):
        if i == 10:
            count = len(valid_df[valid_df['amp_pct'] >= 10])
            label = ">= 10%"
        else:
            count = len(valid_df[(valid_df['amp_pct'] >= i) & (valid_df['amp_pct'] < i+1)])
            label = f"{i}% - {i+1}%"
            
        ratio = count / total_valid
        print(f"{label:<15} | {count:<10} | {ratio:.2%}")

if __name__ == "__main__":
    # 指定时间段
    start_date = "2022-04-01"
    end_date = "2023-04-01"
    
    # 对比多个周期
    for tf in ["1m", "1h", "4h", "1d"]:
        df = fetch_history_range("BTCUSDT", tf, start_date, end_date)
        analyze_amplitude_distribution(df, tf)
