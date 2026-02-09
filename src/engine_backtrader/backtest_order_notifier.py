import backtrader as bt
from .order_state_notifier import OrderStateNotifier

class BacktestOrderNotifier(OrderStateNotifier):
    """
    回测订单状态通知器

    实现：
    - 订单即时成交（模拟）
    - 不需要 WebSocket
    - 直接更新订单状态
    """

    def __init__(self, broker):
        self.broker = broker

    def start(self):
        """启动回测通知器"""
        print("✅ 回测订单通知器已启动（即时成交模式）")

    def stop(self):
        """停止回测通知器"""
        print("🛑 回测订单通知器已停止")

    def update_order_state(self, bt_order, status, filled_qty=0, filled_price=0):
        """
        更新订单状态（回测模式下即时确认）

        注意：在回测模式下，Backtrader 的 BrokerBack 会自动处理订单成交
        这里主要用于通知策略层
        """
        # 更新订单状态
        bt_order.status = status

        # 更新成交信息
        if filled_qty > 0:
            bt_order.executed.size += filled_qty
            bt_order.executed.price = filled_price

        # 触发 Backtrader 订单回调
        self.broker.notify(bt_order)
