import os
import glob
import pandas as pd
import json
from .db_manager import db_manager
from .db_models import MarketData

def load_kline_data(symbol, start_ts=None, end_ts=None, limit=10000, timeframe=None):
    """
    加载指定标的的 K 线数据，支持时间范围筛选
    逻辑：从 PostgreSQL 数据库加载
    """
    df_db = pd.DataFrame()

        # --- 从数据库加载 ---
    try:
        session = db_manager.get_session()
        query = session.query(MarketData).filter(MarketData.symbol == symbol)
        if timeframe:
            query = query.filter(MarketData.timeframe == timeframe)
        if start_ts:
            query = query.filter(MarketData.timestamp >= pd.to_datetime(start_ts, unit='s'))
        if end_ts:
            query = query.filter(MarketData.timestamp <= pd.to_datetime(end_ts, unit='s'))
            
        # Optimize: Limit columns to reduce network/memory usage
        results = query.with_entities(
            MarketData.timestamp, MarketData.open, MarketData.high, 
            MarketData.low, MarketData.close, MarketData.volume
        ).order_by(MarketData.timestamp.asc()).all()
        
        session.close()
        
        if results:
            db_list = [{
                'time': int(r.timestamp.timestamp()),
                'open': float(r.open), 'high': float(r.high), 
                'low': float(r.low), 'close': float(r.close), 
                'volume': float(r.volume)
            } for r in results]
            df_db = pd.DataFrame(db_list)
    except Exception as e:
        print(f"Error loading data from DB: {e}")
        pass

    if df_db.empty:
        # 如果数据库没有找到该周期的数据，且请求的不是 1m，尝试使用 TimescaleDB time_bucket 或 Pandas resample
        if timeframe and timeframe != '1m':
            # 1. 尝试 TimescaleDB 聚合查询 (性能最佳)
            try:
                # 映射 Timeframe 到 TimescaleDB interval 格式
                # 3m -> '3 minutes', 1h -> '1 hour', 1d -> '1 day'
                pg_interval = None
                if timeframe.endswith('m'):
                    pg_interval = f"{timeframe[:-1]} minutes"
                elif timeframe.endswith('h'):
                    pg_interval = f"{timeframe[:-1]} hours"
                elif timeframe.endswith('d'):
                    pg_interval = f"{timeframe[:-1]} days"
                
                if pg_interval:
                    session = db_manager.get_session()
                    
                    # 构造聚合 SQL
                    # time_bucket(interval, timestamp)
                    # FIRST/LAST 聚合需要 timestamp 排序
                    # 注意: FIRST/LAST 是 TimescaleDB 特有函数
                    sql = f"""
                        SELECT
                            time_bucket('{pg_interval}', timestamp) AS bucket,
                            FIRST(open, timestamp) as open,
                            MAX(high) as high,
                            MIN(low) as low,
                            LAST(close, timestamp) as close,
                            SUM(volume) as volume
                        FROM market_data
                        WHERE symbol = :symbol AND timeframe = '1m'
                    """
                    params = {'symbol': symbol}
                    
                    if start_ts:
                        sql += " AND timestamp >= to_timestamp(:start_ts)"
                        params['start_ts'] = start_ts
                    if end_ts:
                        sql += " AND timestamp <= to_timestamp(:end_ts)"
                        params['end_ts'] = end_ts
                        
                    sql += " GROUP BY bucket ORDER BY bucket DESC LIMIT :limit"
                    params['limit'] = limit
                    
                    from sqlalchemy import text
                    result_proxy = session.execute(text(sql), params)
                    results = result_proxy.fetchall()
                    session.close()
                    
                    if results:
                        # 转换回 DataFrame 格式 (注意 SQL ORDER BY DESC，需要反转)
                        db_list = [{
                            'time': int(r.bucket.timestamp()),
                            'open': float(r.open), 'high': float(r.high), 
                            'low': float(r.low), 'close': float(r.close), 
                            'volume': float(r.volume)
                        } for r in reversed(results)]
                        return pd.DataFrame(db_list)
            
            except Exception as e:
                # print(f"TimescaleDB time_bucket query failed (fallback to pandas): {e}")
                pass # Silently fail to fallback

            # 2. Pandas 内存重采样 (后备方案)
            try:
                # Calculate multiplier based on timeframe to avoid fetching too much data
                # e.g. 5m needs 5x 1m data, not 60x
                # Improved multiplier logic for larger timeframes
                multiplier = 60
                if timeframe.endswith('m'):
                    multiplier = int(timeframe[:-1])
                elif timeframe.endswith('h'):
                    multiplier = int(timeframe[:-1]) * 60
                elif timeframe.endswith('d'):
                    multiplier = int(timeframe[:-1]) * 1440
                elif timeframe.endswith('w'):
                    multiplier = int(timeframe[:-1]) * 10080
                elif timeframe.endswith('M'):
                    multiplier = 43200 # approx 30 days
                
                # 尝试加载 1m 数据
                df_1m = load_kline_data(symbol, start_ts, end_ts, limit=limit*multiplier, timeframe='1m')
                if not df_1m.empty:
                    # 重采样逻辑
                    # 1. 设置索引
                    df_1m['datetime'] = pd.to_datetime(df_1m['time'], unit='s')
                    df_1m.set_index('datetime', inplace=True)
                    
                    # 2. 定义重采样规则
                    rule_map = {
                        '3m': '3min', '5m': '5min', '15m': '15min', 
                        '30m': '30min', '1h': '1H', '2h': '2H', 
                        '4h': '4H', '6h': '6H', '12h': '12H', '1d': '1D',
                        '3d': '3D', '1w': '1W', '1M': '1ME' # 1W for Weekly, 1ME for Month End
                    }
                    
                    # Support custom minute/hour input (e.g., '45m', '3h')
                    if timeframe not in rule_map:
                        if timeframe.endswith('m'):
                            rule_map[timeframe] = timeframe.replace('m', 'min')
                        elif timeframe.endswith('h'):
                            rule_map[timeframe] = timeframe.replace('h', 'H')
                        elif timeframe.endswith('d'):
                            rule_map[timeframe] = timeframe.replace('d', 'D')
                        elif timeframe.endswith('w'):
                            rule_map[timeframe] = timeframe.replace('w', 'W')
                    
                    rule = rule_map.get(timeframe)
                    
                    if rule:
                        # 3. Resample OHLCV
                        df_resampled = df_1m.resample(rule).agg({
                            'open': 'first',
                            'high': 'max',
                            'low': 'min',
                            'close': 'last',
                            'volume': 'sum'
                        }).dropna()
                        
                        # 4. 恢复格式
                        df_resampled['time'] = df_resampled.index.astype(int) // 10 ** 9
                        df_resampled.reset_index(drop=True, inplace=True)
                        
                        # 5. Handle NaN
                        df_resampled = df_resampled.where(pd.notnull(df_resampled), None)
                        
                        return df_resampled.tail(limit)
            except Exception as e:
                print(f"Resample failed: {e}")
        
        # If still empty, try fetching from CCXT (Live)
        if timeframe:
            try:
                # Use a default exchange instance (assuming Binance public API works without keys)
                # Or use one from db if available? 
                # Let's try anonymous fetch for market data
                import ccxt
                exchange = ccxt.binanceusdm({'enableRateLimit': True}) 
                # Map timeframe
                since = int(start_ts * 1000) if start_ts else None
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
                
                if ohlcv:
                    data_list = [{
                        'time': int(x[0]/1000),
                        'open': x[1], 'high': x[2], 'low': x[3], 'close': x[4], 'volume': x[5]
                    } for x in ohlcv]
                    
                    # Optional: Cache to DB? Yes, asynchronously ideally.
                    # For now just return
                    return pd.DataFrame(data_list)
            except Exception as e:
                print(f"CCXT fetch failed: {e}")

        return pd.DataFrame()
        
    df = df_db.drop_duplicates(subset=['time'], keep='last')
    df = df.sort_values('time')

    # --- 筛选时间范围和限制 ---
    if start_ts:
        df = df[df['time'] >= start_ts]
    if end_ts:
        df = df[df['time'] <= end_ts]

    # Handle NaN values globally for the DataFrame
    # Lightweight Charts does not support NaN in JSON
    # We replace NaN with None (which becomes null in JSON)
    df = df.where(pd.notnull(df), None)
        
    return df.tail(limit)

