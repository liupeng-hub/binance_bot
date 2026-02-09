import backtrader as bt
from src.utils.db_models import TradeRecord, EquityRecord, SignalRecord, StrategyInstance
from src.utils.db_manager import db_manager
from datetime import datetime
import json

class SQLiteAnalyzer(bt.Analyzer):
    """
    实时将交易和净值记录写入 SQLite 数据库
    """
    params = (
        ('user_id', None),
        ('instance_id', None),
    )

    def __init__(self):
        self.session = db_manager.get_session()
        db_manager.init_db() # 确保存储表存在
        self.strategy_name = "Unknown"
        self.user_id = self.p.user_id
        self.instance_id = self.p.instance_id

    def start(self):
        self.strategy_name = self.strategy.__class__.__name__

    def notify_trade(self, trade):
        if trade.isclosed:
            # 判断方向
            # Backtrader 的 Trade 对象通常有 long 属性 (bool)
            # 如果没有，尝试使用 history 或 size
            if hasattr(trade, 'long'):
                side = 'LONG' if trade.long else 'SHORT'
            elif len(trade.history) > 0:
                side = 'LONG' if trade.history[0].event.size > 0 else 'SHORT'
            else:
                # 回退：根据 size 正负判断 (通常正为多，负为空)
                side = 'LONG' if trade.size > 0 else 'SHORT'

            # 记录已结平的交易 (Round-Trip)
            # 尝试提取更多信息
            # 提取该交易包含的所有 Order Ref (用于关联)
            related_orders = []
            if len(trade.history) > 0:
                for hist in trade.history:
                    if hasattr(hist, 'event') and hasattr(hist.event, 'order'):
                         related_orders.append(hist.event.order.ref)

            extra = {
                'open_dt': str(bt.num2date(trade.dtopen)),
                'close_dt': str(bt.num2date(trade.dtclose)),
                'duration_bars': trade.barlen,
                'pnl_net': trade.pnlcomm, # 净利润 (扣除手续费)
                'related_orders': related_orders # 关联的订单ID列表
            }
            
            record = TradeRecord(
                user_id=self.user_id,
                instance_id=self.instance_id,
                strategy_id=self.strategy_name,
                symbol=trade.data._name,
                side=side,
                price=trade.price,
                size=trade.size,
                value=trade.value,
                commission=trade.commission,
                pnl=trade.pnl,
                timestamp=bt.num2date(trade.dtclose),
                order_id=str(trade.ref), # 使用 ref 作为简单关联
                extra_data=json.dumps(extra)
            )
            self.session.add(record)
            self.session.commit()

    def notify_order(self, order):
        if order.status in [order.Completed]:
            # 记录每一次成交 (Execution)
            side = 'BUY' if order.isbuy() else 'SELL'
            
            extra = {
                'type': 'ORDER_EXECUTION',
                'order_ref': order.ref,
                'status': 'Completed'
            }

            record = TradeRecord(
                user_id=self.user_id,
                instance_id=self.instance_id,
                strategy_id=self.strategy_name,
                symbol=order.data._name,
                side=side,
                price=order.executed.price,
                size=order.executed.size,
                value=order.executed.value,
                commission=order.executed.comm,
                pnl=0.0, # 具体的成交没有 PnL (或是未实现)
                timestamp=bt.num2date(order.executed.dt),
                order_id=str(order.ref),
                extra_data=json.dumps(extra)
            )
            self.session.add(record)
            self.session.commit()

    def next(self):
        # 记录每日/每Bar净值 (频率可控，例如每天记录一次)
        # 这里为了演示，每个 Bar 都记录可能会太多，建议仅在实盘或特定时间记录
        # 模拟盘建议只在一天结束时记录
        
        # 简单的频率控制：如果是实盘，或者每天收盘时
        current_dt = self.strategy.datetime.datetime()
        
        # 仅记录 Equity，这里不做太高频的写入以免影响性能
        # 示例：每小时记录一次，或者每天
        if len(self.strategy) % 60 == 0: # 假设 1m K线，每小时记录一次
             self._record_equity(current_dt)
             
        # 更新进度 (每 100 个 Bar 更新一次，避免频繁写库)
        if len(self.strategy) % 100 == 0:
            self._update_progress()

    def _update_progress(self):
        try:
            # 仅在回测模式下计算进度
            # 实盘模式 buflen 可能无意义或一直在变
            if hasattr(self.datas[0], 'buflen'):
                total_bars = self.datas[0].buflen()
                current_bar = len(self.strategy)
                
                if total_bars > 0:
                    progress = (current_bar / total_bars) * 100.0
                    progress = min(99.9, progress) # 运行中不超过 100
                    
                    # 更新 DB
                    # 为了避免 session 冲突，这里可以尝试使用独立的 session 或者小心操作
                    # 简单起见，复用 session
                    instance = self.session.query(StrategyInstance).filter_by(id=self.instance_id).first()
                    if instance:
                        instance.progress = progress
                        self.session.commit()
        except Exception:
            pass

    def _record_equity(self, dt):
        value = self.strategy.broker.getvalue()
        cash = self.strategy.broker.getcash()
        
        record = EquityRecord(
            user_id=self.user_id,
            instance_id=self.instance_id,
            timestamp=dt,
            total_value=value,
            cash=cash
        )
        self.session.add(record)
        self.session.commit()

    def stop(self):
        # 结束时标记进度为 100%
        try:
            instance = self.session.query(StrategyInstance).filter_by(id=self.instance_id).first()
            if instance:
                instance.progress = 100.0
                self.session.commit()
        except:
            pass
        self.session.close()
