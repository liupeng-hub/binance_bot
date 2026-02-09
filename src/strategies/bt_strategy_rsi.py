import backtrader as bt
from src.utils.log_utils import format_log

class RSIStrategy(bt.Strategy):
    """
    RSI 震荡策略 (Relative Strength Index)
    当 RSI 低于下轨(超卖)时买入，高于上轨(超买)时卖出。
    """
    display_name = "RSI 震荡策略"

    algo_description = """
### 策略原理
利用相对强弱指数 (RSI) 识别超买超卖状态。

* **买入信号**: RSI 低于设定的超卖阈值 (如 30)，认为市场超卖，即将反弹。
* **卖出信号**: RSI 高于设定的超买阈值 (如 70)，认为市场超买，即将回调。

### 适用场景
* 典型的震荡市策略。
* **风险**: 钝化现象。在强势上涨或下跌中，RSI 可能长期处于超买或超卖区，导致过早反向操作。
    """

    params = (
        ('period', 14),
        ('upper', 70),
        ('lower', 30),
    )

    params_config = {
        'period': {'label': 'RSI 周期', 'help': '计算 RSI 的时间周期'},
        'upper': {'label': '超买阈值', 'help': 'RSI 高于此值视为超买 (卖出信号)'},
        'lower': {'label': '超卖阈值', 'help': 'RSI 低于此值视为超卖 (买入信号)'},
    }

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.period)

    def log(self, txt, dt=None, level='INFO'):
        dt = dt or self.datas[0].datetime.datetime(0)
        print(format_log(dt, self.data._name, txt, level=level))

    def next(self):
        if not self.position:
            if self.rsi < self.p.lower:
                self.log(f'买入信号触发, {self.data.close[0]}', level='INFO')
                self.buy()
        else:
            if self.rsi > self.p.upper:
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
