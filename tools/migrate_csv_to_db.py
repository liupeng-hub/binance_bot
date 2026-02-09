import os
import glob
import pandas as pd
from datetime import datetime
from src.utils.db_manager import db_manager
from src.utils.db_models import MarketData

def migrate_csv_to_db():
    """
    将本地 data/ 目录下的 CSV K线数据迁移到数据库 (MarketData 表)
    """
    # 1. 检查数据库连接
    session = db_manager.get_session()
    try:
        # 简单测试连接
        session.execute("SELECT 1")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return

    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data_dir = os.path.join(root_dir, 'data')
    
    # 查找所有 CSV
    csv_files = glob.glob(os.path.join(data_dir, "*_*_*.csv"))
    print(f"Found {len(csv_files)} CSV files to migrate.")
    
    for file_path in csv_files:
        try:
            filename = os.path.basename(file_path)
            # 解析文件名: SYMBOL_TIMEFRAME_START_END.csv
            # e.g. BTCUSDT_1h_20230101_20230201.csv
            parts = filename.split('_')
            if len(parts) < 4:
                print(f"⚠️ Skipping invalid filename: {filename}")
                continue
                
            symbol = parts[0]
            # 还原 symbol 格式 (e.g. BTCUSDT -> BTC/USDT)
            # 这里简单处理，假设是 USDT 结尾
            if symbol.endswith('USDT'):
                symbol = f"{symbol[:-4]}/USDT"
            
            timeframe = parts[1]
            
            print(f"Migrating {filename} (Symbol: {symbol}, TF: {timeframe})...")
            
            # 读取 CSV
            df = pd.read_csv(file_path)
            
            # 标准化列名
            # 期望: time/timestamp, open, high, low, close, volume
            cols = df.columns.tolist()
            rename_map = {}
            if 'datetime' in cols: rename_map['datetime'] = 'timestamp'
            elif 'time' in cols: rename_map['time'] = 'timestamp'
            
            df.rename(columns=rename_map, inplace=True)
            
            # 转换时间戳
            if 'timestamp' in df.columns:
                # 检查是否是字符串或数字
                first_val = df['timestamp'].iloc[0]
                if isinstance(first_val, str):
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                elif isinstance(first_val, (int, float)):
                    # 假设是毫秒 (Binance standard)
                    if first_val > 10**11: 
                        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    else:
                        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            # 批量插入
            # 为了性能，使用 bulk_insert_mappings
            records = []
            for _, row in df.iterrows():
                records.append({
                    'timestamp': row['timestamp'],
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume']
                })
                
                # 分批提交 (每 10000 条)
                if len(records) >= 10000:
                    session.bulk_insert_mappings(MarketData, records)
                    session.commit()
                    records = []
            
            # 提交剩余的
            if records:
                session.bulk_insert_mappings(MarketData, records)
                session.commit()
                
            print(f"✅ Imported {len(df)} rows from {filename}")
            
        except Exception as e:
            print(f"❌ Error processing {file_path}: {e}")
            session.rollback()
            
    session.close()
    print("Migration completed.")

if __name__ == "__main__":
    # 初始化 DB (创建表)
    db_manager.init_db()
    migrate_csv_to_db()
