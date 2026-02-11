import unittest
import pandas as pd
import numpy as np
from src.utils.metrics import calculate_metrics, analyze_trade_list

class TestMetrics(unittest.TestCase):
    
    def setUp(self):
        # Create a standard monotonic increasing equity curve for easy assertions
        self.dates = pd.date_range(start='2023-01-01', periods=5)
        # 10000 -> 10100 -> 10200 -> 10100 -> 10300
        self.equity_values = [10000, 10100, 10200, 10100, 10300]
        self.df = pd.DataFrame({'datetime': self.dates, 'value': self.equity_values})

    def test_calculate_metrics_basic(self):
        metrics = calculate_metrics(self.df, initial_capital=10000.0)
        
        # Check Keys
        expected_keys = [
            "net_profit", "total_return", "sharpe_ratio", "sortino_ratio", 
            "calmar_ratio", "max_drawdown", "volatility", "final_value"
        ]
        for key in expected_keys:
            self.assertIn(key, metrics)
            
        # Check Values
        # Net Profit: 10300 - 10000 = 300
        self.assertEqual(metrics['net_profit'], 300.0)
        # Total Return: 300 / 10000 = 0.03
        self.assertEqual(metrics['total_return'], 0.03)
        # Final Value
        self.assertEqual(metrics['final_value'], 10300.0)
        
        # Max Drawdown
        # Peak at 10200, drop to 10100. Drawdown = (10200-10100)/10200 = 100/10200 ≈ 0.0098
        # Then 10300 is new peak.
        # Max DD should be ~0.0098
        self.assertAlmostEqual(metrics['max_drawdown'], 100/10200, places=4)

    def test_calculate_metrics_empty(self):
        df_empty = pd.DataFrame(columns=['datetime', 'value'])
        metrics = calculate_metrics(df_empty)
        self.assertEqual(metrics, {})

    def test_calculate_metrics_single_row(self):
        df_single = pd.DataFrame({'datetime': [self.dates[0]], 'value': [10000]})
        metrics = calculate_metrics(df_single, initial_capital=10000.0)
        
        self.assertEqual(metrics['net_profit'], 0.0)
        self.assertEqual(metrics['sharpe_ratio'], 0) # Should be 0 as std is 0/undefined logic handles it
        self.assertEqual(metrics['max_drawdown'], 0.0)

    def test_analyze_trade_list_basic(self):
        # 2 Wins, 2 Losses
        trades = [
            {'pnl': 100}, {'pnl': -50}, {'pnl': 200}, {'pnl': -50}
        ]
        
        metrics = analyze_trade_list(trades)
        
        self.assertEqual(metrics['total_trades'], 4)
        self.assertEqual(metrics['win_rate'], 0.5)
        # Avg Win: (100+200)/2 = 150
        self.assertEqual(metrics['avg_win'], 150.0)
        # Avg Loss: (-50-50)/2 = -50
        self.assertEqual(metrics['avg_loss'], -50.0)
        # Profit Factor: (300) / (100) = 3.0
        self.assertEqual(metrics['profit_factor'], 3.0)

    def test_analyze_trade_list_empty(self):
        metrics = analyze_trade_list([])
        self.assertEqual(metrics, {})
        
    def test_analyze_trade_list_all_loss(self):
        trades = [{'pnl': -10}, {'pnl': -20}]
        metrics = analyze_trade_list(trades)
        self.assertEqual(metrics['win_rate'], 0.0)
        self.assertEqual(metrics['profit_factor'], 0.0)
        
    def test_analyze_trade_list_all_win(self):
        trades = [{'pnl': 10}, {'pnl': 20}]
        metrics = analyze_trade_list(trades)
        self.assertEqual(metrics['win_rate'], 1.0)
        self.assertEqual(metrics['profit_factor'], float('inf'))

if __name__ == '__main__':
    unittest.main()
