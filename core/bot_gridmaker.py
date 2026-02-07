import os
import json
import time
import ccxt
import threading
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class LimitOrderBot:
    def __init__(self, config_path=None):
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_SECRET_KEY")
        
        if not self.api_key or not self.api_secret:
            raise ValueError("请在 .env 文件中配置 BINANCE_API_KEY 和 BINANCE_SECRET_KEY")

        # Init Exchange (Binance Futures)
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
        
        # Load Strategy
        if not config_path:
            strategies_dir = "strategies"
            if os.path.exists(strategies_dir):
                files = [os.path.join(strategies_dir, f) for f in os.listdir(strategies_dir) if f.endswith(".json")]
                if files:
                    config_path = max(files, key=os.path.getmtime)
        
        if not config_path:
            raise FileNotFoundError("未找到策略配置文件")
            
        self.load_config(config_path)
        
        self.order_map = {} 
        self.running = True
        self.max_order_age = 4 * 3600 
        self.base_price = None # 记录基准价格用于跟随
        
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
        try:
            self.exchange.set_leverage(self.leverage, self.symbol)
            print("杠杆设置成功。")
        except Exception as e:
            print(f"设置杠杆警告: {e}")

    def get_market_price(self):
        ticker = self.exchange.fetch_ticker(self.symbol)
        return float(ticker['last'])

    def get_account_balance(self):
        bal = self.exchange.fetch_balance()
        return float(bal['USDT']['free'])

    def check_trailing_update(self):
        """检查价格上涨，移动基准价并重置挂单"""
        current_price = self.get_market_price()
        if not self.base_price: return

        # 阈值: 最小网格间距的一半，或者固定 0.5%
        first_grid_drop = self.strategy['grids'][0].get('trigger_drop', self.strategy['grids'][0]['amplitude_pct']/100)
        trailing_threshold = first_grid_drop 
        
        if current_price > self.base_price * (1 + trailing_threshold):
            print(f"📈 价格上涨跟随: 基准价 {self.base_price:.2f} -> {current_price:.2f}")
            self.base_price = current_price
            
            # 撤销所有未成交买单
            self.cancel_all_buy_orders()
            
            # 重新挂单
            self.place_grid_orders(self.base_price)

    def cancel_all_buy_orders(self):
        """仅撤销买单"""
        print("正在撤销旧买单以跟随价格...")
        to_remove = []
        for order_id, info in list(self.order_map.items()):
            if info['side'] == 'BUY' and info.get('status') != 'FILLED':
                try:
                    self.exchange.cancel_order(order_id, self.symbol)
                    to_remove.append(order_id)
                except Exception as e:
                    print(f"撤单失败 {order_id}: {e}")
        
        for oid in to_remove:
            self.order_map.pop(oid, None)

    def place_grid_orders(self, base_price):
        """根据基准价批量挂单"""
        usdt_balance = self.get_account_balance()
        allocation_ratio = 0.1 
        allocation_base = usdt_balance * allocation_ratio * self.leverage
        
        print(f"\n--- 生成网格挂单 (基准价: {base_price:.2f}) ---")
        
        for grid in self.strategy['grids']:
            weight = grid['weight']
            amp = grid['amplitude_pct']
            grid_capital = allocation_base * weight
            
            # 兼容旧格式
            trigger_drop = grid.get('trigger_drop', amp / 100.0)
            buy_price = base_price * (1 - trigger_drop)
            
            if grid_capital < 6: continue
                
            qty = grid_capital / buy_price
            self.place_buy_order(buy_price, qty, amp, weight)

    def execute_strategy(self):
        """执行批量挂单 + 自动止盈监听"""
        self.init_exchange()
        print("\n=== 开始执行批量挂单逻辑 ===")
        
        # 1. 获取资金
        usdt_balance = self.get_account_balance()
        print(f"可用余额: {usdt_balance:.2f} USDT")
        
        if usdt_balance < 10:
            print("资金不足 (<10 USDT)，停止执行。")
            return

        self.base_price = self.get_market_price()
        print(f"初始基准价格: {self.base_price}")
        
        # 2. 批量挂单
        self.place_grid_orders(self.base_price)
            
        print("\n✅ 初始挂单完成，开始后台监听成交...")
        
        # 3. 监听循环
        try:
            while self.running:
                self.check_order_status()
                self.check_timeout_orders() 
                self.check_trailing_update() # 价格跟随
                time.sleep(2)
        except KeyboardInterrupt:
            print("停止监听。")
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

    def place_buy_order(self, price, qty, amp, weight=0):
        try:
            # 精度处理
            price = self.exchange.price_to_precision(self.symbol, price)
            qty = self.exchange.amount_to_precision(self.symbol, qty)
            
            print(f"提交挂单 (网格 {amp}%): {qty} @ {price}")
            
            order = self.exchange.create_order(
                symbol=self.symbol,
                type='limit',
                side='buy',
                amount=qty,
                price=price
            )
            
            self.order_map[order['id']] = {
                'amp': amp,
                'side': 'BUY',
                'qty': qty,
                'status': 'OPEN',
                'price': float(price),
                'created_at': time.time(),
                'weight': weight
            }
            
        except Exception as e:
            print(f"挂单失败: {e}")

    def check_timeout_orders(self):
        """检查并重置超时未成交的订单"""
        if not self.order_map: return
        
        current_time = time.time()
        to_reset = []
        
        for order_id, info in self.order_map.items():
            if info.get('status') == 'FILLED': continue
            if info['side'] != 'BUY': continue # 只重置买单
            
            created_at = info.get('created_at', 0)
            if current_time - created_at > self.max_order_age:
                to_reset.append((order_id, info))
                
        if not to_reset: return
        
        print(f"\n⏳ 发现 {len(to_reset)} 个超时订单，正在重置...")
        current_price = self.get_market_price()
        
        # 重新计算资金分配基数 (简化: 使用当前余额的 10% * leverage)
        # 注意: 撤单前余额是被冻结的，撤单后会释放。
        # 简单的做法是: 撤单 -> 查余额 -> 重新计算 -> 下单
        
        for order_id, info in to_reset:
            try:
                print(f"正在撤销超时订单: {order_id}")
                self.exchange.cancel_order(order_id, self.symbol)
                self.order_map.pop(order_id, None)
                
                # 重新下单
                weight = info.get('weight', 0)
                amp = info['amp']
                
                # 重新计算目标价
                # 假设 trigger_drop 就是 amp% (根据 strategies.json 的逻辑: trigger_drop = amp / 100)
                trigger_drop = amp / 100.0
                new_buy_price = current_price * (1 - trigger_drop)
                
                # 重新计算数量 (需要知道可用资金，但为了避免频繁查余额，可以估算或查一次)
                # 这里我们再次获取余额 (撤单后余额已释放)
                usdt_balance = self.get_account_balance()
                allocation_base = usdt_balance * 0.1 * self.leverage
                grid_capital = allocation_base * weight
                
                if grid_capital < 6:
                    print(f"资金不足，跳过重置网格 {amp}%")
                    continue
                    
                new_qty = grid_capital / new_buy_price
                
                print(f"🔄 重置网格 {amp}%: 新价格 {new_buy_price:.4f}")
                self.place_buy_order(new_buy_price, new_qty, amp, weight)
                
            except Exception as e:
                print(f"重置订单失败: {e}")

    def check_order_status(self):
        """轮询订单状态，处理成交 + 止损检查"""
        if not self.order_map:
            return

        try:
            # 获取当前价格用于止损检查
            current_price = self.get_market_price()
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
                    # 获取最新状态
                    order = self.exchange.fetch_order(order_id, self.symbol)
                    status = order['status']
                    
                    if status == 'closed': # FILLED
                        print(f"✅ 订单成交: {info['side']} {info['qty']} (ID: {order_id})")
                        self.handle_order_filled(order_id, info, order)
                        info['status'] = 'FILLED'
                        to_remove.append(order_id)
                        
                    elif status == 'canceled':
                        print(f"⚠️ 订单已取消: {order_id}")
                        to_remove.append(order_id)
                        
                except Exception as e:
                    pass # 网络波动忽略
            
            for oid in to_remove:
                self.order_map.pop(oid, None)
                
        except Exception as e:
            pass

    def handle_order_filled(self, order_id, info, order_data):
        amp = info['amp']
        side = info['side']
        qty = info['qty']
        avg_price = float(order_data.get('average', order_data.get('price')))
        
        if side == 'BUY':
            # 买单成交 -> 挂止盈
            target_sell_price = avg_price * (1 + amp / 100.0)
            stop_loss_price = avg_price * (1 - self.stop_loss_pct)
            print(f"🔄 自动挂止盈单 (网格 {amp}%): 目标价 {target_sell_price:.4f} | 止损价 {stop_loss_price:.4f}")
            self.place_limit_sell(target_sell_price, qty, amp, stop_loss_price)
            
        elif side == 'SELL':
            print(f"💰 网格 {amp}% 止盈完成! 获利 ~{amp}%")

    def place_limit_sell(self, price, qty, amp, stop_loss_price=None):
        try:
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
                'amp': amp,
                'side': 'SELL',
                'qty': qty,
                'status': 'OPEN',
                'stop_loss_price': stop_loss_price
            }
            print(f"挂单成功: 卖出 {qty} @ {price}")
            
        except Exception as e:
            print(f"自动挂卖单失败: {e}")

    def execute_stop_loss(self, order_id, info):
        """执行止损: 取消挂单 -> 市价卖出"""
        try:
            # 1. 取消原止盈挂单
            print(f"正在取消止盈挂单: {order_id}")
            self.exchange.cancel_order(order_id, self.symbol)
        except Exception as e:
            print(f"取消订单失败 (可能已成交): {e}")
            
        try:
            # 2. 市价卖出
            qty = info['qty']
            print(f"正在执行市价止损卖出: {qty}")
            self.exchange.create_order(
                symbol=self.symbol,
                type='market',
                side='sell',
                amount=qty
            )
            print("✅ 市价止损单已提交")
        except Exception as e:
            print(f"市价止损失败: {e}")

if __name__ == "__main__":
    try:
        bot = LimitOrderBot()
        bot.execute_strategy()
    except Exception as e:
        print(f"Bot Error: {e}")
