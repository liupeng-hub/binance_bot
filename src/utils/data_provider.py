import os
import ccxt
import pandas as pd
import time
import traceback
from datetime import datetime, timedelta
from sqlalchemy import func
from .db_manager import db_manager
from .db_models import MarketData
from sqlalchemy.dialects.postgresql import insert

def fetch_binance_history(symbol="BTCUSDT", timeframe="1m", days=365):
    """
    获取币安合约历史K线 (优先读取 PostgreSQL 数据库)
    """
    # 1. 尝试从数据库加载
    end_time_dt = datetime.utcnow()
    start_time_dt = end_time_dt - timedelta(days=days)
    
    print(f"正在检查数据库中的历史数据: {symbol} {timeframe} ({days} days)...")
    
    session = db_manager.get_session()
    try:
        # 查询数据库中的数据范围
        # 注意: 这种检查比较粗略，假设数据是连续的
        min_ts = session.query(func.min(MarketData.timestamp)).filter(
            MarketData.symbol == symbol,
            MarketData.timeframe == timeframe
        ).scalar()
        
        max_ts = session.query(func.max(MarketData.timestamp)).filter(
            MarketData.symbol == symbol,
            MarketData.timeframe == timeframe
        ).scalar()
        
        # 检查是否覆盖了请求的范围
        # 允许 1 天的容差 (对于 Start) 和 1 小时的容差 (对于 End)
        coverage_ok = False
        if min_ts and max_ts:
            db_start_ok = min_ts <= start_time_dt + timedelta(days=1)
            db_end_ok = max_ts >= end_time_dt - timedelta(hours=1)
            
            if db_start_ok and db_end_ok:
                print(f"✅ 数据库中已存在足够的数据 ({min_ts} ~ {max_ts})。直接读取...")
                
                # 读取数据
                query = session.query(MarketData).filter(
                    MarketData.symbol == symbol,
                    MarketData.timeframe == timeframe,
                    MarketData.timestamp >= start_time_dt
                ).order_by(MarketData.timestamp.asc())
                
                results = query.all()
                if results:
                    data = [{
                        'datetime': r.timestamp,
                        'open': r.open, 'high': r.high, 'low': r.low, 'close': r.close, 'volume': r.volume
                    } for r in results]
                    df = pd.DataFrame(data)
                    df.set_index('datetime', inplace=True)
                    print(f"从数据库读取了 {len(df)} 条记录。")
                    return df
            else:
                print(f"⚠️ 数据库数据不完整 (DB: {min_ts}~{max_ts} vs Req: {start_time_dt}~{end_time_dt})。准备下载...")
        else:
            print("⚠️ 数据库中无此标的数据。准备下载...")
            
    except Exception as e:
        print(f"查询数据库失败: {e}")
    finally:
        session.close()

    # 2. 如果数据库数据不足，下载数据
    print(f"正在从币安获取 {symbol} {timeframe} 历史数据 (过去 {days} 天)...")
    
    # 尝试配置本地代理，解决连接问题
    exchange_config = {
        'enableRateLimit': True,
        'verbose': False, 
        'options': {
            'defaultType': 'future'
        }
    }
    
    # 检查环境变量中的代理
    http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
    https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
    
    if http_proxy or https_proxy:
        exchange_config['proxies'] = {}
        if http_proxy:
            exchange_config['proxies']['http'] = http_proxy
        if https_proxy:
            exchange_config['proxies']['https'] = https_proxy
    
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
    
    # === 3. 保存数据到 PostgreSQL ===
    print("正在保存数据到数据库...")
    session = db_manager.get_session()
    try:
        # 批量插入/更新
        # 为了效率，我们使用 bulk_save_objects 或者 execute(insert)
        # 考虑到可能存在重复，我们需要 UPSERT
        
        objects = []
        for _, row in df.iterrows():
            objects.append({
                'timestamp': row['datetime'],
                'symbol': symbol,
                'timeframe': timeframe,
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close'],
                'volume': row['volume']
            })
            
        if objects:
            # 分批处理以避免内存溢出
            batch_size = 5000
            for i in range(0, len(objects), batch_size):
                batch = objects[i:i+batch_size]
                
                # 使用 PostgreSQL 的 ON CONFLICT 语法
                stmt = insert(MarketData).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=['timestamp', 'symbol', 'timeframe'],
                    set_={
                        'open': stmt.excluded.open,
                        'high': stmt.excluded.high,
                        'low': stmt.excluded.low,
                        'close': stmt.excluded.close,
                        'volume': stmt.excluded.volume
                    }
                )
                session.execute(stmt)
                session.commit()
                print(f"  已保存 {min(i+batch_size, len(objects))}/{len(objects)} 条...")
                
        print("✅ 数据保存完成。")
        
    except Exception as e:
        print(f"❌ 保存数据到数据库失败: {e}")
        session.rollback()
    finally:
        session.close()
    
    df.set_index('datetime', inplace=True)
    return df
