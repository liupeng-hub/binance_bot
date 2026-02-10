
import random
import asyncio
from nicegui import ui
import datetime
import pandas as pd
import numpy as np

# --- 1. 后端模拟数据源 (Backend Data Simulator) ---
class TradingDataFeed:
    def __init__(self, symbol="BTC/USDT"):
        self.symbol = symbol
        self.price = 50000.0
        self.history = []
        self.listeners = []
        self.is_running = False
        
        # 初始化一些历史数据 (100根)
        current_time = datetime.datetime.now() - datetime.timedelta(minutes=100)
        for _ in range(100):
            change = random.uniform(-50, 50)
            self.price += change
            high = self.price + random.uniform(0, 20)
            low = self.price - random.uniform(0, 20)
            vol = random.uniform(1, 10)
            
            candle = {
                "time": int(current_time.timestamp() * 1000), # Highcharts 需要毫秒时间戳
                "open": self.price - change,
                "high": high,
                "low": low,
                "close": self.price,
                "volume": vol
            }
            self.history.append(candle)
            current_time += datetime.timedelta(minutes=1)

    def subscribe(self, callback):
        self.listeners.append(callback)

    async def start(self):
        self.is_running = True
        while self.is_running:
            # 模拟新的一根 K 线 (或者更新最后一根)
            # 这里简单起见，每 0.5秒生成一根新 K 线
            change = random.uniform(-30, 30)
            self.price += change
            high = self.price + random.uniform(0, 10)
            low = self.price - random.uniform(0, 10)
            vol = random.uniform(1, 5)
            
            # 使用当前时间
            now = datetime.datetime.now()
            candle = {
                "time": int(now.timestamp() * 1000),
                "open": self.price - change,
                "high": high,
                "low": low,
                "close": self.price,
                "volume": vol
            }
            
            # 维护历史 (用于计算指标)
            self.history.append(candle)
            if len(self.history) > 200:
                self.history.pop(0)
            
            # 计算指标 (Backend Calculation)
            # 1. SMA (Simple Moving Average)
            df = pd.DataFrame(self.history)
            sma_val = df['close'].rolling(window=10).mean().iloc[-1]
            
            # 2. MACD
            exp1 = df['close'].ewm(span=12, adjust=False).mean()
            exp2 = df['close'].ewm(span=26, adjust=False).mean()
            macd = exp1 - exp2
            signal = macd.ewm(span=9, adjust=False).mean()
            hist = macd - signal
            
            indicators = {
                "sma": round(sma_val, 2) if not pd.isna(sma_val) else None,
                "macd": round(macd.iloc[-1], 2),
                "macd_signal": round(signal.iloc[-1], 2),
                "macd_hist": round(hist.iloc[-1], 2)
            }
            
            # 推送数据包
            data_packet = {
                "candle": candle,
                "indicators": indicators
            }
            
            for callback in self.listeners:
                callback(data_packet)
            
            await asyncio.sleep(0.5)

