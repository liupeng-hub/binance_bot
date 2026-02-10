import backtrader as bt
from src.utils.redis_client import redis_client
from datetime import datetime

class RedisMarketFeed(bt.Analyzer):
    """
    Real-time Market Data Publisher for Redis
    """
    params = (
        ('instance_id', None),
        ('symbol', None),
    )

    def start(self):
        self.instance_id = self.p.instance_id
        self.symbol = self.p.symbol

    def next(self):
        # Called on every bar close (usually)
        self._publish_candle()

    def _publish_candle(self):
        if not self.instance_id:
            return

        data = self.datas[0]
        # 获取当前 Bar 的数据
        # 注意: 在 next() 中，index 0 通常是刚刚 Close 的 Bar
        # 如果是 Live 模式且支持 tick，可能需要检查 data.datetime
        
        try:
            # 转换为 timestamp (seconds)
            dt = data.datetime.datetime(0)
            ts = dt.timestamp()
            
            candle = {
                'time': int(ts),
                'open': data.open[0],
                'high': data.high[0],
                'low': data.low[0],
                'close': data.close[0],
                'volume': data.volume[0] if hasattr(data, 'volume') else 0,
                'symbol': self.symbol,
                'is_closed': True # 标记为已关闭的 Bar
            }
            
            redis_client.publish_market_data(self.instance_id, candle)
        except Exception as e:
            pass
            # print(f"RedisFeed Error: {e}")
