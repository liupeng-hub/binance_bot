import os
import ccxt
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class BinanceStore:
    """
    BinanceStore 类作为通过 CCXT 与币安 API 交互的中心枢纽。
    它处理 API 初始化、身份验证，并提供获取数据源和经纪人实例的方法。
    """
    def __init__(self, api_key=None, secret_key=None, env_file=None, testnet=False):
        if env_file:
            load_dotenv(dotenv_path=env_file)

        self.api_key = api_key or os.getenv("BINANCE_API_KEY")
        self.secret_key = secret_key or os.getenv("BINANCE_SECRET_KEY")
        self.testnet = testnet

        # CCXT 配置
        self.exchange_config = {
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',  # 默认为 USDT 本位合约
            }
        }
        
        if testnet:
            self.exchange_config['options']['defaultType'] = 'future'
            self.exchange = ccxt.binanceusdm(self.exchange_config)
            self.exchange.set_sandbox_mode(True)
            print(f"📡 [Store] 已切换至币安测试网 (SandBox Mode)")
        else:
            self.exchange = ccxt.binanceusdm(self.exchange_config)
            print(f"📡 [Store] 已连接至币安正式网")

        self._broker = None
        self._data = None
        self._user_stream = None

    def get_exchange(self):
        return self.exchange

    def start_user_stream(self):
        """
        Starts the User Data Stream for real-time order/account updates.
        """
        if self._user_stream is None:
            from .bt_binance_user_stream import BinanceUserStream
            self._user_stream = BinanceUserStream(self)
            self._user_stream.start()
        return self._user_stream

    def get_data(self, symbol='BTC/USDT', timeframe='1m', days=30, use_websocket=True, instance_id=None, **kwargs):
        """
        工厂方法：创建 BinanceData 数据源。
        在此处预加载历史数据并传递给 Data Feed。
        """
        from .bt_binance_feed import BinanceData
        from src.utils.data_provider import fetch_binance_history
        import pandas as pd
        
        print(f"Loading data for {symbol} (Timeframe: {timeframe}, Days: {days})...")
        try:
            df = fetch_binance_history(symbol=symbol, timeframe=timeframe, days=days)
            
            if df.empty:
                print(f"Warning: No data fetched for {symbol}")
                df = pd.DataFrame(columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
                df.set_index('datetime', inplace=True)
            else:
                if 'datetime' in df.columns:
                    df.set_index('datetime', inplace=True)
                if 'timestamp' in df.columns:
                    df.drop(columns=['timestamp'], inplace=True)
                    
        except Exception as e:
            print(f"Error fetching data: {e}")
            df = pd.DataFrame(columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df.set_index('datetime', inplace=True)

        return BinanceData(dataname=df, store=self, symbol=symbol, 
                           binance_timeframe=timeframe, days=days, 
                           use_websocket=use_websocket, instance_id=instance_id, **kwargs)

    def get_broker(self, **kwargs):
        """
        工厂方法：创建 BinanceBroker 实例。
        """
        if self._broker is None:
            from .bt_binance_broker import BinanceBroker
            self._broker = BinanceBroker(store=self, **kwargs)
        return self._broker
