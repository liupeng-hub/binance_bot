import unittest
from unittest.mock import MagicMock
from src.engine_backtrader.risk_proxy_broker import RiskProxyBroker

class MockRiskManager:
    def __init__(self, allow=True):
        self.allow = allow
        self.last_info = None

    def check_order(self, order_info):
        self.last_info = order_info
        if self.allow:
            return True, "OK"
        else:
            return False, "Risk check failed"

class MockBroker:
    def __init__(self):
        self.orders = []
        self.value = 10000.0

    def submit(self, order, **kwargs):
        self.orders.append(order)
        return order

    def getvalue(self):
        return self.value

    def notify(self, order):
        pass

class MockData:
    def __init__(self, name="BTC/USDT", close=100.0):
        self._name = name
        self.close = [close]

class MockOrder:
    def __init__(self, is_buy=True, price=100.0, size=1.0, data=None):
        self._is_buy = is_buy
        self.price = price
        self.size = size
        self.data = data
        self.status = 'CREATED'

    def isbuy(self):
        return self._is_buy

    def reject(self, broker):
        self.status = 'REJECTED'

class TestRiskProxyBroker(unittest.TestCase):
    
    def setUp(self):
        self.real_broker = MockBroker()
        self.data = MockData()

    def test_order_allowed(self):
        # 1. Setup Risk Manager to allow orders
        risk_manager = MockRiskManager(allow=True)
        proxy = RiskProxyBroker(self.real_broker, risk_manager)

        # 2. Create an order
        order = MockOrder(is_buy=True, price=50000, size=0.1, data=self.data)

        # 3. Submit order via proxy (which patched the real broker)
        # Note: In real usage, strategy calls self.broker.buy() which calls self.broker.submit()
        # Since we patched self.broker.submit, we call it directly to simulate
        result = self.real_broker.submit(order)

        # 4. Assertions
        # Should call check_order
        self.assertIsNotNone(risk_manager.last_info)
        self.assertEqual(risk_manager.last_info['symbol'], "BTC/USDT")
        self.assertEqual(risk_manager.last_info['side'], "BUY")
        
        # Should proceed to real submit
        self.assertIn(order, self.real_broker.orders)
        self.assertEqual(order.status, 'CREATED')

    def test_order_rejected(self):
        # 1. Setup Risk Manager to reject orders
        risk_manager = MockRiskManager(allow=False)
        proxy = RiskProxyBroker(self.real_broker, risk_manager)

        # 2. Create an order
        order = MockOrder(is_buy=False, price=50000, size=1.0, data=self.data)

        # 3. Submit order
        result = self.real_broker.submit(order)

        # 4. Assertions
        # Should call check_order
        self.assertIsNotNone(risk_manager.last_info)
        self.assertEqual(risk_manager.last_info['side'], "SELL")

        # Should NOT proceed to real submit
        self.assertNotIn(order, self.real_broker.orders)
        
        # Should be rejected
        self.assertEqual(order.status, 'REJECTED')

    def test_market_order_price_estimation(self):
        risk_manager = MockRiskManager(allow=True)
        proxy = RiskProxyBroker(self.real_broker, risk_manager)

        # Market order (price=None)
        order = MockOrder(is_buy=True, price=None, size=0.5, data=self.data)
        
        self.real_broker.submit(order)
        
        # Should use current close price from data
        self.assertEqual(risk_manager.last_info['price'], 100.0)

if __name__ == '__main__':
    unittest.main()