def calculate_indicators(df, strategy_name=None, config_json=None, requested_indicators=None):
    """
    根据策略类型或请求的指标列表，计算指标并返回 Lightweight Charts 格式的 Series
    
    Args:
        df: DataFrame with OHLCV data
        strategy_name: (Optional) Strategy name for strategy-specific indicators
        config_json: (Optional) Strategy config
        requested_indicators: (Optional) List of dicts, e.g. [{'type': 'SMA', 'period': 20}]
        
    Returns:
        (main_overlays, sub_charts)
    """
    if df.empty:
        return [], []
        
    main_overlays = []
    sub_charts = []
    config = {}
    try:
        full_config = json.loads(config_json) if config_json else {}
        config = full_config.get('params', full_config)
    except:
        pass

    # Helper to add main overlay
    def add_main(type_, data, options):
        main_overlays.append({"type": type_, "data": data, "options": options})

    # Helper to add sub chart
    def add_sub(height, series_list):
        sub_charts.append({"height": height, "series": series_list})

    # 1. Strategy-Specific Indicators (Legacy Mode)
    if strategy_name:
        # SMA Cross
        if 'SMA' in strategy_name:
            fast = int(config.get('fast_period', 10))
            slow = int(config.get('slow_period', 30))
            requested_indicators = requested_indicators or []
            requested_indicators.append({'type': 'SMA', 'period': fast, 'color': '#2962FF'})
            requested_indicators.append({'type': 'SMA', 'period': slow, 'color': '#FF6D00'})

        # Bollinger Bands
        elif 'BBands' in strategy_name:
            period = int(config.get('period', 20))
            dev = float(config.get('devfactor', 2.0))
            requested_indicators = requested_indicators or []
            requested_indicators.append({'type': 'BBands', 'period': period, 'dev': dev})

        # Dual Thrust
        elif 'DualThrust' in strategy_name:
            # Special case, logic is complex, keep it here or migrate?
            # Keeping it here for now as it's very custom
            period = int(config.get('period', 5))
            k1 = float(config.get('k1', 0.5))
            k2 = float(config.get('k2', 0.5))
            
            df['hh'] = df['high'].rolling(window=period).max()
            df['hc'] = df['close'].rolling(window=period).max()
            df['ll'] = df['low'].rolling(window=period).min()
            df['lc'] = df['close'].rolling(window=period).min()
            
            df['r1'] = df['hh'] - df['lc']
            df['r2'] = df['hc'] - df['ll']
            df['range'] = df[['r1', 'r2']].max(axis=1).shift(1)
            
            df['buy_line'] = df['open'] + k1 * df['range']
            df['sell_line'] = df['open'] - k2 * df['range']
            
            buy_data = df[['time', 'buy_line']].rename(columns={'buy_line': 'value'}).dropna().to_dict('records')
            sell_data = df[['time', 'sell_line']].rename(columns={'sell_line': 'value'}).dropna().to_dict('records')

            add_main('Line', buy_data, {"color": 'green', "lineWidth": 1, "title": "Buy Line"})
            add_main('Line', sell_data, {"color": 'red', "lineWidth": 1, "title": "Sell Line"})

        # RSI
        elif 'RSI' in strategy_name:
            period = int(config.get('period', 14))
            requested_indicators = requested_indicators or []
            requested_indicators.append({'type': 'RSI', 'period': period})

        # MACD
        elif 'MACD' in strategy_name:
            requested_indicators = requested_indicators or []
            requested_indicators.append({'type': 'MACD', 
                'fast': int(config.get('fast_period', 12)),
                'slow': int(config.get('slow_period', 26)),
                'signal': int(config.get('signal_period', 9))
            })

    # 2. Generic Indicator Factory
    if requested_indicators:
        # Deduplicate based on signature to avoid double adding
        # Simple set check could be added here
        
        for ind in requested_indicators:
            itype = ind.get('type')
            
            if itype == 'SMA' or itype == 'MA':
                period = int(ind.get('period', 20))
                color = ind.get('color', '#2962FF')
                col_name = f'sma_{period}'
                df[col_name] = df['close'].rolling(window=period).mean()
                data = df[['time', col_name]].rename(columns={col_name: 'value'}).dropna().to_dict('records')
                if data:
                    add_main('Line', data, {"color": color, "lineWidth": 2, "title": f"MA {period}"})
            
            elif itype == 'EMA':
                period = int(ind.get('period', 20))
                color = ind.get('color', '#FF6D00')
                col_name = f'ema_{period}'
                df[col_name] = df['close'].ewm(span=period, adjust=False).mean()
                data = df[['time', col_name]].rename(columns={col_name: 'value'}).dropna().to_dict('records')
                if data:
                    add_main('Line', data, {"color": color, "lineWidth": 2, "title": f"EMA {period}"})

            elif itype == 'BBands':
                period = int(ind.get('period', 20))
                dev = float(ind.get('dev', 2.0))
                
                sma = df['close'].rolling(window=period).mean()
                std = df['close'].rolling(window=period).std()
                upper = sma + (std * dev)
                lower = sma - (std * dev)
                
                # Convert to records
                up_data = pd.DataFrame({'time': df['time'], 'value': upper}).dropna().to_dict('records')
                lo_data = pd.DataFrame({'time': df['time'], 'value': lower}).dropna().to_dict('records')
                mid_data = pd.DataFrame({'time': df['time'], 'value': sma}).dropna().to_dict('records')
                
                if mid_data:
                    add_main('Line', up_data, {"color": 'rgba(0, 150, 136, 0.5)', "lineWidth": 1, "title": "BB Up"})
                    add_main('Line', lo_data, {"color": 'rgba(0, 150, 136, 0.5)', "lineWidth": 1, "title": "BB Low"})
                    add_main('Line', mid_data, {"color": 'rgba(0, 150, 136, 0.5)', "lineWidth": 1, "lineStyle": 2, "title": "BB Mid"})

            elif itype == 'RSI':
                period = int(ind.get('period', 14))
                delta = df['close'].diff()
                up = delta.clip(lower=0)
                down = -1 * delta.clip(upper=0)
                ma_up = up.ewm(alpha=1/period, adjust=False).mean()
                ma_down = down.ewm(alpha=1/period, adjust=False).mean()
                rs = ma_up / ma_down
                rsi = 100 - (100 / (1 + rs))
                
                data = pd.DataFrame({'time': df['time'], 'value': rsi}).dropna().to_dict('records')
                if data:
                    add_sub(150, [{"type": 'Line', "data": data, "options": {"color": '#7E57C2', "lineWidth": 1, "title": f"RSI {period}"}}])

            elif itype == 'MACD':
                fast = int(ind.get('fast', 12))
                slow = int(ind.get('slow', 26))
                signal = int(ind.get('signal', 9))
                
                ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
                ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
                diff = ema_fast - ema_slow
                dea = diff.ewm(span=signal, adjust=False).mean()
                macd = 2 * (diff - dea)
                
                macd_data = pd.DataFrame({'time': df['time'], 'value': macd}).dropna().to_dict('records')
                diff_data = pd.DataFrame({'time': df['time'], 'value': diff}).dropna().to_dict('records')
                dea_data = pd.DataFrame({'time': df['time'], 'value': dea}).dropna().to_dict('records')
                
                if macd_data:
                    series = [
                        {"type": 'Histogram', "data": macd_data, "options": {"color": '#26a69a', "title": "MACD"}},
                        {"type": 'Line', "data": diff_data, "options": {"color": '#2962FF', "lineWidth": 1, "title": "DIFF"}},
                        {"type": 'Line', "data": dea_data, "options": {"color": '#FF6D00', "lineWidth": 1, "title": "DEA"}}
                    ]
                    add_sub(150, series)
            
            elif itype == 'KDJ':
                 # Simple KDJ implementation
                 low_min = df['low'].rolling(9).min()
                 high_max = df['high'].rolling(9).max()
                 rsv = (df['close'] - low_min) / (high_max - low_min) * 100
                 k = rsv.ewm(com=2, adjust=False).mean() # SMA(3) equivalent roughly
                 d = k.ewm(com=2, adjust=False).mean()
                 j = 3 * k - 2 * d
                 
                 k_data = pd.DataFrame({'time': df['time'], 'value': k}).dropna().to_dict('records')
                 d_data = pd.DataFrame({'time': df['time'], 'value': d}).dropna().to_dict('records')
                 j_data = pd.DataFrame({'time': df['time'], 'value': j}).dropna().to_dict('records')
                 
                 if k_data:
                     series = [
                         {"type": 'Line', "data": k_data, "options": {"color": '#2962FF', "lineWidth": 1, "title": "K"}},
                         {"type": 'Line', "data": d_data, "options": {"color": '#FF6D00', "lineWidth": 1, "title": "D"}},
                         {"type": 'Line', "data": j_data, "options": {"color": '#E91E63', "lineWidth": 1, "title": "J"}}
                     ]
                     add_sub(150, series)

    return main_overlays, sub_charts
