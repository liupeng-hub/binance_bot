import backtrader as bt
from collections import defaultdict
from src.utils.log_utils import format_log

class AmplitudeStrategy(bt.Strategy):
    """
    Amplitude Distribution Strategy
    """
    display_name = "振幅分布策略"

    algo_description = """
### 策略原理
一种基于统计套利的动态网格策略。

* **统计分析**: 统计过去 N 天的日振幅 (High-Low/Open) 分布。
* **动态权重**: 根据振幅分布概率，动态分配不同跌幅档位的资金权重 (Kelley 公式变种)。
* **执行**: 高概率出现的振幅区间分配更多资金，低概率区间分配较少资金。

### 适用场景
* 适合长期运行，自动适应市场波动率的变化。
* **风险**: 模型依赖历史数据，如果市场波动特性发生结构性改变（如突然的黑天鹅），模型可能滞后。
    """

    params = (
        ('lookback_period', 30),
        ('leverage', 10),
        ('decay', 0.5),
        ('fee_rate', 0.002),
        ('min_trade_interval', 5),
    )

    params_config = {
        'lookback_period': {'label': '回溯周期 (天)', 'help': '计算振幅分布的历史数据天数'},
        'leverage': {'label': '杠杆倍数', 'help': '用于计算预期收益的杠杆倍数'},
        'decay': {'label': '衰减系数', 'help': '概率衰减因子'},
        'fee_rate': {'label': '费率', 'help': '交易费率'},
        'min_trade_interval': {'label': '最小交易间隔 (秒)', 'help': '最小交易时间间隔'},
    }

    def __init__(self):
        print("DEBUG: AmplitudeStrategy.__init__ called")
        self.amplitudes = []
        self.strategy_weights = {}
        
        # 记录日内最高最低
        self.daily_high = None
        self.daily_low = None
        self.daily_open = None
        self.last_date = None
        
        # Recalculate daily
        # self.add_timer(
        #     when=bt.timer.SESSION_END,
        #     monthdays=[],
        #     monthcarry=True,
        #     timername='recalc_stats'
        # )

    def next(self):
        # 调试打印
        if len(self) < 5 or len(self) % 10000 == 0:
            print(f"DEBUG: Processing bar {len(self)}")

        current_date = self.data.datetime.date(0)
        
        # 初始化上一日期
        if self.last_date is None:
            self.last_date = current_date
            self.daily_open = self.data.open[0]
            self.daily_high = self.data.high[0]
            self.daily_low = self.data.low[0]
            return

        # 检测日期变更
        if current_date != self.last_date:
            # 结算上一天
            if self.daily_open and self.daily_open > 0:
                amp = (self.daily_high - self.daily_low) / self.daily_open
                self.amplitudes.append(amp)
                self.log(f"记录日振幅: {amp:.2%} (日期: {self.last_date})")
                
            self.recalculate_stats()
            
            # 重置为新的一天
            self.daily_open = self.data.open[0]
            self.daily_high = self.data.high[0]
            self.daily_low = self.data.low[0]
            self.last_date = current_date
        else:
            # 同一天，更新高低
            self.daily_high = max(self.daily_high, self.data.high[0])
            self.daily_low = min(self.daily_low, self.data.low[0])

    def recalculate_stats(self):
        # 注意: len(self) 是 bar 的数量，不是天数。这里我们用 amplitudes 的长度判断
        if len(self.amplitudes) < self.p.lookback_period:
            return

        recent_amps = self.amplitudes[-self.p.lookback_period:]
        if not recent_amps: return

        weights, _ = self.calculate_strategy_weights(recent_amps)
        self.strategy_weights = weights
        
        self.log(f"策略权重已更新: {self.strategy_weights}")
        self.update_grids()

    def calculate_strategy_weights(self, amplitudes):
        total_count = len(amplitudes)
        if total_count == 0: return {}, {}

        bins = defaultdict(int)
        for amp in amplitudes:
            amp_pct = amp * 100
            if amp_pct >= 10: bin_idx = 10
            else:
                bin_idx = int(amp_pct) + 1
                if bin_idx > 10: bin_idx = 10
            bins[bin_idx] += 1

        total_adj_ret = 0
        calculated_bins = []

        for i in range(1, 11):
            count = bins[i]
            prob = count / total_count
            
            if i == 10:
                lev_return = -1.0
            else:
                gross_return = (i / 100.0) * self.p.leverage
                effective_fee = self.p.fee_rate * self.p.leverage
                net_return = gross_return - effective_fee
                if net_return < 0: net_return = -effective_fee
                lev_return = net_return

            exp_ret = lev_return * prob
            adj_ret = self.p.decay * exp_ret * prob
            
            calculated_bins.append({"amp_bin": i, "adj_ret": adj_ret})
            if adj_ret > 0: total_adj_ret += adj_ret

        weights = {}
        for item in calculated_bins:
            if item["adj_ret"] > 0:
                w = item["adj_ret"] / total_adj_ret if total_adj_ret > 0 else 0
                weights[item["amp_bin"]] = w
        
        return weights, bins

    def update_grids(self):
        if not self.strategy_weights:
            return

        new_grids = []
        for amp_bin, weight in self.strategy_weights.items():
            trigger_drop = (amp_bin - 0.5) / 100.0
            amplitude_pct = 1.0
            
            new_grids.append({
                "id": f"dynamic_grid_{amp_bin}",
                "trigger_drop": trigger_drop,
                "amplitude_pct": amplitude_pct,
                "weight": weight
            })
            
        self.log(f"生成新网格配置: {len(new_grids)} 个网格")
        for g in new_grids:
            self.log(f"  - 触发跌幅: {g['trigger_drop']:.2%}, 权重: {g['weight']:.2%}")

    def log(self, txt, dt=None, level='INFO'):
        dt = dt or self.datas[0].datetime.datetime(0)
        # 统一日志格式
        print(format_log(dt, self.data._name, txt, level=level))

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
