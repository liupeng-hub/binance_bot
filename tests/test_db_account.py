import unittest
import os
import sys
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.utils.db_models import Base, User, ExchangeAccount, StrategyInstance
from src.utils.db_manager import DBManager

class TestDBAccount(unittest.TestCase):
    def setUp(self):
        # Use in-memory SQLite for testing
        self.db_manager = DBManager(db_url='sqlite:///:memory:')
        self.db_manager.init_db()
        self.session = self.db_manager.get_session()

    def tearDown(self):
        self.session.close()
        self.db_manager.dispose()

    def test_create_account(self):
        # 1. Create User
        user = User(username='test_user', password_hash='hash', role='user')
        self.session.add(user)
        self.session.commit()
        
        # 2. Add Exchange Account
        account = self.db_manager.add_exchange_account(
            self.session, 
            user_id=user.id, 
            alias='Main Binance', 
            api_key='abc', 
            secret_key='123'
        )
        self.session.commit()
        
        # 3. Verify
        self.assertIsNotNone(account.id)
        self.assertEqual(account.alias, 'Main Binance')
        
        # Check Encryption
        decrypted_key = self.db_manager.decrypt_secret(account.api_key_enc)
        self.assertEqual(decrypted_key, 'abc')

    def test_link_instance_to_account(self):
        # 1. Create User & Account
        user = User(username='trader', password_hash='hash')
        self.session.add(user)
        self.session.commit()
        
        account = self.db_manager.add_exchange_account(
            self.session, user.id, 'Test Account', 'k', 's', account_type='testnet'
        )
        self.session.commit()
        
        # 2. Create Instance linked to Account
        instance_id = str(uuid.uuid4())
        instance = StrategyInstance(
            id=instance_id,
            user_id=user.id,
            account_id=account.id,
            symbol='BTC/USDT',
            strategy_name='TestStrat'
        )
        self.session.add(instance)
        self.session.commit()
        
        # 3. Verify Relationship
        fetched_inst = self.session.query(StrategyInstance).filter_by(id=instance_id).first()
        self.assertEqual(fetched_inst.account.alias, 'Test Account')
        self.assertEqual(fetched_inst.account.account_type, 'testnet')
        print("✅ test_link_instance_to_account passed")

if __name__ == '__main__':
    unittest.main(verbosity=2)
