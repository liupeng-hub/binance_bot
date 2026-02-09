import backtrader as bt
from src.utils.log_utils import format_log

class MonitorStrategy(bt.Strategy):
    """
    监控策略
    用于实时监控价格波动和持仓盈亏，触发预警。
    """
    params = (
        ('warning_threshold', 0.05), # 5%
    )

    def __init__(self):
        self.last_warning_time = None
        self.d = self.datas[0]
            
    def next(self):
        # 计算当前浮动盈亏
        value = self.broker.get_value()
        cash = self.broker.get_cash()
        
        # 简单预警逻辑：如果回撤超过阈值
        if value < self.initial_cash * (1 - self.p.warning_threshold):
             self.log(f"价格预警: 账户净值低于阈值! 当前: {value:.2f}", level='WARNING')

    def log(self, txt, dt=None, level='INFO'):
        dt = dt or self.d.datetime.datetime(0)
        # 统一使用中文时间格式和无英文前缀
        print(format_log(dt, self.d._name, txt, level=level))
