import unittest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import json
from datetime import datetime

# Import app
from src.utils.dashboard_api import app

class TestDashboardAPI(unittest.TestCase):
    
    def setUp(self):
        self.client = TestClient(app)
        
    @patch('src.utils.dashboard_api.db_manager')
    def test_get_instances(self, mock_db_manager):
        # Mock Session and Query
        mock_session = MagicMock()
        mock_db_manager.get_session.return_value = mock_session
        
        # Mock Instance Data
        mock_inst = MagicMock()
        mock_inst.id = "test_id_1"
        mock_inst.symbol = "BTC/USDT"
        mock_inst.strategy_name = "Grid"
        mock_inst.status = "RUNNING"
        mock_inst.config_json = json.dumps({"sys": {"capital": 10000.0}})
        
        # Mock Equity Data
        mock_eq = MagicMock()
        mock_eq.total_value = 10500.0
        
        # Chain calls
        mock_session.query.return_value.filter_by.return_value.all.return_value = [mock_inst]
        # For the second query (EquityRecord) inside the loop
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = mock_eq
        
        response = self.client.get("/instances?user_id=1")
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['symbol'], "BTC/USDT")
        self.assertEqual(data[0]['pnl'], 500.0) # 10500 - 10000
        
    @patch('src.utils.dashboard_api.db_manager')
    def test_get_equity_curve(self, mock_db_manager):
        mock_session = MagicMock()
        mock_db_manager.get_session.return_value = mock_session
        
        mock_rec = MagicMock()
        mock_rec.timestamp = datetime(2023, 1, 1, 12, 0, 0)
        mock_rec.total_value = 10000.0
        mock_rec.cash = 5000.0
        
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [mock_rec]
        
        response = self.client.get("/equity/test_inst_1")
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['total_value'], 10000.0)

if __name__ == '__main__':
    unittest.main()
