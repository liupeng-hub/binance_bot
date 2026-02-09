import backtrader as bt
from datetime import datetime
import json
from src.utils.log_utils import format_log

class GridMartinStrategy(bt.Strategy):
    display_name = "网格马丁策略"

    algo_description = """
### 策略原理
结合了**网格交易**与**马丁格尔 (Martingale)** 加仓机制。

* **网格挂单**: 根据设定的百分比间隔，在当前价格下方分批挂买单。
* **马丁加仓**: 价格下跌时，逐步增加买入仓位（权重增加），以降低平均持仓成本。
* **反弹卖出**: 每个网格买单成交后，立即挂出对应的止盈卖单。

### 适用场景
* 适合震荡下跌或横盘震荡行情，利用价格回调获利。
* **风险**: 若行情单边暴跌，可能会积累大量仓位导致深套或爆仓。需严格设置止损。
    """

    params = (
        ('strategy_config', None),
        ('stop_loss_pct', 0.08),
        ('min_trade_interval', 5), # seconds
    )

    params_config = {
        'strategy_config': {'label': '网格配置 (JSON)', 'help': '网格参数配置，JSON格式'},
        'stop_loss_pct': {'label': '止损百分比', 'help': '触发止损的跌幅比例 (如 0.08 为 8%)'},
        'min_trade_interval': {'label': '最小交易间隔 (秒)', 'help': '两次交易之间的最小时间间隔'},
    }

    def __init__(self):
        # print(f"DEBUG: GridMartinStrategy __init__ called. Config type: {type(self.p.strategy_config)}")
        
        # Get data feed specific to this strategy instance
        self.d = self.datas[0]

        self.log(f"初始化 GridMartin 策略 (交易对: {self.d._name})...")

        self.order_map = {}
        self.grids_status = {}
        self.base_price = None
        self.last_trade_time = None

        # 1. Handle Config Parsing
        # If it's a string (JSON), parse it
        if isinstance(self.p.strategy_config, str):
            try:
                # Replace single quotes with double quotes if necessary (simple fix for python dict string)
                if "'" in self.p.strategy_config and '"' not in self.p.strategy_config:
                     self.p.strategy_config = self.p.strategy_config.replace("'", '"')
                
                self.p.strategy_config = json.loads(self.p.strategy_config)
                # print("DEBUG: Successfully parsed strategy_config from string.")
            except Exception as e:
                self.log(f"解析 strategy_config 失败: {e}")
                self.p.strategy_config = None

        # 2. Validate and Default Config
        if not self.p.strategy_config or not isinstance(self.p.strategy_config, dict) or 'grids' not in self.p.strategy_config:
            self.log("未找到有效的 strategy_config，使用默认 3 网格设置。")
            self.p.strategy_config = {
                'grids': [
                    {'id': 1, 'amplitude_pct': 1.0, 'trigger_drop': 0.01, 'weight': 0.1},
                    {'id': 2, 'amplitude_pct': 2.0, 'trigger_drop': 0.02, 'weight': 0.2},
                    {'id': 3, 'amplitude_pct': 3.0, 'trigger_drop': 0.03, 'weight': 0.3},
                ]
            }

        # 3. Initialize Grids
        for grid in self.p.strategy_config['grids']:
            grid_id = grid.get('id', grid['amplitude_pct'])
            self.grids_status[grid_id] = {'status': 'waiting', 'buy_price': 0}
            self.log(f"网格 {grid_id} 初始化完成，状态: 等待中")

    def check_market_close(self):
        """Check if market is closing. For Crypto, it's always open."""
        return False

    def log(self, txt, dt=None, level='INFO'):
        ''' Strategy logging function '''
        if dt is None:
            if len(self.d) > 0:
                dt = self.d.datetime.datetime(0)
            else:
                dt = datetime.now()
        # 使用结构化日志
        print(format_log(dt, self.d._name, txt, level=level))

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'交易盈亏, 毛利 {trade.pnl:.2f}, 净利 {trade.pnlcomm:.2f}', level='TRADE')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        order_info = self.order_map.get(order.ref)
        if not order_info:
            return

        grid_id = order_info['grid_id']

        # Check if order is completed
        if order.status == order.Completed:
            if order.isbuy():
                buy_price = order.executed.price
                self.log(f'网格 {grid_id} 买入成交, 价格: {buy_price:.2f}, 成本: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}', level='ORDER')
                
                # Place Sell Order
                amp = order_info['amp']
                qty = order_info['qty']
                
                target_sell_price = buy_price * (1 + amp / 100.0)
                stop_loss_price = buy_price * (1 - self.p.stop_loss_pct)
                
                self.log(f"网格 {grid_id} 挂出卖单, 目标价: {target_sell_price:.2f} (止损价: {stop_loss_price:.2f})", level='INFO')
                # 使用 tradeid 分组
                sell_order = self.sell(data=self.d, size=qty, price=target_sell_price, exectype=bt.Order.Limit, tradeid=int(grid_id))
                
                # Update grid status and map new order
                self.grids_status[grid_id]['status'] = 'held'
                self.grids_status[grid_id]['buy_price'] = buy_price
                self.order_map[sell_order.ref] = {
                    'grid_id': grid_id,
                    'amp': amp,
                    'side': 'SELL',
                    'qty': qty,
                    'stop_loss_price': stop_loss_price,
                    'order_obj': sell_order
                }
                del self.order_map[order.ref]

            elif order.issell():
                self.log(f'网格 {grid_id} 卖出成交, 价格: {order.executed.price:.2f}, 成本: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}', level='ORDER')
                # Reset grid status
                self.grids_status[grid_id]['status'] = 'waiting'
                self.log(f"网格 {grid_id} 重置为 'waiting'", level='INFO')
                del self.order_map[order.ref]

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'订单状态: {order.getstatusname()}, Ref: {order.ref}, 网格: {grid_id}', level='WARNING')
            self.grids_status[grid_id]['status'] = 'waiting'
            del self.order_map[order.ref]

    def next(self):
        current_price = self.d.close[0]

        if self.base_price is None:
            self.base_price = current_price
            self.log(f'基准价格设定为: {self.base_price:.2f}')
            return

        # Trailing Base Price Logic
        first_grid_drop = self.p.strategy_config['grids'][0]['trigger_drop']
        if current_price > self.base_price * (1 + first_grid_drop):
            old_base = self.base_price
            self.base_price = current_price
            self.log(f'基准价格上调: {old_base:.2f} -> {self.base_price:.2f}')

        # Check Stop Loss
        for order_ref, info in list(self.order_map.items()):
            if info['side'] == 'SELL' and info.get('stop_loss_price'):
                if current_price <= info['stop_loss_price']:
                    self.log(f"网格 {info['grid_id']} 触发止损，价格 {current_price:.2f}")
                    
                    order_to_cancel = info.get('order_obj')
                    if order_to_cancel:
                        self.cancel(order_to_cancel)
                    
                    # 使用 tradeid 分组
                    self.sell(data=self.d, size=info['qty'], exectype=bt.Order.Market, tradeid=int(info['grid_id']))
                    return 

        # Check Grid Triggers
        current_time = self.d.datetime.datetime(0)
        if self.last_trade_time:
            time_diff = (current_time - self.last_trade_time).total_seconds()
            if time_diff < self.p.min_trade_interval:
                return

        for grid in self.p.strategy_config['grids']:
            grid_id = grid.get('id', grid['amplitude_pct'])
            if self.grids_status[grid_id]['status'] == 'waiting':
                target_buy_price = self.base_price * (1 - grid['trigger_drop'])
                if current_price <= target_buy_price:
                    self.log(f"网格 {grid_id} 触发买入，价格 {current_price:.2f}")
                    
                    total_value = self.broker.get_value()
                    amount = total_value * grid['weight']
                    # Crypto quantities can be fractional, but let's keep it simple for now or use step size
                    # For simplicity, casting to float with precision might be needed.
                    # CCXT handles precision, but Backtrader uses float size.
                    # Let's assume size is amount / price.
                    qty = amount / current_price
                    
                    # Minimal check to avoid dust errors (though Binance handles small orders with error)
                    if qty <= 0:
                        continue

                    self.log(f"提交市价买单，数量 {qty:.4f}，现金: {self.broker.getcash():.2f}")
                    # 使用 tradeid 分组
                    buy_order = self.buy(data=self.d, size=qty, exectype=bt.Order.Market, tradeid=int(grid_id))
                    
                    self.last_trade_time = current_time 

                    self.order_map[buy_order.ref] = {
                        'grid_id': grid_id,
                        'amp': grid['amplitude_pct'],
                        'side': 'BUY',
                        'qty': qty
                    }
                    self.grids_status[grid_id]['status'] = 'pending_buy' 
                    return
