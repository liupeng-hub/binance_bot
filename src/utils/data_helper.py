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

def calculate_indicators(df, strategy_name, config_json):
    """
    根据策略类型和配置，计算指标并返回 Lightweight Charts 格式的 Series
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
        
    # SMA Cross
    if 'SMA' in strategy_name:
        fast_period = int(config.get('fast_period', 10))
        slow_period = int(config.get('slow_period', 30))
        
        df['sma_fast'] = df['close'].rolling(window=fast_period).mean()
        df['sma_slow'] = df['close'].rolling(window=slow_period).mean()
        
        # Replace NaN with None for chart data
        sma_fast_df = df[['time', 'sma_fast']].rename(columns={'sma_fast': 'value'})
        sma_fast_data = sma_fast_df.where(sma_fast_df.notnull(), None).dropna().to_dict('records')
        
        sma_slow_df = df[['time', 'sma_slow']].rename(columns={'sma_slow': 'value'})
        sma_slow_data = sma_slow_df.where(sma_slow_df.notnull(), None).dropna().to_dict('records')

        main_overlays.append({
            "type": 'Line',
            "data": sma_fast_data,
            "options": {"color": '#2962FF', "lineWidth": 2, "title": f"SMA {fast_period}"}
        })
        main_overlays.append({
            "type": 'Line',
            "data": sma_slow_data,
            "options": {"color": '#FF6D00', "lineWidth": 2, "title": f"SMA {slow_period}"}
        })

    # Bollinger Bands
    elif 'BBands' in strategy_name:
        period = int(config.get('period', 20))
        dev = float(config.get('devfactor', 2.0))
        
        df['sma'] = df['close'].rolling(window=period).mean()
        df['std'] = df['close'].rolling(window=period).std()
        df['upper'] = df['sma'] + (df['std'] * dev)
        df['lower'] = df['sma'] - (df['std'] * dev)
        
        upper_df = df[['time', 'upper']].rename(columns={'upper': 'value'})
        upper_data = upper_df.where(upper_df.notnull(), None).dropna().to_dict('records')
        
        lower_df = df[['time', 'lower']].rename(columns={'lower': 'value'})
        lower_data = lower_df.where(lower_df.notnull(), None).dropna().to_dict('records')
        
        mid_df = df[['time', 'sma']].rename(columns={'sma': 'value'})
        mid_data = mid_df.where(mid_df.notnull(), None).dropna().to_dict('records')

        main_overlays.append({"type": 'Line', "data": upper_data, "options": {"color": 'rgba(128, 0, 128, 0.5)', "lineWidth": 1, "title": "Upper"}})
        main_overlays.append({"type": 'Line', "data": lower_data, "options": {"color": 'rgba(128, 0, 128, 0.5)', "lineWidth": 1, "title": "Lower"}})
        main_overlays.append({"type": 'Line', "data": mid_data, "options": {"color": 'rgba(128, 128, 128, 0.5)', "lineWidth": 1, "lineStyle": 2, "title": "Mid"}})

    # Dual Thrust
    elif 'DualThrust' in strategy_name:
        period = int(config.get('period', 5))
        k1 = float(config.get('k1', 0.5))
        k2 = float(config.get('k2', 0.5))
        
        # Calculate Range (HH - LC, HC - LL)
        df['hh'] = df['high'].rolling(window=period).max()
        df['hc'] = df['close'].rolling(window=period).max()
        df['ll'] = df['low'].rolling(window=period).min()
        df['lc'] = df['close'].rolling(window=period).min()
        
        # Shift 1 bar (use previous N days data)
        # Note: Backtrader uses [-1], so we shift 1
        df['r1'] = df['hh'] - df['lc']
        df['r2'] = df['hc'] - df['ll']
        df['range'] = df[['r1', 'r2']].max(axis=1).shift(1)
        
        # Upper/Lower (based on OPEN of current bar)
        df['buy_line'] = df['open'] + k1 * df['range']
        df['sell_line'] = df['open'] - k2 * df['range']
        
        buy_df = df[['time', 'buy_line']].rename(columns={'buy_line': 'value'})
        buy_data = buy_df.where(buy_df.notnull(), None).dropna().to_dict('records')
        
        sell_df = df[['time', 'sell_line']].rename(columns={'sell_line': 'value'})
        sell_data = sell_df.where(sell_df.notnull(), None).dropna().to_dict('records')

        main_overlays.append({"type": 'Line', "data": buy_data, "options": {"color": 'green', "lineWidth": 1, "title": "Buy Line"}})
        main_overlays.append({"type": 'Line', "data": sell_data, "options": {"color": 'red', "lineWidth": 1, "title": "Sell Line"}})

    # MACD (副图)
    elif 'MACD' in strategy_name:
        fast_period = int(config.get('fast_period', 12))
        slow_period = int(config.get('slow_period', 26))
        signal_period = int(config.get('signal_period', 9))
        
        # Calculate EMA
        ema_fast = df['close'].ewm(span=fast_period, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow_period, adjust=False).mean()
        
        df['diff'] = ema_fast - ema_slow
        df['dea'] = df['diff'].ewm(span=signal_period, adjust=False).mean()
        df['macd'] = 2 * (df['diff'] - df['dea'])
        
        # 构建副图 Series
        # 注意：数据需要过滤 NaN，否则 LightWeightCharts 可能渲染失败
        macd_df = df[['time', 'macd']].rename(columns={'macd': 'value'})
        macd_data = macd_df.where(macd_df.notnull(), None).dropna().to_dict('records')
        
        diff_df = df[['time', 'diff']].rename(columns={'diff': 'value'})
        diff_data = diff_df.where(diff_df.notnull(), None).dropna().to_dict('records')
        
        dea_df = df[['time', 'dea']].rename(columns={'dea': 'value'})
        dea_data = dea_df.where(dea_df.notnull(), None).dropna().to_dict('records')
        
        if not macd_data: # 如果计算结果为空 (e.g. 数据不够长)
             return [], []

        sub_series = [
            {"type": 'Histogram', "data": macd_data, "options": {"color": '#26a69a', "title": "MACD"}},
            {"type": 'Line', "data": diff_data, "options": {"color": '#2962FF', "lineWidth": 1, "title": "DIFF"}},
            {"type": 'Line', "data": dea_data, "options": {"color": '#FF6D00', "lineWidth": 1, "title": "DEA"}}
        ]
        
        sub_charts.append({
            "height": 150, # Sub-chart height
            "series": sub_series
        })
    
    return main_overlays, sub_charts
