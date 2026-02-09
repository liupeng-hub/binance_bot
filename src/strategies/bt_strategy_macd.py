import backtrader as bt
from src.utils.log_utils import format_log

class MACDStrategy(bt.Strategy):
    """
    MACD 趋势策略
    当 DIFF 线上穿 DEA 线(金叉)时买入，下穿(死叉)时卖出。
    """
    display_name = "MACD 趋势策略"

    algo_description = """
### 策略原理
利用 MACD 指标的快慢线交叉捕捉趋势。

* **买入信号**: 快线 (DIFF) 上穿慢线 (DEA) 形成金叉。
* **卖出信号**: 快线 (DIFF) 下穿慢线 (DEA) 形成死叉。

### 适用场景
* 适合波动明显的中长线趋势行情。
* **风险**: 在横盘震荡市中可能会产生频繁的假信号，导致连续止损。
    """

    params = (
        ('fast_period', 12),
        ('slow_period', 26),
        ('signal_period', 9),
    )

    params_config = {
        'fast_period': {'label': '快线周期', 'help': 'MACD 快线 (EMA) 周期'},
        'slow_period': {'label': '慢线周期', 'help': 'MACD 慢线 (EMA) 周期'},
        'signal_period': {'label': '信号线周期', 'help': 'Signal 线 (DEA) 周期'},
    }

    def __init__(self):
        # 创建 MACD 指标
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.fast_period,
            period_me2=self.p.slow_period,
            period_signal=self.p.signal_period
        )
        # 交叉信号：MACD线上穿Signal线为1，下穿为-1
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

    def log(self, txt, dt=None, level='INFO'):
        """Logging function for this strategy"""
        dt = dt or self.datas[0].datetime.datetime(0)
        print(format_log(dt, self.data._name, txt, level=level))

    def next(self):
        if not self.position:
            if self.crossover > 0:  # 金叉买入
                self.log(f'买入信号触发, {self.data.close[0]}', level='INFO')
                self.buy()
        elif self.crossover < 0:    # 死叉卖出
            self.log(f'卖出信号触发, {self.data.close[0]}', level='INFO')
            self.close()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'买入成交, 价格: {order.executed.price:.2f}, 成本: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}', level='ORDER')
            elif order.issell():
                self.log(f'卖出成交, 价格: {order.executed.price:.2f}, 成本: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}', level='ORDER')
        
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'订单状态: {order.getstatusname()}', level='WARNING')
            # 如果是保证金不足，打印更多信息
            if order.status == order.Margin:
                 self.log('保证金错误: 资金不足以执行订单。', level='ERROR')

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'交易盈亏, 毛利 {trade.pnl:.2f}, 净利 {trade.pnlcomm:.2f}', level='TRADE')
