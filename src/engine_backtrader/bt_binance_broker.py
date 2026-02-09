import backtrader as bt
import ccxt

class BinanceBroker(bt.brokers.BrokerBack):
    """
    自定义 Backtrader Broker，通过 CCXT 连接到 Binance。
    它继承自 BrokerBack 以维护内部状态模拟，
    同时将真实订单发送到交易所。
    """
    params = (
        ('store', None),
    )

    def __init__(self):
        super().__init__()
        if self.p.store is None:
            raise ValueError("必须提供 BinanceStore 实例。")
        self.store = self.p.store
        self.exchange = self.store.get_exchange()
        self.orders = {} # 映射 Binance 订单 ID -> BT 订单

    def buy(self, owner, data, size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None, **kwargs):
        
        # 1. 让父类 (模拟器) 创建订单对象
        order = super().buy(owner, data, size, price, plimit,
                            exectype, valid, tradeid, oco,
                            trailamount, trailpercent, **kwargs)
        
        # 2. 提交到 Binance
        self._submit_order(order, 'buy')
        return order

    def sell(self, owner, data, size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None, **kwargs):

        order = super().sell(owner, data, size, price, plimit,
                             exectype, valid, tradeid, oco,
                             trailamount, trailpercent, **kwargs)

        self._submit_order(order, 'sell')
        return order

    def _submit_order(self, order, side):
        symbol = order.data._dataname
        amount = abs(order.size)
        price = order.price
        
        order_type = 'limit' if order.exectype == bt.Order.Limit else 'market'
        
        # CCXT 参数
        params = {}
        
        try:
            print(f"🚀 正在向 Binance 提交 {side.upper()} 订单: {symbol} {amount} @ {price if price else 'MKT'}")
            
            # 使用 CCXT create_order
            # create_order(symbol, type, side, amount, price=None, params={})
            response = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price if order_type == 'limit' else None,
                params=params
            )
            
            binance_id = response['id']
            print(f"✅ 订单已提交。ID: {binance_id}")
            self.orders[binance_id] = order
            
        except Exception as e:
            print(f"❌ 提交订单到 Binance 失败: {e}")
            # 如果失败，在模拟器中取消
            super().cancel(order)

    def cancel(self, order):
        super().cancel(order)
        
        binance_id = self.get_binance_id(order)
        if not binance_id:
            return

        try:
            print(f"🔄 正在取消 Binance 订单: {binance_id}")
            symbol = order.data._dataname
            self.exchange.cancel_order(binance_id, symbol)
        except Exception as e:
            print(f"❌ 取消 Binance 订单 {binance_id} 失败: {e}")

    def get_binance_id(self, order):
        for bid, o in self.orders.items():
            if o.ref == order.ref:
                return bid
        return None
