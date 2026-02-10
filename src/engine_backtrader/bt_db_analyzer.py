import backtrader as bt
from src.utils.db_models import TradeRecord, EquityRecord, SignalRecord, StrategyInstance, MarketData
from src.utils.db_manager import db_manager
from datetime import datetime
import json

class SQLiteAnalyzer(bt.Analyzer):
    """
    实时将交易、净值和市场数据写入 SQLite 数据库
    """
    params = (
        ('user_id', None),
        ('instance_id', None),
        ('mode', 'backtest'), # 新增 mode 参数
    )

    def __init__(self):
        self.session = db_manager.get_session()
        db_manager.init_db() # 确保存储表存在
        self.strategy_name = "Unknown"
        self.user_id = self.p.user_id
        self.instance_id = self.p.instance_id
        self.last_kline_time = None # 记录上一次保存 K 线的时间

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
        current_dt = self.strategy.datetime.datetime()
        
        # 1. 实时保存 K 线数据到 MarketData 表 (仅保存已完成的 Bar)
        # 这样 Web UI 就能通过 load_kline_data 看到最新的线
        self._record_kline(current_dt)

        # 2. 净值记录
        # 仅记录 Equity，这里不做太高频的写入以免影响性能
        # 示例：每小时记录一次，或者每 60 个 Bar
        if len(self.strategy) % 60 == 0: 
             self._record_equity(current_dt)
             
        # 3. 更新进度 (仅回测模式)
        if len(self.strategy) % 100 == 0:
            self._update_progress()

    def _record_kline(self, dt):
        """将当前 Bar 数据持久化到数据库，供 Web UI 实时显示"""
        try:
            # 1. 模式检查：回测模式不记录 K 线到数据库 (节省 IO)
            if self.p.mode != 'live':
                return

            # 2. 避免同一时间戳的重复处理（如果是同一秒的数据且价格没变，则跳过）
            # 注意：在实盘模式下，我们允许覆盖同一分钟的 Bar 以更新最新价格
            data = self.datas[0]
            
            # 如果是回测，last_kline_time 检查很有用
            # 如果是实盘，我们希望每一跳都更新 DB
            # 但为了性能，如果价格没变，也可以跳过
            # 这里简化为：实盘模式总是尝试更新 (SQLAlchemy merge 会处理)
            symbol = data._name
            # 尝试获取 timeframe 字符串 (e.g., '1m')
            # BinanceData 中存储了 binance_timeframe
            timeframe = getattr(data.p, 'binance_timeframe', '1m')
            
            # 检查是否已存在 (避免主键冲突)
            # 在高性能场景下可以先存入缓存或批量写入
            # 这里先简单实现：直接插入或忽略
            
            # 使用原生 SQL 以提高性能 (INSERT OR IGNORE)
            # 或者先查询
            # 为了兼容多种数据库，这里使用 SQLAlchemy 的逻辑
            
            k_record = MarketData(
                timestamp=dt,
                symbol=symbol,
                timeframe=timeframe,
                open=data.open[0],
                high=data.high[0],
                low=data.low[0],
                close=data.close[0],
                volume=data.volume[0]
            )
            
            # 注意：SQLite 的处理。如果主键重复会报错。
            # 我们先 commit 之前的，再处理这个。
            try:
                self.session.merge(k_record) # merge 会根据主键更新或插入
                self.session.commit()
                self.last_kline_time = dt
                # 打印持久化调试信息
                print(f"💾 [DB] 已保存 K线: {symbol} ({timeframe}) | 时间: {dt} | 收盘: {k_record.close}")
            except Exception as e:
                print(f"❌ [DB] 保存 K线失败: {e}")
                self.session.rollback()
        except Exception:
            pass

    def record_signal(self, signal_type, price, comment=""):
        """手动记录策略信号"""
        try:
            sig = SignalRecord(
                user_id=self.user_id,
                instance_id=self.instance_id,
                timestamp=self.strategy.datetime.datetime(),
                symbol=self.datas[0]._name,
                signal_type=signal_type,
                price=price,
                comment=comment
            )
            self.session.add(sig)
            self.session.commit()
        except Exception:
            pass


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
