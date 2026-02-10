import redis
import os
import json
from dotenv import load_dotenv

class RedisClient:
    def __init__(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        load_dotenv(os.path.join(root_dir, '.env'))
        
        self.redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        try:
            self.client = redis.from_url(self.redis_url, decode_responses=True)
            # 测试连接
            self.client.ping()
            self.available = True
        except Exception as e:
            print(f"⚠️ Redis unavailable: {e}")
            self.client = None
            self.available = False

    def publish_status(self, instance_id, status_data):
        """发布实例状态更新并同步缓存"""
        if not self.available:
            return
        
        # 更新缓存
        key = f"instance_status_cache:{instance_id}"
        self.client.set(key, json.dumps(status_data), ex=86400) # 缓存24小时
        
        # 发布消息
        channel = f"instance_status:{instance_id}"
        self.client.publish(channel, json.dumps(status_data))

    def get_status(self, instance_id):
        """从 Redis 获取最新状态"""
        if not self.available:
            return None
        key = f"instance_status_cache:{instance_id}"
        data = self.client.get(key)
        return json.loads(data) if data else None

    def publish_log(self, instance_id, log_message):
        """发布实例实时日志并存入最近日志列表"""
        if not self.available:
            return
        
        # 存入最近日志列表 (保留最近 200 条)
        list_key = f"instance_logs_list:{instance_id}"
        self.client.rpush(list_key, log_message)
        self.client.ltrim(list_key, -200, -1)
        self.client.expire(list_key, 3600) # 1小时过期
        
        # 发布消息
        channel = f"instance_logs:{instance_id}"
        self.client.publish(channel, log_message)

    def get_latest_logs(self, instance_id, count=100):
        """从 Redis 获取最近日志"""
        if not self.available:
            return []
        list_key = f"instance_logs_list:{instance_id}"
        return self.client.lrange(list_key, -count, -1)

    def set_instance_info(self, instance_id, info):
        """缓存实例基本信息"""
        if not self.available:
            return
        key = f"instance_info:{instance_id}"
        self.client.set(key, json.dumps(info), ex=3600) # 缓存1小时

    def get_instance_info(self, instance_id):
        if not self.available:
            return None
        key = f"instance_info:{instance_id}"
        data = self.client.get(key)
        return json.loads(data) if data else None

    def publish_market_data(self, instance_id, kline_data):
        """发布实时 K 线数据 (Snapshot)"""
        if not self.available:
            return
        # Topic: market_data:{instance_id}
        channel = f"market_data:{instance_id}"
        # Cache last candle for immediate fetch
        cache_key = f"market_data_cache:{instance_id}"
        
        # 处理 NaN 值，将其转换为 None (JSON null)
        # Python 的 json.dumps 默认会输出 NaN，这在 JS 中是不合法的
        # simplejson 支持 ignore_nan=True，但标准库需要手动处理
        # 这里我们使用 json.dumps(..., allow_nan=False) 会抛出异常
        # 或者我们手动清理数据
        
        def clean_nan(obj):
            if isinstance(obj, float):
                import math
                if math.isnan(obj) or math.isinf(obj):
                    return None
            elif isinstance(obj, dict):
                return {k: clean_nan(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_nan(v) for v in obj]
            return obj
            
        cleaned_data = clean_nan(kline_data)
        json_data = json.dumps(cleaned_data)
        
        # 1. Update Snapshot (Single Key) - for backward compatibility
        self.client.set(cache_key, json_data, ex=3600)
        
        # 2. Update List (Keep last 20 ticks/candles)
        list_key = f"market_data_list:{instance_id}"
        self.client.rpush(list_key, json_data)
        self.client.ltrim(list_key, -20, -1)
        self.client.expire(list_key, 3600)

        # 3. Publish
        self.client.publish(channel, json_data)

    def get_latest_market_data(self, instance_id):
        """获取最新的 K 线快照 (返回列表)"""
        if not self.available:
            return []
            
        # Try list first
        list_key = f"market_data_list:{instance_id}"
        data_list = self.client.lrange(list_key, 0, -1)
        
        if data_list:
            return [json.loads(x) for x in data_list]
            
        # Fallback to single cache
        key = f"market_data_cache:{instance_id}"
        data = self.client.get(key)
        return [json.loads(data)] if data else []

# 单例模式
redis_client = RedisClient()
