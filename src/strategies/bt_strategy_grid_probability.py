import backtrader as bt
import numpy as np
import scipy.stats as stats
import pandas as pd
from datetime import datetime
from src.utils.log_utils import format_log

class GridProbabilityStrategy(bt.Strategy):
    """
    概率网格策略
    基于历史波动幅度分布计算概率，在低概率（极端）位置反向操作。
    """
    display_name = "概率网格策略"

    algo_description = """
### 策略原理
基于历史数据的波动幅度分布来计算交易概率。

* **数据分析**: 统计过去 N 天 (Lookback Period) 的日内振幅。
* **概率计算**: 计算当前价格波动处于历史分布的百分位。
* **逆势操作**: 
    * 当价格处于极高位（高概率区域）时，认为超买，触发卖出。
    * 当价格处于极低位（低概率区域）时，认为超卖，触发买入。

### 适用场景
* 适合均值回归特性的市场。
* **风险**: 遇到突破历史波动范围的极端单边行情时失效。
    """

    params = (
        ('lookback_period', 30),
        ('probability_threshold', 0.8),
    )

    params_config = {
        'lookback_period': {'label': '回溯周期 (天)', 'help': '计算概率分布的历史数据天数'},
        'probability_threshold': {'label': '概率阈值', 'help': '触发交易的概率阈值 (0-1)'},
    }

    def __init__(self):
        # 修复逻辑: 如果 symbol 为 None 或 'None' 字符串，则使用 datas[0]
        # 注意: 前端传来的 None 可能会变成字符串 'None'
        self.d = self.datas[0]

        self.amplitudes = []
        self.amp_probs = {}
        self.daily_open = None
        self.daily_high = None
        self.daily_low = None
        
        self.add_timer(
            when=bt.timer.SESSION_END,
            monthdays=[],
            monthcarry=True,
            timername='recalc_probs'
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        if timer.params.timername == 'recalc_probs':
            self.recalculate_probabilities()

    def recalculate_probabilities(self):
        if len(self.amplitudes) < self.p.lookback_period:
            return

        recent_amps = self.amplitudes[-self.p.lookback_period:]
        if not recent_amps: return
        
        sorted_amps = sorted(recent_amps)
        n = len(sorted_amps)
        
        self.amp_probs = {}
        for i, amp in enumerate(sorted_amps):
            prob = (i + 1) / n
            self.amp_probs[amp] = prob
            
        self.log(f"概率分布已更新 (样本数: {n})")

    def next(self):
        # 0. Initialize daily data if first run
        if self.daily_open is None:
            self.daily_open = self.d.open[0]
            self.daily_high = self.d.high[0]
            self.daily_low = self.d.low[0]

        # 1. Maintain daily High/Low from whatever timeframe we are on
        # Check boundary condition for index -1 (will fail on first bar)
        try:
             # 安全地检查日期变更，如果 index -1 不存在会抛出 IndexError
             is_new_day = (self.d.datetime.date(0) != self.d.datetime.date(-1))
        except IndexError:
             is_new_day = False
             
        if is_new_day:
            # New day
            self.daily_open = self.d.open[0]
            self.daily_high = self.d.high[0]
            self.daily_low = self.d.low[0]
        else:
            # Same day update
            if self.daily_high is None: self.daily_high = self.d.high[0]
            if self.daily_low is None: self.daily_low = self.d.low[0]
            
            self.daily_high = max(self.daily_high, self.d.high[0])
            self.daily_low = min(self.daily_low, self.d.low[0])
            
        # 2. Trading Logic
        if not self.amp_probs or not self.daily_open:
            return
            
        current_amp = (self.daily_high - self.daily_low) / self.daily_open
        
        current_prob = 0
        for amp, prob in self.amp_probs.items():
            if current_amp <= amp:
                current_prob = prob
                break
        else:
            current_prob = 1.0
            
        if current_prob >= self.p.probability_threshold:
            dist_to_high = (self.daily_high - self.d.close[0])
            dist_to_low = (self.d.close[0] - self.daily_low)
            
            if dist_to_high < dist_to_low:
                # Near High -> Short
                if self.position.size >= 0:
                    self.log(f"触发卖出信号: 分位点 {current_prob:.2%}, 价格 {self.d.close[0]:.2f}")
                    self.sell(data=self.d)
            else:
                # Near Low -> Buy
                if self.position.size <= 0:
                    self.log(f"触发买入信号: 分位点 {current_prob:.2%}, 价格 {self.d.close[0]:.2f}")
                    self.buy(data=self.d)

    def log(self, txt, dt=None):
        dt = dt or self.d.datetime.datetime(0)
        print(f'{dt.strftime("%Y-%m-%d %H:%M:%S")}, [{self.d._name}] {txt}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'买入成交, 价格: {order.executed.price:.2f}, 成本: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}')
            elif order.issell():
                self.log(f'卖出成交, 价格: {order.executed.price:.2f}, 成本: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}')
        
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'订单状态: {order.getstatusname()}')

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'交易盈亏, 毛利 {trade.pnl:.2f}, 净利 {trade.pnlcomm:.2f}')
