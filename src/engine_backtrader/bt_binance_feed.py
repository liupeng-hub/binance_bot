import backtrader as bt
import pandas as pd
from datetime import datetime, timedelta
import time
import threading
import queue
import os
import sys
from src.utils.redis_client import redis_client
from src.utils.data_provider import fetch_binance_history

class BinanceData(bt.feeds.PandasData):
    """
    Backtrader 自定义数据源，用于从 Binance 加载历史数据
    并通过轮询支持伪实时数据。
    """
    params = (
        ('store', None),
        ('symbol', 'BTC/USDT'),
        ('binance_timeframe', '1m'), # '1m', '5m', '1h', '1d'
        ('days', 30),
        ('_realtime', False),
        ('poll_interval', 3), # 轮询间隔 (秒)
        ('use_websocket', True), # 是否使用 WebSocket
        ('instance_id', None), # 用于推送实时数据到 Redis
    )

    def __init__(self):
        # 3. 时间周期映射
        tf_map = {
            '1m': (bt.TimeFrame.Minutes, 1),
            '3m': (bt.TimeFrame.Minutes, 3),
            '5m': (bt.TimeFrame.Minutes, 5),
            '15m': (bt.TimeFrame.Minutes, 15),
            '30m': (bt.TimeFrame.Minutes, 30),
            '1h': (bt.TimeFrame.Minutes, 60),
            '2h': (bt.TimeFrame.Minutes, 120),
            '4h': (bt.TimeFrame.Minutes, 240),
            '1d': (bt.TimeFrame.Days, 1),
        }
        
        tf, comp = tf_map.get(self.p.binance_timeframe, (bt.TimeFrame.Minutes, 1))
        
        # 4. 初始化父类
        super().__init__()
        
        # 5. 覆盖时间周期和压缩参数
        self._timeframe = tf
        self._compression = comp

        if self.p.store is None:
            raise ValueError("必须提供 BinanceStore 实例。")
        self.store = self.p.store
        
        self._realtime_queue = queue.Queue()
        self._realtime_thread = None
        self._realtime_running = False
        self._ws_app = None # WebSocket 客户端实例

    def start(self):
        super().start()
        # 历史数据已在 init 中加载
        if self.p._realtime:
            if self.p.use_websocket:
                self._start_websocket()
            else:
                self._start_polling()

    def stop(self):
        self._realtime_running = False
        if self._realtime_thread:
            # 如果是 WS，需要关闭连接
            if self._ws_app:
                self._ws_app.close()
            self._realtime_thread.join(timeout=1)
        super().stop()

    def _start_polling(self):
        self._realtime_running = True
        self._realtime_thread = threading.Thread(target=self._run_polling_loop)
        self._realtime_thread.daemon = True
        self._realtime_thread.start()

    def _start_websocket(self):
        self._realtime_running = True
        self._realtime_thread = threading.Thread(target=self._run_websocket_loop)
        self._realtime_thread.daemon = True
        self._realtime_thread.start()

    def _run_websocket_loop(self):
        """连接币安 WebSocket 获取实时 K 线。"""
        import websocket
        import json
        import ssl
        
        symbol = self.p.symbol.replace('/', '').lower()
        interval = self.p.binance_timeframe
        
        # Binance Futures WebSocket URL
        # e.g. wss://fstream.binance.com/ws/btcusdt@kline_1m
        if getattr(self.store, 'testnet', False):
            base_url = "wss://stream.binancefuture.com/ws"
        else:
            base_url = "wss://fstream.binance.com/ws"
            
        socket_url = f"{base_url}/{symbol}@kline_{interval}"
        
        print(f"🚀 正在连接 WebSocket: {socket_url}")
        
        def on_message(ws, message):
            if not self._realtime_running:
                ws.close()
                return
                
            try:
                msg = json.loads(message)
                # 提取 K 线数据
                # 格式参考: https://binance-docs.github.io/apidocs/futures/en/#kline-candlestick-streams
                k = msg.get('k')
                if k:
                    is_closed = k.get('x', False) # K线是否完结
                    current_time = datetime.fromtimestamp(k['t'] / 1000.0)
                    close_price = float(k['c'])
                    volume = float(k['v'])
                    
                    # --- Redis 实时推送 (Developing Candle) ---
                    if self.p.instance_id:
                        candle = {
                            'time': int(k['t'] / 1000),
                            'open': float(k['o']),
                            'high': float(k['h']),
                            'low': float(k['l']),
                            'close': close_price,
                            'volume': volume,
                            'symbol': self.p.symbol,
                            'is_closed': is_closed
                        }
                        # 直接推送到 Redis，不通过 Backtrader Queue
                        redis_client.publish_market_data(self.p.instance_id, candle)
                    # ----------------------------------------
                    
                    # 打印调试信息
                    if self.p._realtime: 
                        status = "✅ 已完结" if is_closed else "⏳ 进行中"
                        # print(f"📡 WS [{self.p.symbol}] {status}: {current_time} | 收: {close_price} | 量: {volume}")

                    # 逻辑：
                    # 1. 如果 K 线已完结，将其放入队列 (供 Backtrader 引擎使用)
                    if is_closed:
                        line = (
                            current_time,
                            float(k['o']), # Open
                            float(k['h']), # High
                            float(k['l']), # Low
                            close_price,   # Close
                            volume
                        )
                        self._realtime_queue.put(line)
                    
            except Exception as e:
                print(f"WS Message Error: {e}")

        def on_error(ws, error):
            print(f"WS Error: {error}")

        def on_close(ws, close_status_code, close_msg):
            print(f"WS Closed: {close_status_code} - {close_msg}")

        def on_open(ws):
            print("✅ WebSocket 连接已建立")

        # 启动 WebSocket
        self._ws_app = websocket.WebSocketApp(
            socket_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        # 获取系统代理设置
        proxy_type = None
        http_proxy_host = None
        http_proxy_port = None
        
        # 简单检查常见的代理环境变量
        for env_var in ['https_proxy', 'http_proxy', 'HTTPS_PROXY', 'HTTP_PROXY']:
            proxy_url = os.environ.get(env_var)
            if proxy_url:
                try:
                    # 解析如 http://127.0.0.1:7890
                    if '://' in proxy_url:
                        schema, rest = proxy_url.split('://')
                        if ':' in rest:
                            http_proxy_host, http_proxy_port = rest.split(':')
                    else:
                        if ':' in proxy_url:
                            http_proxy_host, http_proxy_port = proxy_url.split(':')
                            
                    if http_proxy_host and http_proxy_port:
                        http_proxy_port = int(http_proxy_port)
                        proxy_type = 'http'
                        print(f"ℹ️  使用代理: {http_proxy_host}:{http_proxy_port}")
                        break
                except Exception as e:
                    print(f"⚠️  解析代理环境变量失败: {e}")

        while self._realtime_running:
            try:
                # 禁用 SSL 验证以避免证书问题
                self._ws_app.run_forever(
                    ping_interval=60, 
                    ping_timeout=10,
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    http_proxy_host=http_proxy_host,
                    http_proxy_port=http_proxy_port,
                    proxy_type=proxy_type
                )
            except Exception as e:
                print(f"WS Run Error: {e}")
                time.sleep(5) # 重连延迟

    def _run_polling_loop(self):
        """轮询币安获取最新价格。"""
        exchange = self.store.get_exchange()
        symbol = self.p.symbol
        print(f"正在启动 {symbol} 的实时轮询...")
        
        while self._realtime_running:
            try:
                # 获取最新 ticker 作为实时价格
                ticker = exchange.fetch_ticker(symbol)
                current_time = datetime.fromtimestamp(ticker['timestamp'] / 1000.0)
                price = ticker['last']
                
                # --- Redis 实时推送 (Polling) ---
                if self.p.instance_id:
                    candle = {
                        'time': int(ticker['timestamp'] / 1000),
                        'open': price,
                        'high': price,
                        'low': price,
                        'close': price,
                        'volume': ticker.get('baseVolume', 0),
                        'symbol': self.p.symbol,
                        'is_closed': False
                    }
                    redis_client.publish_market_data(self.p.instance_id, candle)
                # --------------------------------
                
                # 构建伪 K 线或仅更新收盘价
                line = (
                    current_time,
                    price,
                    price,
                    price,
                    price,
                    ticker.get('baseVolume', 0) # 或 quoteVolume
                )
                self._realtime_queue.put(line)
                
            except Exception as e:
                print(f"轮询币安出错: {e}")
            
            time.sleep(self.p.poll_interval)

    def _load(self):
        if self.p._realtime:
            # 1. 尝试加载历史数据
            if super()._load():
                return True
            
            # 2. 历史数据耗尽，切换到实时队列
            line = self._realtime_queue.get()
            if line is not None:
                dt, open_, high, low, close, volume = line
                self.lines.datetime[0] = bt.date2num(dt)
                self.lines.open[0] = open_
                self.lines.high[0] = high
                self.lines.low[0] = low
                self.lines.close[0] = close
                self.lines.volume[0] = volume
                self.lines.openinterest[0] = 0
                return True
            return False
        else:
            return super()._load()

    def _load_history(self):
        # 此方法不再使用，逻辑移至 __init__
        pass
