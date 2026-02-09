import backtrader as bt
from src.utils.log_utils import format_log

class SMACrossStrategy(bt.Strategy):
    """
    双均线交叉策略 (Simple Moving Average Crossover)
    当快线向上穿过慢线时买入，向下穿过慢线时卖出。
    """
    display_name = "双均线交叉策略"

    algo_description = """
### 策略原理
最经典的趋势跟踪策略之一。

* **买入信号**: 快速均线 (Fast SMA) 上穿 慢速均线 (Slow SMA)，形成金叉。
* **卖出信号**: 快速均线 下穿 慢速均线，形成死叉。

### 适用场景
* 适合长期趋势明显的行情。
* **风险**: 滞后性较强。在震荡市中会频繁发出错误信号，导致由于滑点和手续费造成的持续亏损。
    """

    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )

    params_config = {
        'fast_period': {'label': '快线周期', 'help': '快速移动平均线周期'},
        'slow_period': {'label': '慢线周期', 'help': '慢速移动平均线周期'},
    }

    def __init__(self):
        self.fast_sma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)

    def log(self, txt, dt=None, level='INFO'):
        """Logging function for this strategy"""
        dt = dt or self.datas[0].datetime.datetime(0)
        print(format_log(dt, self.data._name, txt, level=level))

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.log(f'买入信号触发, {self.data.close[0]}', level='INFO')
                self.buy()
        elif self.crossover < 0:
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

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'交易盈亏, 毛利 {trade.pnl:.2f}, 净利 {trade.pnlcomm:.2f}', level='TRADE')
