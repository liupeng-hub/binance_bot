import os
import glob
import pandas as pd
import json
from .db_manager import db_manager
from .db_models import MarketData

def load_kline_data(symbol, start_ts=None, end_ts=None, limit=10000, timeframe=None):
    """
    加载指定标的的 K 线数据，支持时间范围筛选
    优先尝试从数据库加载，如果失败或数据不足，则回退到 CSV 文件
    
    :param symbol: 交易对 (e.g. BTC/USDT)
    :param start_ts: 开始时间戳 (秒)
    :param end_ts: 结束时间戳 (秒)
    :param limit: 默认限制条数
    :param timeframe: K线周期 (e.g., '1m', '1h', '1d')
    """
    
    # --- 1. 尝试从数据库加载 ---
    try:
        session = db_manager.get_session()
        query = session.query(MarketData).filter(MarketData.symbol == symbol)
        
        if timeframe:
            query = query.filter(MarketData.timeframe == timeframe)
            
        if start_ts:
            start_dt = pd.to_datetime(start_ts, unit='s')
            query = query.filter(MarketData.timestamp >= start_dt)
            
        if end_ts:
            end_dt = pd.to_datetime(end_ts, unit='s')
            query = query.filter(MarketData.timestamp <= end_dt)
            
        # 排序和限制
        query = query.order_by(MarketData.timestamp.asc())
        
        # 如果没有指定时间范围，只取最后 limit 条
        if not start_ts and not end_ts:
            # SQL 优化: 先倒序取 limit，再正序
            # 注意: SQLite/PG 语法可能略有差异，这里使用 Python 切片或子查询
            # 简单起见，直接查询
            count = query.count()
            if count > limit:
                query = query.offset(count - limit)
        
        # 执行查询
        # 使用 pandas.read_sql 会更方便，但这里我们有 session
        # 手动转换
        results = query.all()
        session.close()
        
        if results:
            data = [{
                'time': int(r.timestamp.timestamp()),
                'open': r.open,
                'high': r.high,
                'low': r.low,
                'close': r.close,
                'volume': r.volume
            } for r in results]
            
            df = pd.DataFrame(data)
            return df
            
    except Exception as e:
        # print(f"DB Load Error: {e}") # 调试用
        pass # Fallback to CSV

    # --- 2. 回退到 CSV 加载 (原有逻辑) ---
    # src/utils/data_helper.py -> src/utils -> src -> binance_bot
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data_dir = os.path.join(root_dir, 'data')
    safe_symbol = symbol.replace('/', '')
    
    # 构造文件匹配模式
    if timeframe:
        # 精确匹配周期: BTCUSDT_1d_*.csv
        pattern = os.path.join(data_dir, f"{safe_symbol}_{timeframe}_*.csv")
    else:
        # 模糊匹配 (可能会匹配到错误的周期，如 1m 代替 1d)
        pattern = os.path.join(data_dir, f"{safe_symbol}_*_*.csv")
        
    files = glob.glob(pattern)
    
    if not files:
        # 如果指定了周期但没找到，尝试降级到模糊搜索 (仅作为 fallback)
        if timeframe:
             pattern = os.path.join(data_dir, f"{safe_symbol}_*_*.csv")
             files = glob.glob(pattern)
             if not files:
                 return pd.DataFrame()
        else:
            return pd.DataFrame()
        
    # 策略：如果指定了 start_ts/end_ts，我们尝试找到覆盖该范围的文件
    # 但由于文件名只包含大致时间，且我们可能需要加载多个文件拼接 (暂不支持拼接)
    # 目前逻辑：优先取最新的文件 (通常是最新的数据)
    # 改进：如果文件列表中有明显包含目标时间段的文件，应该优先选它
    # (这需要解析文件名中的时间段，暂且先保持取最新，但依靠 timeframe 过滤应该能解决大部分问题)
    
    # 按照修改时间排序，取最新的
    files.sort(key=os.path.getmtime, reverse=True)
    latest_file = files[0]
    
    # 如果有多个文件，尝试找到包含 start_ts 的文件 (简单启发式)
    # 比如文件名包含 YYYYMMDD
    # 但最可靠的还是读取文件头尾 (但这会比较慢)
    # 考虑到我们通常只有一个最新的完整文件，或者按时间分割的文件
    # 如果最新的文件时间太早，可能不包含我们需要的数据
    
    try:
        # 尝试读取最新的文件
        df = pd.read_csv(latest_file)
        # 兼容不同的列名
        if 'datetime' in df.columns:
            df['time'] = pd.to_datetime(df['datetime'])
        elif 'timestamp' in df.columns: # Binance API raw data
             df['time'] = pd.to_datetime(df['timestamp'], unit='ms')
             
        # 转换为 Unix Timestamp (seconds)
        df['time'] = df['time'].astype('int64') // 10**9 
        
        # 筛选所需列
        required_cols = ['time', 'open', 'high', 'low', 'close']
        if all(col in df.columns for col in required_cols):
             df = df[required_cols]
             
             # 如果指定了时间范围，进行筛选
             if start_ts is not None or end_ts is not None:
                 if start_ts:
                     df = df[df['time'] >= start_ts]
                 if end_ts:
                     df = df[df['time'] <= end_ts]
                 
                 # 如果筛选后有数据，直接返回
                 if not df.empty:
                     return df
             
             # 如果没有指定时间，或者筛选后为空（fallback），返回最后 limit 条
             return df.tail(limit)
             
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

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
        
        main_overlays.append({
            "type": 'Line',
            "data": df[['time', 'sma_fast']].rename(columns={'sma_fast': 'value'}).dropna().to_dict('records'),
            "options": {"color": '#2962FF', "lineWidth": 2, "title": f"SMA {fast_period}"}
        })
        main_overlays.append({
            "type": 'Line',
            "data": df[['time', 'sma_slow']].rename(columns={'sma_slow': 'value'}).dropna().to_dict('records'),
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
        
        main_overlays.append({"type": 'Line', "data": df[['time', 'upper']].rename(columns={'upper': 'value'}).dropna().to_dict('records'), "options": {"color": 'rgba(128, 0, 128, 0.5)', "lineWidth": 1, "title": "Upper"}})
        main_overlays.append({"type": 'Line', "data": df[['time', 'lower']].rename(columns={'lower': 'value'}).dropna().to_dict('records'), "options": {"color": 'rgba(128, 0, 128, 0.5)', "lineWidth": 1, "title": "Lower"}})
        main_overlays.append({"type": 'Line', "data": df[['time', 'sma']].rename(columns={'sma': 'value'}).dropna().to_dict('records'), "options": {"color": 'rgba(128, 128, 128, 0.5)', "lineWidth": 1, "lineStyle": 2, "title": "Mid"}})

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
        
        main_overlays.append({"type": 'Line', "data": df[['time', 'buy_line']].rename(columns={'buy_line': 'value'}).dropna().to_dict('records'), "options": {"color": 'green', "lineWidth": 1, "title": "Buy Line"}})
        main_overlays.append({"type": 'Line', "data": df[['time', 'sell_line']].rename(columns={'sell_line': 'value'}).dropna().to_dict('records'), "options": {"color": 'red', "lineWidth": 1, "title": "Sell Line"}})

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
        macd_data = df[['time', 'macd']].rename(columns={'macd': 'value'}).dropna().to_dict('records')
        diff_data = df[['time', 'diff']].rename(columns={'diff': 'value'}).dropna().to_dict('records')
        dea_data = df[['time', 'dea']].rename(columns={'dea': 'value'}).dropna().to_dict('records')
        
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
