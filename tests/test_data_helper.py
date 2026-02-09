import unittest
import pandas as pd
import numpy as np
import json
import os
import sys

# 添加项目根目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.data_helper import calculate_indicators

class TestDataHelper(unittest.TestCase):
    
    def setUp(self):
        # 创建一个模拟的 DataFrame
        dates = pd.date_range(start='2023-01-01', periods=100, freq='1H')
        self.df = pd.DataFrame({
            'time': dates.view('int64') // 10**9,
            'open': np.random.uniform(50000, 51000, 100),
            'high': np.random.uniform(51000, 52000, 100),
            'low': np.random.uniform(49000, 50000, 100),
            'close': np.random.uniform(50000, 51000, 100),
            'volume': np.random.uniform(1, 10, 100)
        })

    def test_calculate_indicators_sma(self):
        # 测试 SMA 指标计算
        config = json.dumps({"fast_period": 5, "slow_period": 10})
        main_overlays, sub_charts = calculate_indicators(self.df, "SMA_Cross", config)
        
        self.assertEqual(len(main_overlays), 2)
        self.assertEqual(len(sub_charts), 0)
        self.assertEqual(main_overlays[0]['options']['title'], "SMA 5")
        self.assertEqual(main_overlays[1]['options']['title'], "SMA 10")
        
        # 检查数据点数量 (100 - 9 = 91, 因为 slow_period=10 需要 10 个点产生第一个均值)
        self.assertEqual(len(main_overlays[1]['data']), 91)

    def test_calculate_indicators_bbands(self):
        # 测试布林带指标计算
        config = json.dumps({"period": 20, "devfactor": 2.0})
        main_overlays, sub_charts = calculate_indicators(self.df, "BBands", config)
        
        self.assertEqual(len(main_overlays), 3) # Upper, Lower, Mid
        self.assertEqual(main_overlays[0]['options']['title'], "Upper")
        self.assertEqual(len(main_overlays[0]['data']), 81) # 100 - 19 = 81

    def test_calculate_indicators_macd(self):
        # 测试 MACD 指标计算
        config = json.dumps({"fast_period": 12, "slow_period": 26, "signal_period": 9})
        main_overlays, sub_charts = calculate_indicators(self.df, "MACD", config)
        
        self.assertEqual(len(main_overlays), 0)
        self.assertEqual(len(sub_charts), 1)
        self.assertEqual(len(sub_charts[0]['series']), 3) # MACD, DIFF, DEA
        self.assertEqual(sub_charts[0]['series'][0]['type'], 'Histogram')

if __name__ == '__main__':
    unittest.main()
