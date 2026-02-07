import os
import ccxt
import pandas as pd
import time
import traceback
from datetime import datetime, timedelta

def fetch_binance_history(symbol="BTCUSDT", timeframe="1m", days=365):
    """
    获取币安合约历史K线 (优先读取本地缓存)
    """
    safe_symbol = symbol.replace("/", "")
    # 数据目录在 core 上一级的 data 目录
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    
    # 预期时间范围
    end_time_dt = datetime.now()
    start_time_dt = end_time_dt - timedelta(days=days)
    
    existing_file = None
    for f in os.listdir(data_dir):
        if f.startswith(f"{safe_symbol}_{timeframe}_") and f.endswith(".csv"):
            existing_file = os.path.join(data_dir, f)
            break
            
    if existing_file:
        print(f"发现本地缓存数据: {existing_file}")
        print("正在读取本地数据...")
        df = pd.read_csv(existing_file)
        df['datetime'] = pd.to_datetime(df['datetime'])
        # 简单校验一下数据长度是否足够 (粗略)
        if len(df) > 0:
            print(f"本地数据读取成功。条数: {len(df)}")
            return df
        else:
            print("本地数据为空，重新下载。")
    
    print(f"正在从币安获取 {symbol} {timeframe} 历史数据 (过去 {days} 天)...")
    
    # 尝试配置本地代理，解决连接问题
    exchange_config = {
        'enableRateLimit': True,
        'verbose': False, 
        'proxies': {
            'http': 'http://127.0.0.1:1087',
            'https': 'http://127.0.0.1:1087',
        },
        'options': {
            'defaultType': 'future'
        }
    }
    
    exchange = ccxt.binanceusdm(exchange_config)
    
    # 加载市场信息 (必须!)
    try:
        print("正在加载市场信息...")
        exchange.load_markets()
    except Exception as e:
        print(f"加载市场信息失败: {e}")
        return pd.DataFrame() # 提前返回
    
    # 计算开始时间
    start_time = datetime.now() - timedelta(days=days)
    since = int(start_time.timestamp() * 1000)
    end_time = exchange.milliseconds()
    
    all_candles = []
    retry_count = 0
    
    while since < end_time:
        try:
            # 每次获取 1000 条 (Binance 最大限制)
            candles = exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
            if not candles:
                break
            
            all_candles.extend(candles)
            
            # 更新下一次获取的起点
            since = candles[-1][0] + 1 
            
            # 打印进度
            current_date = datetime.fromtimestamp(candles[-1][0]/1000)
            progress = (candles[-1][0] - start_time.timestamp()*1000) / (end_time - start_time.timestamp()*1000) * 100
            print(f"\r  [{progress:.1f}%] 已获取至: {current_date} | 条数: {len(all_candles)}", end="")
            
            # 如果数据已经是最近的，停止
            if since > end_time - 60000: # 1分钟内
                break
                
            retry_count = 0 # 重置重试计数
            
        except Exception as e:
            print(f"\n获取数据出错: {e}")
            retry_count += 1
            if retry_count > 5:
                print("重试多次失败，停止获取。")
                break
            time.sleep(5) # 出错后多等一会
            
    print(f"\n下载完成。总K线数: {len(all_candles)}")
    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # === 保存数据到 CSV ===
    start_str = df['datetime'].min().strftime("%Y%m%d")
    end_str = df['datetime'].max().strftime("%Y%m%d")
    filename = f"{safe_symbol}_{timeframe}_{start_str}_{end_str}.csv"
    file_path = os.path.join(data_dir, filename)
    
    df.to_csv(file_path, index=False)
    print(f"数据已保存至: {file_path}")
    
    return df
