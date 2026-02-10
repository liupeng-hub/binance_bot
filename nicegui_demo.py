
import random
import asyncio
from nicegui import ui
import datetime

# --- 模拟数据源 (Simulated Data Feed) ---
# 实际项目中，这里会替换为 Redis 订阅或 WebSocket 客户端
class MarketDataFeed:
    def __init__(self, symbol="BTC/USDT"):
        self.symbol = symbol
        self.price = 50000.0
        self.listeners = []
        self.is_running = False

    def subscribe(self, callback):
        self.listeners.append(callback)

    async def start(self):
        self.is_running = True
        while self.is_running:
            # 模拟随机价格波动
            change = random.uniform(-10, 10)
            self.price += change
            
            # 构建一个简单的 Tick 数据
            tick = {
                "time": datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "price": round(self.price, 2),
                "symbol": self.symbol
            }
            
            # 推送给所有订阅者
            for callback in self.listeners:
                callback(tick)
            
            # 模拟高频更新 (每 100ms 更新一次)
            await asyncio.sleep(0.1)

# --- 前端 UI (NiceGUI) ---
@ui.page('/')
async def main_page():
    # 初始化数据源
    feed = MarketDataFeed()
    
    # 1. 页面布局
    with ui.header().classes('bg-slate-900 text-white'):
        ui.label('🚀 NiceGUI Realtime Crypto Dashboard').classes('text-xl font-bold')
        
    with ui.row().classes('w-full items-stretch'):
        # 左侧：控制面板
        with ui.card().classes('w-1/4'):
            ui.markdown('### Control Panel')
            ui.label(f'Symbol: {feed.symbol}')
            
            # 状态指示器
            status_label = ui.label('Status: Stopped').classes('text-red-500 font-bold')
            
            async def start_feed():
                if not feed.is_running:
                    status_label.text = 'Status: Running (Streaming...)'
                    status_label.classes(replace='text-green-500')
                    # 启动后台任务
                    asyncio.create_task(feed.start())
            
            ui.button('Start Data Stream', on_click=start_feed)

        # 右侧：实时图表 (使用 Highcharts)
        with ui.card().classes('w-3/4 h-96'):
            ui.markdown('### Realtime Price (Tick)')
            
            # Highcharts 配置
            # 注意：这里我们开启了 boost 模块以支持高性能渲染
            chart = ui.highchart({
                'title': False,
                'chart': {'type': 'line', 'animation': False}, # 关闭动画以提高性能
                'xAxis': {'type': 'category'},
                'yAxis': {'title': {'text': 'Price (USDT)'}},
                'series': [{
                    'name': 'BTC/USDT',
                    'data': [] 
                }],
                'plotOptions': {
                    'series': {
                        'marker': {'enabled': False} # 隐藏数据点标记，提升流畅度
                    }
                }
            }).classes('w-full h-full')

    # 2. 定义数据接收回调
    def on_tick(tick):
        # 核心：直接调用 Highcharts 的 API 添加数据点
        # add_point(point, redraw=True, shift=True/False)
        # shift=True 表示数据超过一定数量后，移除最早的一个，保持窗口移动
        
        # 我们需要在 UI 线程中执行更新
        # NiceGUI 会自动处理 websocket 通信
        chart.options['series'][0]['data'].append([tick['time'], tick['price']])
        
        # 保持图表中只显示最近 100 个点
        if len(chart.options['series'][0]['data']) > 100:
             chart.options['series'][0]['data'].pop(0)
             
        chart.update() # 推送更新到前端

    # 订阅数据
    feed.subscribe(on_tick)

# 启动应用
# 注意：在 Trae 终端中运行此文件，它会启动一个 Web 服务器
# 您可以通过 http://localhost:8080 访问
ui.run(port=8080, title='Crypto Stream')
