
import os
import json
import time
import ccxt
import threading
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class BinanceBot:
    def __init__(self, config_path=None):
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_SECRET_KEY")
        
        if not self.api_key or not self.api_secret:
            raise ValueError("请在 .env 文件中配置 BINANCE_API_KEY 和 BINANCE_SECRET_KEY")

        # 初始化交易所 (币安合约)
        self.exchange = ccxt.binanceusdm({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
            'proxies': {
                'http': 'http://127.0.0.1:1087',
                'https': 'http://127.0.0.1:1087',
            },
            'options': {
                'defaultType': 'future'
            }
        })
        
        # 加载策略
        if not config_path:
            strategies_dir = "strategies"
            if os.path.exists(strategies_dir):
                # 递归查找所有 .json 文件
                files = []
                for root, dirs, filenames in os.walk(strategies_dir):
                    for f in filenames:
                        if f.endswith(".json"):
                            files.append(os.path.join(root, f))
                
                if files:
                    # 按修改时间排序，加载最新的
                    config_path = max(files, key=os.path.getmtime)
                    print(f"自动选择最新策略配置: {config_path}")
        
        if not config_path:
            raise FileNotFoundError("未找到策略配置文件，请先运行 backtest.py")
            
        self.load_config(config_path)
        
        # 运行时状态
        self.base_price = None
        self.grids_status = {} # {grid_id: {'status': 'waiting/held', 'buy_price': 0}}
        self.order_map = {} # {order_id: {'grid_id': id, 'amp': amp, 'side': 'BUY'/'SELL', 'qty': qty}}
        self.lock = threading.Lock()
        
        self.last_trade_time = 0
        self.min_trade_interval = 5 
        
    def load_config(self, path):
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        self.symbol = config["symbol"]
        self.leverage = config.get("leverage", 10)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.08) # 默认8%
        best_period = config["best_period"]
        
        if "strategies" in config:
            self.strategy = config["strategies"][best_period]
        else:
            self.strategy = config

        print(f"已加载策略: {self.symbol} | 周期: {best_period} | 杠杆: {self.leverage}x | 止损: {self.stop_loss_pct:.1%}")
        print("网格配置:")
        for g in self.strategy['grids']:
            print(f"  触发: {g['amplitude_pct']}% | 权重: {g['weight']}")
            
    def init_exchange(self):
        """初始化交易所设置"""
        try:
            self.exchange.set_leverage(self.leverage, self.symbol)
            print("杠杆设置成功。")
        except Exception as e:
            print(f"设置杠杆警告: {e}")

    def get_market_price(self):
        ticker = self.exchange.fetch_ticker(self.symbol)
        return float(ticker['last'])

    def get_account_balance(self):
        """获取 USDT 可用余额"""
        bal = self.exchange.fetch_balance()
        return float(bal['USDT']['free'])

    def check_order_status(self, current_price=None):
        """
        模拟事件驱动: 轮询订单状态
        检查 order_map 中的订单是否成交 + 止损检查
        """
        if not self.order_map:
            return

        try:
            if current_price is None:
                current_price = self.get_market_price()

            # 这里采用简单策略: 遍历 order_map 中 'OPEN' 的订单进行查询
            to_remove = []
            
            for order_id, info in list(self.order_map.items()):
                if info.get('status') == 'FILLED':
                    continue
                
                # --- 止损检查 ---
                if info['side'] == 'SELL' and info.get('stop_loss_price'):
                    if current_price <= info['stop_loss_price']:
                        print(f"🛑 触发止损! (网格 {info['amp']}%) 现价 {current_price} <= 止损价 {info['stop_loss_price']:.4f}")
                        self.execute_stop_loss(order_id, info)
                        to_remove.append(order_id)
                        continue

                try:
                    order = self.exchange.fetch_order(order_id, self.symbol)
                    status = order['status'] # 'open', 'closed', 'canceled'
                    
                    if status == 'closed': # 成交
                        print(f"✅ 订单成交: {info['side']} {info['qty']} (ID: {order_id})")
                        self.handle_order_filled(order_id, info, order)
                        info['status'] = 'FILLED' # 标记为处理过
                        to_remove.append(order_id)
                        
                    elif status == 'canceled':
                        print(f"⚠️ 订单已取消: {order_id}")
                        to_remove.append(order_id)
                        # 如果是买单被取消，重置网格状态
                        if info['side'] == 'BUY':
                             grid_id = info['grid_id']
                             self.grids_status[grid_id] = {'status': 'waiting', 'buy_price': 0}

                except Exception as e:
                    print(f"查询订单 {order_id} 失败: {e}")
            
            # 清理已完成的订单记录
            for oid in to_remove:
                self.order_map.pop(oid, None)
                
        except Exception as e:
            print(f"检查订单状态出错: {e}")

    def handle_order_filled(self, order_id, info, order_data):
        """处理成交事件"""
        grid_id = info['grid_id']
        amp = info['amp']
        side = info['side']
        qty = info['qty']
        avg_price = float(order_data.get('average', order_data.get('price')))
        
        with self.lock:
            if side == 'BUY':
                # 买入成交 -> 挂止盈单
                target_sell_price = avg_price * (1 + amp / 100.0)
                stop_loss_price = avg_price * (1 - self.stop_loss_pct)
                print(f"🔄 自动挂止盈单 (网格 {grid_id}): 目标价 {target_sell_price:.4f} | 止损价 {stop_loss_price:.4f}")
                self.place_limit_sell(target_sell_price, qty, amp, grid_id, stop_loss_price)
                
                # 更新状态
                self.grids_status[grid_id] = {'status': 'held', 'buy_price': avg_price}
                
            elif side == 'SELL':
                # 卖出成交 -> 止盈完成
                print(f"💰 网格 {grid_id} 止盈完成! 获利 ~{amp}%")
                self.grids_status[grid_id] = {'status': 'waiting', 'buy_price': 0}

    def place_limit_sell(self, price, qty, amp, grid_id, stop_loss_price=None):
        try:
            # 价格精度调整 (Binance严格要求)
            price = self.exchange.price_to_precision(self.symbol, price)
            qty = self.exchange.amount_to_precision(self.symbol, qty)
            
            order = self.exchange.create_order(
                symbol=self.symbol,
                type='limit',
                side='sell',
                amount=qty,
                price=price
            )
            
            self.order_map[order['id']] = {
                'grid_id': grid_id,
                'amp': amp,
                'side': 'SELL',
                'qty': qty,
                'status': 'OPEN',
                'stop_loss_price': stop_loss_price
            }
            print(f"挂单成功: 卖出 {qty} @ {price} (ID: {order['id']})")
            
        except Exception as e:
            print(f"自动挂卖单失败: {e}")

    def execute_buy(self, price, weight, amp, grid_id):
        try:
            usdt_balance = self.get_account_balance()
            
            # 资金分配: 10% 安全仓位 (改为使用 weight)
            # weight 是如 0.1 (10%)
            allocation_ratio = weight
            target_value = usdt_balance * allocation_ratio * self.leverage
            
            if target_value < 6: # 币安最小约 5U
                print(f"资金不足以开单 (分配额 {target_value:.2f}U < 6U)")
                return False

            qty = target_value / price
            qty = self.exchange.amount_to_precision(self.symbol, qty)
            
            # 使用略高价格确保成交 (Taker) 或者挂单 (Maker)
            # 实时Bot通常追求快速成交
            submit_price = price * 1.001 
            submit_price = self.exchange.price_to_precision(self.symbol, submit_price)
            
            print(f"正在提交买单 (网格 {grid_id}): {qty} @ {submit_price}")
            
            order = self.exchange.create_order(
                symbol=self.symbol,
                type='limit',
                side='buy',
                amount=qty,
                price=submit_price
            )
            
            self.order_map[order['id']] = {
                'grid_id': grid_id,
                'amp': amp,
                'side': 'BUY',
                'qty': qty,
                'status': 'OPEN'
            }
            
            return True
            
        except Exception as e:
            print(f"买入失败: {e}")
            return False

    def start(self):
        self.init_exchange()
        print(f"机器人启动! 正在监听 {self.symbol}...")
        
        self.base_price = self.get_market_price()
        print(f"初始基准价格: {self.base_price}")
        
        # 初始化网格状态
        for g in self.strategy['grids']:
            grid_id = g.get('id', g['amplitude_pct'])
            self.grids_status[grid_id] = {'status': 'waiting', 'buy_price': 0}
            
        try:
            while True:
                # 1. 轮询价格
                current_price = self.get_market_price()
                
                # 2. 检查订单状态 (模拟 WebSocket 推送)
                self.check_order_status(current_price)
                
                # 3. 检查网格触发
                self.check_grids(current_price)
                
                # 4. 打印心跳
                if int(time.time()) % 10 == 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 现价: {current_price}")
                    
                time.sleep(2) # 2秒轮询一次，避免触发 Rate Limit
                
        except KeyboardInterrupt:
            print("机器人已停止。")
        except Exception as e:
            print(f"运行时错误: {e}")
        finally:
            self.cancel_all_orders()

    def cancel_all_orders(self):
        """取消所有挂单"""
        print("\n🧹 正在取消所有挂单...")
        try:
            self.exchange.cancel_all_orders(self.symbol)
            print("✅ 所有挂单已取消。")
        except Exception as e:
            print(f"取消挂单失败: {e}")
            
    def execute_stop_loss(self, order_id, info):
        """执行止损: 取消挂单 -> 市价卖出 -> 重置网格"""
        try:
            print(f"正在取消止盈挂单: {order_id}")
            self.exchange.cancel_order(order_id, self.symbol)
        except Exception as e:
            print(f"取消订单失败: {e}")
            
        try:
            qty = info['qty']
            print(f"正在执行市价止损卖出: {qty}")
            self.exchange.create_order(
                symbol=self.symbol,
                type='market',
                side='sell',
                amount=qty
            )
            print("✅ 市价止损单已提交")
            
            # 重置网格状态
            amp = info['amp']
            self.grids_status[amp] = {'status': 'waiting', 'buy_price': 0}
            print(f"网格 {amp}% 状态已重置为 waiting")
            
        except Exception as e:
            print(f"市价止损失败: {e}")

    def check_grids(self, current_price):
        with self.lock:
            if time.time() - self.last_trade_time < self.min_trade_interval:
                return
                
            # --- 移动基准价逻辑 (Trailing Base Price) ---
            # 如果当前价格高于基准价一定幅度，上移基准价，防止踏空
            # 阈值设为最小网格间距的一半，或者固定 0.5%
            # 这里取第一个网格的 trigger_drop 作为参考
            first_grid_drop = self.strategy['grids'][0]['trigger_drop']
            trailing_threshold = first_grid_drop # 例如 1%
            
            if current_price > self.base_price * (1 + trailing_threshold):
                old_base = self.base_price
                self.base_price = current_price
                print(f"📈 价格上涨跟随: 基准价 {old_base:.2f} -> {self.base_price:.2f}")

            for grid in self.strategy['grids']:
                amp = grid['amplitude_pct']
                weight = grid['weight']
                grid_id = grid.get('id', amp) # 兼容旧格式，新格式使用 id
                
                status = self.grids_status.get(grid_id, {'status': 'waiting'})
                
                if status['status'] == 'waiting':
                    target_buy_price = self.base_price * (1 - grid['trigger_drop'])
                    
                    if current_price <= target_buy_price:
                        print(f"📉 网格 {grid_id} 触发买入: 现价 {current_price} <= 目标 {target_buy_price:.4f}")
                        if self.execute_buy(current_price, weight, amp, grid_id):
                            # 暂时标记为 held 防止重复下单，等待订单成交回调确认
                            self.grids_status[grid_id] = {'status': 'pending_buy', 'buy_price': current_price}
                            self.last_trade_time = time.time()

if __name__ == "__main__":
    bot = BinanceBot()
    bot.start()
