import backtrader as bt
import json
import threading
import time
from .order_state_notifier import OrderStateNotifier

class LiveOrderNotifier(OrderStateNotifier):
    """
    实盘订单状态通知器

    实现：
    - 通过 WebSocket User Data Stream 接收订单状态
    - 解析 executionReport 事件
    - 更新 Backtrader Broker 订单状态
    """

    def __init__(self, exchange, broker):
        self.exchange = exchange
        self.broker = broker
        self.listen_key = None
        self.ws = None
        self.running = False
        self.thread = None

        # 定时刷新线程
        self.refresh_thread = None
        self.refresh_running = False

    def start(self):
        """启动 WebSocket 连接"""
        self.running = True
        self.listen_key = self._create_listen_key()

        # 启动 WebSocket 线程
        self.thread = threading.Thread(target=self._run_websocket, daemon=True)
        self.thread.start()

        # 启动 ListenKey 刷新线程
        self.refresh_running = True
        self.refresh_thread = threading.Thread(
            target=self._refresh_listen_key_loop,
            daemon=True
        )
        self.refresh_thread.start()

        print("✅ 实盘订单通知器已启动 (WebSocket User Data Stream)")

    def stop(self):
        """停止 WebSocket 连接"""
        self.running = False
        self.refresh_running = False

        if self.ws:
            self.ws.close()

        if self.listen_key:
            try:
                self._delete_listen_key()
            except Exception as e:
                print(f"删除 ListenKey 失败: {e}")

        print("🛑 实盘订单通知器已停止")

    def _create_listen_key(self):
        """创建 ListenKey"""
        # Binance Futures API
        try:
            if hasattr(self.exchange, 'fapiPrivatePostListenKey'):
                response = self.exchange.fapiPrivatePostListenKey()
            else:
                # Fallback
                response = self.exchange.publicPostUserDataStream()
            return response['listenKey']
        except Exception as e:
            print(f"Error creating listen key: {e}")
            raise e

    def _delete_listen_key(self):
        """删除 ListenKey"""
        try:
            if hasattr(self.exchange, 'fapiPrivateDeleteListenKey'):
                self.exchange.fapiPrivateDeleteListenKey(params={'listenKey': self.listen_key})
            else:
                self.exchange.publicDeleteUserDataStream(params={'listenKey': self.listen_key})
        except Exception as e:
            pass

    def _refresh_listen_key_loop(self):
        """定期刷新 ListenKey（每12小时）"""
        while self.refresh_running:
            time.sleep(1800)  # 30 mins (safe interval)
            try:
                if hasattr(self.exchange, 'fapiPrivatePutListenKey'):
                    self.exchange.fapiPrivatePutListenKey(params={'listenKey': self.listen_key})
                else:
                    self.exchange.publicPutUserDataStream(params={'listenKey': self.listen_key})
                # print("🔄 ListenKey 已刷新")
            except Exception as e:
                print(f"刷新 ListenKey 失败: {e}")

    def _run_websocket(self):
        """运行 WebSocket 连接"""
        import websocket
        import ssl

        # 确定 WebSocket URL
        if getattr(self.broker.store, 'testnet', False):
            base_url = "wss://stream.binancefuture.com/ws"
        else:
            base_url = "wss://fstream.binance.com/ws"

        url = f"{base_url}/{self.listen_key}"

        def on_message(ws, message):
            self._on_message(ws, message)

        def on_error(ws, error):
            self._on_error(ws, error)

        def on_close(ws, close_status_code, close_msg):
            self._on_close(ws, close_status_code, close_msg)

        def on_open(ws):
            self._on_open(ws)

        self.ws = websocket.WebSocketApp(
            url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )

        # 带重连机制
        reconnect_delay = 5
        while self.running:
            try:
                self.ws.run_forever(ping_interval=60, ping_timeout=10, sslopt={"cert_reqs": ssl.CERT_NONE})
            except Exception as e:
                print(f"WS 连接异常: {e}")
                
            if self.running:
                print(f"⏳ {reconnect_delay} 秒后重连...")
                time.sleep(reconnect_delay)
                # 重新创建 ListenKey
                try:
                    self.listen_key = self._create_listen_key()
                    # Update URL with new listen key
                    self.ws.url = f"{base_url}/{self.listen_key}"
                except:
                    pass

    def _on_message(self, ws, message):
        """接收 WebSocket 消息"""
        try:
            data = json.loads(message)
            event_type = data.get('e')

            if event_type == 'ORDER_TRADE_UPDATE':
                self._handle_execution_report(data)
            elif event_type == 'ACCOUNT_UPDATE':
                self._handle_account_update(data)

        except Exception as e:
            print(f"处理 WS 消息失败: {e}")

    def _on_open(self, ws):
        print("🔗 WebSocket 连接已建立")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"🔌 WebSocket 连接已关闭: {close_status_code}")

    def _on_error(self, ws, error):
        print(f"❌ WebSocket 错误: {error}")

    def _handle_execution_report(self, data):
        """处理订单执行报告"""
        order_data = data.get('o', {})
        binance_order_id = str(order_data.get('i'))
        execution_status = order_data.get('x') # Execution Type
        order_status = order_data.get('X') # Order Status

        # 映射状态到 Backtrader
        # NEW, PARTIALLY_FILLED, FILLED, CANCELED, REJECTED, EXPIRED
        status_map = {
            'NEW': bt.Order.Accepted,
            'PARTIALLY_FILLED': bt.Order.Partial,
            'FILLED': bt.Order.Completed,
            'CANCELED': bt.Order.Cancelled,
            'REJECTED': bt.Order.Rejected,
            'EXPIRED': bt.Order.Cancelled,
        }

        bt_status = status_map.get(order_status)
        if not bt_status:
            return

        # 查找对应的 Backtrader 订单
        # 注意：Broker 维护了 string 类型的 id
        bt_order = self.broker.get_order_by_binance_id(binance_order_id)
        if bt_order:
            filled_qty = float(order_data.get('l', 0)) # Last filled quantity
            filled_price = float(order_data.get('L', 0)) # Last filled price
            
            # 累计成交量 z
            # 平均价格 ap

            self.update_order_state(bt_order, bt_status, filled_qty, filled_price)

    def _handle_account_update(self, data):
        """处理账户更新"""
        # 更新余额、持仓等信息
        pass

    def update_order_state(self, bt_order, status, filled_qty=0, filled_price=0):
        """更新订单状态"""
        # 更新订单状态
        bt_order.status = status

        # 更新成交信息
        if filled_qty > 0:
            bt_order.executed.size += filled_qty
            bt_order.executed.price = filled_price
            bt_order.executed.value += filled_qty * filled_price

        # 触发 Backtrader 订单回调
        self.broker.notify(bt_order)
