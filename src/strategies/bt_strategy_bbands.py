import backtrader as bt
from src.utils.log_utils import format_log

class BBandsStrategy(bt.Strategy):
    """
    布林带均值回归策略
    价格跌破下轨时买入(预期回归)，突破上轨时卖出。
    """
    display_name = "布林带均值回归"

    algo_description = """
### 策略原理
利用布林带 (Bollinger Bands) 指标进行均值回归交易。

* **买入信号**: 价格跌破布林带下轨 (Lower Band)，预期价格将回归中轨。
* **卖出信号**: 价格突破布林带上轨 (Upper Band)，预期价格受阻回落。

### 适用场景
* 适合震荡行情。
* **风险**: 在强劲的单边趋势中，价格可能长时间沿着上轨或下轨运行，导致逆势操作亏损。
    """

    params = (
        ('period', 20),
        ('devfactor', 2.0),
    )

    params_config = {
        'period': {'label': '均线周期', 'help': '布林带中轨 (SMA) 周期'},
        'devfactor': {'label': '标准差倍数', 'help': '布林带宽度倍数 (通常为 2.0)'},
    }

    def __init__(self):
        # 创建布林带指标
        self.bb = bt.indicators.BollingerBands(
            self.data.close, 
            period=self.p.period, 
            devfactor=self.p.devfactor
        )

    def log(self, txt, dt=None, level='INFO'):
        dt = dt or self.datas[0].datetime.datetime(0)
        print(format_log(dt, self.data._name, txt, level=level))

    def next(self):
        if not self.position:
            # 价格跌破下轨，预期回归均值，买入
            if self.data.close < self.bb.lines.bot:
                self.log(f'买入信号触发, {self.data.close[0]}', level='INFO')
                self.buy()
        else:
            # 价格突破上轨，平仓
            if self.data.close > self.bb.lines.top:
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
