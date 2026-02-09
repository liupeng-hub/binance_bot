class RiskManager:
    """
    全局风控管理器 (Global Risk Manager)
    用于在订单提交前进行事前风控检查。
    """
    def __init__(self, config=None):
        self.config = config or {}
        
        # 加载风控规则
        self.max_order_val = self.config.get('max_order_value', 10000.0) # 单笔最大金额 (USDT)
        self.max_daily_drawdown = self.config.get('max_daily_drawdown', 0.05) # 日内最大回撤 (5%)
        self.restricted_symbols = self.config.get('restricted_symbols', []) # 禁止交易名单
        
        self.initial_equity = None
        self.daily_high_equity = None

    def update_equity(self, current_equity):
        """
        更新当前净值状态 (通常在每个 Bar 或订单检查前调用)
        """
        if self.initial_equity is None:
            self.initial_equity = current_equity
            self.daily_high_equity = current_equity
            
        self.daily_high_equity = max(self.daily_high_equity, current_equity)

    def check_order(self, order_info):
        """
        检查订单是否合规
        Args:
            order_info (dict): {
                'symbol': str,
                'side': 'BUY'/'SELL',
                'price': float,
                'size': float,
                'current_equity': float
            }
        Returns:
            bool: True if safe, False if rejected
            str: Rejection reason
        """
        symbol = order_info.get('symbol')
        price = order_info.get('price')
        size = order_info.get('size')
        current_equity = order_info.get('current_equity')
        
        # 0. 更新净值状态
        if current_equity:
            self.update_equity(current_equity)

        # 1. 黑名单检查
        if symbol in self.restricted_symbols:
            return False, f"Risk: Symbol {symbol} is restricted."

        # 2. 单笔金额限制
        # 注意: 如果 price 是 0 (市价单)，可能需要估算。这里假设传入的是预估成交价或当前市价。
        if price and size:
            order_value = price * abs(size)
            if order_value > self.max_order_val:
                return False, f"Risk: Order value {order_value:.2f} exceeds limit {self.max_order_val}."

        # 3. 日内回撤限制
        # 如果当前净值相对于日内高点回撤超过阈值，禁止开仓 (平仓通常允许，但这里简单起见一刀切，或者需要区分 side)
        # 改进: 允许 SELL/CLOSE 操作以降低风险
        if current_equity and self.daily_high_equity > 0:
            drawdown = (self.daily_high_equity - current_equity) / self.daily_high_equity
            if drawdown > self.max_daily_drawdown:
                # 如果是开仓 (BUY)，则禁止
                # 如果是平仓 (SELL)，理论上应该允许，但 Backtrader 的 size 正负取决于方向
                # 简单起见，如果处于风控状态，只允许减仓 (降低风险 exposure)
                # 这里暂且只做简单的回撤报警/禁止开新仓
                if order_info.get('side') == 'BUY': 
                    return False, f"Risk: Daily drawdown {drawdown:.2%} exceeds limit {self.max_daily_drawdown:.2%}."

        return True, "Passed"
