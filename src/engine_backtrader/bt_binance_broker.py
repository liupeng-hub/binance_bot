import backtrader as bt
import ccxt
from typing import Optional

class BinanceBroker(bt.brokers.BrokerBack):
    """
    Binance 订单代理（支持实盘和回测）
    """
    params = (
        ('store', None),
        ('mode', 'sim'),  # 'sim' 或 'live'
        ('order_notifier', None),  # 订单状态通知器
    )

    def __init__(self):
        super().__init__()
        if self.p.store is None:
            raise ValueError("必须提供 BinanceStore 实例。")
        self.store = self.p.store
        self.exchange = self.store.get_exchange()
        self.mode = self.p.mode

        self.orders = {} # 映射 Binance 订单 ID -> BT 订单
        self.bt_to_binance_orders = {} # BT ID -> 币安 ID

        # 订单状态通知器（延迟初始化）
        self._order_notifier: Optional['OrderStateNotifier'] = self.p.order_notifier

    def set_order_notifier(self, notifier):
        """设置订单状态通知器"""
        self._order_notifier = notifier

    def get_order_notifier(self):
        """获取订单状态通知器"""
        return self._order_notifier

    def get_order_by_binance_id(self, binance_id):
        """根据币安订单 ID 查找 BT 订单"""
        return self.orders.get(binance_id)

    def get_binance_id_by_order(self, bt_order):
        """根据 BT 订单查找币安订单 ID"""
        return self.bt_to_binance_orders.get(bt_order.ref)

    def buy(self, owner, data, size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None, **kwargs):
        """
        买入订单
        """
        # 1. 让父类创建订单对象
        order = super().buy(owner, data, size, price, plimit,
                            exectype, valid, tradeid, oco,
                            trailamount, trailpercent, **kwargs)

        # 2. 如果是实盘模式，提交到币安
        if self.mode == 'live':
            self._submit_order_to_exchange(order, 'buy')
        else:
            # 回测模式：订单已由父类处理，这里直接通过通知器更新状态
            if self._order_notifier:
                # 回测模式下，订单会由 Backtrader 自动成交
                # 这里可以添加自定义逻辑
                pass

        return order

    def sell(self, owner, data, size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None, **kwargs):
        """
        卖出订单
        """
        order = super().sell(owner, data, size, price, plimit,
                             exectype, valid, tradeid, oco,
                             trailamount, trailpercent, **kwargs)

        if self.mode == 'live':
            self._submit_order_to_exchange(order, 'sell')
        else:
            # 回测模式
            if self._order_notifier:
                pass

        return order

    def _submit_order_to_exchange(self, order, side):
        """
        提交订单到币安交易所（仅实盘模式）
        """
        symbol = order.data._dataname
        amount = abs(order.size)
        price = order.price

        order_type = 'limit' if order.exectype == bt.Order.Limit else 'market'

        try:
            print(f"🚀 提交 {side.upper()} 订单到币安: {symbol} {amount} @ {price if price else 'MKT'}")

            # 使用 CCXT create_order
            response = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price if order_type == 'limit' else None
            )

            # 注意: CCXT 的 response['id'] 可能是 int 或 str
            binance_id = str(response['id'])
            print(f"✅ 订单已提交，币安订单 ID: {binance_id}")

            # 保存映射关系
            self.orders[binance_id] = order
            self.bt_to_binance_orders[order.ref] = binance_id

        except Exception as e:
            print(f"❌ 提交订单失败: {e}")
            # 取消订单
            super().cancel(order)

    def cancel(self, order, **kwargs):
        """取消订单"""
        try:
            super().cancel(order, **kwargs)
        except TypeError:
            super().cancel(order)

        if self.mode == 'live':
            binance_id = self.get_binance_id_by_order(order)
            if binance_id:
                try:
                    print(f"🔄 取消币安订单: {binance_id}")
                    symbol = order.data._dataname
                    self.exchange.cancel_order(binance_id, symbol)
                except Exception as e:
                    print(f"❌ 取消订单失败: {e}")

    def get_binance_id(self, order):
        # 兼容旧代码调用
        return self.get_binance_id_by_order(order)
