from abc import ABC, abstractmethod
import backtrader as bt

class OrderStateNotifier(ABC):
    """
    订单状态更新通知器（抽象基类）

    职责：
    - 实盘：通过 WebSocket 接收订单状态更新
    - 回测：模拟订单即时成交
    """

    @abstractmethod
    def start(self):
        """启动通知器"""
        pass

    @abstractmethod
    def stop(self):
        """停止通知器"""
        pass

    @abstractmethod
    def update_order_state(self, bt_order, status, filled_qty=0, filled_price=0):
        """
        更新订单状态

        Args:
            bt_order: Backtrader 订单对象
            status: 订单状态（bt.Order.Accepted, bt.Order.Completed 等）
            filled_qty: 成交数量
            filled_price: 成交价格
        """
        pass