# --- 2. 前端页面 (NiceGUI) ---
@ui.page('/')
async def trading_dashboard():
    feed = TradingDataFeed()
    
    # 页面样式
    ui.colors(primary='#5898d4', secondary='#26a69a', accent='#ef5350')
    
    with ui.header().classes('bg-gray-900 text-white'):
        ui.label('📈 Pro Trading Dashboard (NiceGUI + Highcharts Stock)').classes('text-xl font-bold')
        ui.label('Native WebSocket Push | Backend Indicator Calc').classes('text-xs text-gray-400 ml-4')

    # 主布局
    with ui.row().classes('w-full h-screen p-4 gap-4'):
        
        # 图表容器
        with ui.card().classes('w-full h-[600px] p-0 gap-0'):
            
            # Highcharts Stock 配置
            # 我们配置两个 yAxis: 
            # 0: 主图 (K线 + SMA)
            # 1: 副图 (MACD)
            chart = ui.highchart({
                'chart': {'backgroundColor': '#1e1e1e', 'marginRight': 50},
                'rangeSelector': {'enabled': False},
                'scrollbar': {'enabled': False},
                'navigator': {'enabled': False}, # 简化显示
                'title': {'text': 'BTC/USDT Real-time', 'style': {'color': '#fff'}},
                
                'xAxis': {
                    'type': 'datetime',
                    'gridLineWidth': 0.5,
                    'gridLineColor': '#333',
                    'labels': {'style': {'color': '#aaa'}}
                },
                
                'yAxis': [{
                    'labels': {'align': 'right', 'x': -3, 'style': {'color': '#aaa'}},
                    'title': {'text': 'Price'},
                    'height': '70%', # 主图占 70% 高度
                    'lineWidth': 1,
                    'gridLineColor': '#333'
                }, {
                    'labels': {'align': 'right', 'x': -3, 'style': {'color': '#aaa'}},
                    'title': {'text': 'MACD'},
                    'top': '75%',   # 副图从 75% 处开始
                    'height': '25%', # 副图占 25% 高度
                    'offset': 0,
                    'lineWidth': 1,
                    'gridLineColor': '#333'
                }],
                
                'plotOptions': {
                    'candlestick': {
                        'color': '#ef5350',       # 下跌红
                        'upColor': '#26a69a',     # 上涨绿
                        'lineColor': '#ef5350',
                        'upLineColor': '#26a69a'
                    },
                    'line': {'marker': {'enabled': False}}
                },
                
                'series': [
                    # Series 0: Candlestick
                    {
                        'type': 'candlestick',
                        'name': 'BTC/USDT',
                        'data': [],
                        'yAxis': 0
                    },
                    # Series 1: SMA (Overlay)
                    {
                        'type': 'line',
                        'name': 'SMA 10',
                        'data': [],
                        'color': '#ffd700', # Gold
                        'lineWidth': 2,
                        'yAxis': 0
                    },
                    # Series 2: MACD Diff (Line)
                    {
                        'type': 'line',
                        'name': 'MACD',
                        'data': [],
                        'color': '#00bfff',
                        'lineWidth': 1,
                        'yAxis': 1
                    },
                    # Series 3: MACD Signal (Line)
                    {
                        'type': 'line',
                        'name': 'Signal',
                        'data': [],
                        'color': '#ff8c00',
                        'lineWidth': 1,
                        'yAxis': 1
                    },
                    # Series 4: MACD Hist (Column)
                    {
                        'type': 'column',
                        'name': 'Histogram',
                        'data': [],
                        'color': '#aaaaaa',
                        'yAxis': 1
                    }
                ]
            }, extras=['stock']).classes('w-full h-full')

    # 3. 初始化历史数据
    def init_chart():
        # 将历史数据格式化为 Highcharts 格式
        ohlc = [[x['time'], x['open'], x['high'], x['low'], x['close']] for x in feed.history]
        
        # 计算历史指标 (简单起见，这里先推空或者模拟)
        # 实际应在后端算好一次性推过去
        # 这里只做演示，初始化为空，等待实时推送填满
        chart.options['series'][0]['data'] = ohlc
        chart.update()

    init_chart()

    # 4. 实时更新回调
    def on_update(packet):
        c = packet['candle']
        ind = packet['indicators']
        
        # 更新 K 线 (Series 0)
        # add_point(point, redraw, shift)
        # shift=True 表示保持窗口大小 (移除旧数据)
        chart.options['series'][0]['data'].append([c['time'], c['open'], c['high'], c['low'], c['close']])
        if len(chart.options['series'][0]['data']) > 100:
            chart.options['series'][0]['data'].pop(0)
            
        # 更新 SMA (Series 1)
        if ind['sma']:
            chart.options['series'][1]['data'].append([c['time'], ind['sma']])
            if len(chart.options['series'][1]['data']) > 100:
                chart.options['series'][1]['data'].pop(0)

        # 更新 MACD (Series 2, 3, 4)
        chart.options['series'][2]['data'].append([c['time'], ind['macd']])
        chart.options['series'][3]['data'].append([c['time'], ind['macd_signal']])
        
        # Histogram color based on value
        hist_color = '#26a69a' if ind['macd_hist'] >= 0 else '#ef5350'
        chart.options['series'][4]['data'].append({
            'x': c['time'], 
            'y': ind['macd_hist'], 
            'color': hist_color
        })
        
        # Cleanup Subplots
        for i in [2, 3, 4]:
            if len(chart.options['series'][i]['data']) > 100:
                chart.options['series'][i]['data'].pop(0)
        
        chart.update()

    feed.subscribe(on_update)
    
    # 自动启动
    if not feed.is_running:
        asyncio.create_task(feed.start())

ui.run(port=8080, title='NiceGUI Trading Station', dark=True)
