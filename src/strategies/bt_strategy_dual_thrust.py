import backtrader as bt
from src.utils.log_utils import format_log

class DualThrustStrategy(bt.Strategy):
    """
    Dual Thrust 区间突破策略
    根据前N日的波动区间计算上下轨，突破上轨做多，跌破下轨做空(平仓)。
    """
    display_name = "Dual Thrust 区间突破"

    algo_description = """
### 策略原理
一种经典的日内区间突破策略。

* **区间计算**: 根据前 N 日的 (High - Close) 和 (Close - Low) 计算波动区间 Range。
* **上轨**: 今日开盘价 + K1 * Range
* **下轨**: 今日开盘价 - K2 * Range
* **交易**: 价格突破上轨做多，跌破下轨做空。

### 适用场景
* 适合日内波动较大且具有突破性的行情。
* **风险**: 假突破。价格突破后迅速回调可能导致止损。
    """

    params = (
        ('period', 5),  # 计算 Range 的周期
        ('k1', 0.5),   # 上轨系数
        ('k2', 0.5),   # 下轨系数
    )

    params_config = {
        'period': {'label': '区间周期', 'help': '计算 Range 的历史周期'},
        'k1': {'label': '上轨系数 (K1)', 'help': 'Buy Line = Open + K1 * Range'},
        'k2': {'label': '下轨系数 (K2)', 'help': 'Sell Line = Open - K2 * Range'},
    }

    def __init__(self):
        # 获取前 N 日的最高价、最低价和收盘价
        self.hh = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.hc = bt.indicators.Highest(self.data.close, period=self.p.period)
        self.ll = bt.indicators.Lowest(self.data.low, period=self.p.period)
        self.lc = bt.indicators.Lowest(self.data.close, period=self.p.period)

    def log(self, txt, dt=None, level='INFO'):
        dt = dt or self.datas[0].datetime.datetime(0)
        print(format_log(dt, self.data._name, txt, level=level))

    def next(self):
        # Dual Thrust 逻辑通常使用前 N 日的数据计算今日的上下轨
        # 使用 [-1] 获取上一个 Bar 结束时的指标值
        r1 = self.hh[-1] - self.lc[-1]
        r2 = self.hc[-1] - self.ll[-1]
        rng = max(r1, r2)
        
        # 以今日开盘价为基准计算上下轨
        buy_line = self.data.open[0] + self.p.k1 * rng
        sell_line = self.data.open[0] - self.p.k2 * rng

        if not self.position:
            if self.data.close[0] > buy_line:
                self.log(f'买入信号触发, {self.data.close[0]}', level='INFO')
                self.buy()
        else:
            if self.data.close[0] < sell_line:
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
