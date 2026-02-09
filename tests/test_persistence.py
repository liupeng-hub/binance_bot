import unittest
from unittest.mock import MagicMock, patch
import json
import os
import sys

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from src.utils.db_models import StrategyState, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

class TestPersistence(unittest.TestCase):
    
    def setUp(self):
        # Setup in-memory SQLite
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        
    def tearDown(self):
        self.session.close()
        
    def test_save_state(self):
        # Create a state entry
        state_data = {
            "positions": {"BTC/USDT": {"size": 1.0, "price": 50000}},
            "open_orders": []
        }
        
        state = StrategyState(
            instance_id="test_inst_1",
            state_json=json.dumps(state_data)
        )
        self.session.add(state)
        self.session.commit()
        
        # Verify
        saved = self.session.query(StrategyState).filter_by(instance_id="test_inst_1").first()
        self.assertIsNotNone(saved)
        loaded_data = json.loads(saved.state_json)
        self.assertEqual(loaded_data['positions']['BTC/USDT']['size'], 1.0)
        
    def test_update_state(self):
        # Create initial state
        state = StrategyState(instance_id="test_inst_2", state_json="{}")
        self.session.add(state)
        self.session.commit()
        
        # Update
        saved = self.session.query(StrategyState).filter_by(instance_id="test_inst_2").first()
        saved.state_json = json.dumps({"updated": True})
        self.session.commit()
        
        # Verify update
        reloaded = self.session.query(StrategyState).filter_by(instance_id="test_inst_2").first()
        self.assertTrue(json.loads(reloaded.state_json)['updated'])

if __name__ == '__main__':
    unittest.main()
