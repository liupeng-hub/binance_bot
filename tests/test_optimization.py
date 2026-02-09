import unittest
from unittest.mock import MagicMock, patch
import backtrader as bt
import sys
import os

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from src.engine_backtrader.optimization_runner import run_grid_search, run_optuna_search

class DummyStrategy(bt.Strategy):
    params = (('p1', 10), ('p2', 20.5))
    def next(self):
        pass

class TestOptimizationRunner(unittest.TestCase):

    def setUp(self):
        self.capital = 10000.0
        self.params_config = {
            'p1': {'start': 10, 'end': 12, 'step': 1, 'type': 'int'},
            'p2': {'start': 0.1, 'end': 0.3, 'step': 0.1, 'type': 'float'}
        }

    @patch('src.engine_backtrader.optimization_runner.extract_metrics')
    def test_run_grid_search(self, mock_extract):
        # Setup mocks
        mock_extract.return_value = {'net_profit': 100, 'max_drawdown': 5.0}
        
        cerebro = MagicMock()
        # Mock run result: list of lists of strategy instances
        strat_instance = MagicMock()
        strat_instance.p.p1 = 10
        strat_instance.p.p2 = 0.1
        
        # 3 combinations: p1(10,11,12) * p2(0.1, 0.2, 0.3) = 9
        # But let's simplify params for easier testing
        simple_config = {'p1': {'start': 1, 'end': 2, 'step': 1, 'type': 'int'}}
        
        # Mock cerebro.run returning 2 results
        res1 = [MagicMock()]
        res1[0].p.p1 = 1
        res2 = [MagicMock()]
        res2[0].p.p1 = 2
        
        cerebro.run.return_value = [res1, res2]
        
        results = run_grid_search(cerebro, DummyStrategy, simple_config, self.capital)
        
        # Assertions
        cerebro.optstrategy.assert_called()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['params']['p1'], 1)

    @patch('optuna.create_study')
    def test_run_optuna_search(self, mock_create_study):
        # Mock Study and Trial
        mock_study = MagicMock()
        mock_create_study.return_value = mock_study
        
        # Mock completed trials
        trial1 = MagicMock()
        trial1.state = 5 # COMPLETE (using enum value or just mocking attr)
        # Optuna TrialState.COMPLETE is actually an enum, but let's assume we can just check state
        # Better: mock optuna.trial.TrialState
        
        # Actually run_optuna_search iterates study.trials
        # We need to ensure trial.state equals optuna.trial.TrialState.COMPLETE
        # Let's just mock the behavior of optimization loop
        
        # Instead of mocking internal logic of optuna (which is complex), 
        # let's just test that it calls optimize and processes results.
        
        import optuna
        trial1.state = optuna.trial.TrialState.COMPLETE
        trial1.params = {'p1': 10}
        trial1.user_attrs = {'net_profit': 500}
        
        mock_study.trials = [trial1]
        
        # We need a dummy data feed
        data_feed = MagicMock()
        
        # Since run_optuna_search defines 'objective' internally, we can't easily mock it
        # unless we mock bt.Cerebro inside the function.
        
        with patch('backtrader.Cerebro') as mock_cerebro_cls:
            mock_cerebro = mock_cerebro_cls.return_value
            mock_cerebro.run.return_value = [MagicMock()] # returns strats
            mock_cerebro.run.return_value[0].broker.get_value.return_value = 10100.0 # profit 100
            
            # Also mock analyzers
            mock_strat = mock_cerebro.run.return_value[0]
            mock_strat.analyzers.trade_analyzer.get_analysis.return_value = {}
            mock_strat.analyzers.drawdown.get_analysis.return_value = {}

            results = run_optuna_search(DummyStrategy, self.params_config, data_feed, self.capital, n_trials=2)
            
            # Check if study.optimize was called
            mock_study.optimize.assert_called()
            
            # Check results extraction
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['metrics']['net_profit'], 500)

if __name__ == '__main__':
    unittest.main()
