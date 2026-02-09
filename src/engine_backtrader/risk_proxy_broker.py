import backtrader as bt

class RiskProxyBroker:
    """
    代理 Broker，通过 Monkey Patching 拦截策略的下单请求并进行风控检查。
    它不继承 bt.BrokerBase，而是直接代理真实的 Broker 实例。
    """
    def __init__(self, real_broker, risk_manager):
        self._broker = real_broker
        self._risk_manager = risk_manager
        
        # Monkey Patch: 替换真实 Broker 的 submit 方法
        # 这样无论策略调用 broker.buy() 还是 broker.submit()，都会经过我们的检查
        self._original_submit = self._broker.submit
        self._broker.submit = self.submit_with_check
        
        # 确保代理对象也有 set_order_notifier 方法
        if hasattr(self._broker, 'set_order_notifier'):
            self.set_order_notifier = self._broker.set_order_notifier

    def __getattr__(self, name):
        # 将所有调用转发给真实的 Broker
        return getattr(self._broker, name)

    def submit_with_check(self, order, **kwargs):
        """
        拦截下单请求 (Monkey Patched submit)
        """
        # 1. 获取当前状态
        # 注意：这里要调用 self._broker 的方法，因为 self 只是 Proxy
        current_value = self._broker.getvalue()
        
        # 2. 准备订单信息
        price = order.price
        if not price and order.data:
            # 如果是市价单，使用当前 Close 价估算
            # 注意: order.data 可能还没准备好 line 0，需要防御性编程
            try:
                price = order.data.close[0]
            except:
                price = 0.0
            
        side = 'BUY' if order.isbuy() else 'SELL'
        
        order_info = {
            'symbol': order.data._name if hasattr(order.data, '_name') else 'Unknown',
            'side': side,
            'price': price,
            'size': order.size,
            'current_equity': current_value
        }
        
        # 3. 调用风控检查
        is_safe, reason = self._risk_manager.check_order(order_info)
        
        if not is_safe:
            print(f"🛑 [RISK REJECT] {reason}")
            # 拒绝订单
            # 我们不能直接调用 order.reject，因为那通常需要 broker 上下文
            # Backtrader 的 order.reject(broker) 会调用 broker.notify(order)
            
            order.reject(self._broker)
            # 确保通知被发送 (有些 broker 实现可能不一样)
            if hasattr(self._broker, 'notify'):
                self._broker.notify(order)
                
            return order
        
        # 4. 检查通过，调用原始 submit，并透传所有参数 (如 check=...)
        return self._original_submit(order, **kwargs)
