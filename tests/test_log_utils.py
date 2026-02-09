import unittest
import json
from datetime import datetime
import os
import sys

# 添加项目根目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.log_utils import format_log, setup_logger

class TestLogUtils(unittest.TestCase):
    
    def test_format_log_json(self):
        dt = datetime(2023, 1, 1, 12, 0, 0)
        symbol = "BTC/USDT"
        msg = "Test message"
        
        json_str = format_log(dt, symbol, msg, level='DEBUG', component='TestUnit')
        log_data = json.loads(json_str)
        
        self.assertEqual(log_data['timestamp'], "2023-01-01 12:00:00")
        self.assertEqual(log_data['symbol'], "BTC/USDT")
        self.assertEqual(log_data['message'], "Test message")
        self.assertEqual(log_data['level'], "DEBUG")
        self.assertEqual(log_data['component'], "TestUnit")

    def test_setup_logger(self):
        # 简单测试 logger 是否能正确创建
        logger = setup_logger("test_logger", level='DEBUG')
        self.assertEqual(logger.name, "test_logger")
        self.assertTrue(len(logger.handlers) > 0)

if __name__ == '__main__':
    unittest.main()
