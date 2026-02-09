import unittest
import pandas as pd
import numpy as np
from src.utils.data_helper import calculate_indicators

class TestDataHelper(unittest.TestCase):
    
    def setUp(self):
        # Create a sample DataFrame
        dates = pd.date_range(start='2023-01-01', periods=100, freq='H')
        self.df = pd.DataFrame({
            'time': dates.astype('int64') // 10**9,
            'open': np.random.randn(100) + 100,
            'high': np.random.randn(100) + 105,
            'low': np.random.randn(100) + 95,
            'close': np.random.randn(100) + 100,
            'volume': np.random.randint(1, 100, 100)
        })

    def test_sma_indicators(self):
        config = '{"params": {"fast_period": 5, "slow_period": 10}}'
        main, sub = calculate_indicators(self.df.copy(), 'SMACrossStrategy', config)
        
        # Check if SMA lines are added to main chart
        self.assertEqual(len(main), 2)
        self.assertEqual(main[0]['type'], 'Line')
        self.assertIn('SMA 5', main[0]['options']['title'])
        self.assertIn('SMA 10', main[1]['options']['title'])
        self.assertEqual(len(sub), 0)

    def test_macd_indicators(self):
        config = '{"params": {"fast_period": 12, "slow_period": 26, "signal_period": 9}}'
        main, sub = calculate_indicators(self.df.copy(), 'MACDStrategy', config)
        
        # Check if MACD is added to sub chart
        self.assertEqual(len(main), 0)
        self.assertEqual(len(sub), 1)
        self.assertEqual(len(sub[0]['series']), 3) # MACD, DIFF, DEA
        
        types = [s['type'] for s in sub[0]['series']]
        self.assertIn('Histogram', types)
        self.assertIn('Line', types)

    def test_bbands_indicators(self):
        config = '{"params": {"period": 20}}'
        main, sub = calculate_indicators(self.df.copy(), 'BBandsStrategy', config)
        
        # Upper, Lower, Mid
        self.assertEqual(len(main), 3) 
        titles = [m['options']['title'] for m in main]
        self.assertIn('Upper', titles)
        self.assertIn('Lower', titles)
        self.assertIn('Mid', titles)

if __name__ == '__main__':
    unittest.main()
