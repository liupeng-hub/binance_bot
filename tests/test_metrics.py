import unittest
import pandas as pd
import numpy as np
from src.utils.metrics import calculate_metrics, analyze_trade_list

class TestMetrics(unittest.TestCase):
    
    def test_calculate_metrics(self):
        # Create dummy equity curve
        dates = pd.date_range(start='2023-01-01', periods=100)
        # Random walk
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 100)
        equity = 10000 * (1 + returns).cumprod()
        
        df = pd.DataFrame({'datetime': dates, 'value': equity})
        
        metrics = calculate_metrics(df, initial_capital=10000.0)
        
        self.assertIn("Total Return", metrics)
        self.assertIn("Sharpe Ratio", metrics)
        self.assertIn("Max Drawdown", metrics)
        
        # Check basic correctness
        total_ret_val = float(metrics['Total Return'].strip('%'))
        self.assertNotEqual(total_ret_val, 0)

    def test_analyze_trade_list(self):
        trades = [
            {'pnl': 100}, {'pnl': -50}, {'pnl': 200}, {'pnl': -50}
        ]
        
        metrics = analyze_trade_list(trades)
        
        self.assertEqual(metrics['Total Trades'], 4)
        # 2 wins, 2 losses = 50%
        self.assertEqual(metrics['Win Rate'], "50.00%")
        # Gross profit 300, Gross loss 100 -> PF 3.0
        self.assertEqual(metrics['Profit Factor'], "3.00")

if __name__ == '__main__':
    unittest.main()
