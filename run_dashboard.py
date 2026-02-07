
import os
import time
import ccxt
from datetime import datetime
from tabulate import tabulate
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")

def show_dashboard():
    if not API_KEY or not API_SECRET:
        print("❌ 未配置 BINANCE_API_KEY 或 BINANCE_SECRET_KEY")
        return

    exchange = ccxt.binanceusdm({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'proxies': {
            'http': 'http://127.0.0.1:1087',
            'https': 'http://127.0.0.1:1087',
        },
        'options': {
            'defaultType': 'future'
        }
    })
    
    print("\n" + "="*50)
    print(f"Binance Futures 看板 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)

    # 1. 账户资金 (Account Balance)
    try:
        balance = exchange.fetch_balance()
        usdt_free = balance['USDT']['free']
        usdt_total = balance['USDT']['total']
        
        # 简单显示 USDT
        asset_data = [["USDT", f"{usdt_total:.2f}", f"{usdt_free:.2f}"]]
        
        print("\n💰 账户资金:")
        print(tabulate(asset_data, headers=["币种", "总权益", "可用余额"], tablefmt="simple"))
        
    except Exception as e:
        print(f"获取资金失败: {e}")

    # 2. 当前持仓 (Positions)
    try:
        positions = exchange.fetch_positions()
        pos_data = []
        for pos in positions:
            if float(pos['contracts']) > 0:
                symbol = pos['symbol']
                side = pos['side'].upper() # long/short
                qty = float(pos['contracts'])
                entry_price = float(pos['entryPrice'])
                unrealized_pnl = float(pos['unrealizedPnl'])
                leverage = pos['leverage']
                
                pos_data.append([
                    symbol,
                    side,
                    f"{leverage}x",
                    qty,
                    f"{entry_price:.4f}",
                    f"{unrealized_pnl:.2f}"
                ])
                
        if pos_data:
            print("\n📦 当前持仓:")
            print(tabulate(pos_data, headers=["合约", "方向", "杠杆", "数量", "开仓价", "未结盈亏"], tablefmt="simple"))
        else:
            print("\n📦 当前持仓: 空仓")
            
    except Exception as e:
        print(f"获取持仓失败: {e}")

    # 3. 当前挂单 (Open Orders)
    try:
        # 获取所有 Open Orders 需要遍历 symbol 或者 fetch_open_orders() 如果支持不传 symbol
        # Binance Futures fetch_open_orders 通常需要 symbol。
        # 为了简单，我们只获取 BTCUSDT 和 ETHUSDT，或者不做全局查询
        # 这里尝试获取 BTC/USDT:USDT (ccxt 符号)
        
        # 暂时只查 BTCUSDT
        symbol = "BTC/USDT:USDT"
        orders = exchange.fetch_open_orders(symbol)
        
        order_data = []
        if orders:
            for order in orders[:10]:
                order_data.append([
                    order['symbol'],
                    order['side'].upper(),
                    f"{order['price']} / {order['amount']}",
                    f"{order['filled']}",
                    order['status'],
                    datetime.fromtimestamp(order['timestamp']/1000).strftime('%H:%M:%S')
                ])
            print(f"\n📝 {symbol} 当前挂单 (Top 10):")
            print(tabulate(order_data, headers=["合约", "方向", "价格/数量", "已成", "状态", "时间"], tablefmt="simple"))
        else:
            print(f"\n📝 {symbol} 当前挂单: 无")
            
    except Exception as e:
        print(f"获取挂单失败: {e}")
        
    print("\n" + "="*50)

def loop_dashboard(interval=10):
    """
    循环运行看板
    interval: 刷新间隔 (秒)
    """
    while True:
        try:
            # 清屏 (兼容 Mac/Linux 和 Windows)
            os.system('cls' if os.name == 'nt' else 'clear')
            show_dashboard()
            print(f"\n[自动刷新中] 下次更新在 {interval} 秒后... (按 Ctrl+C 停止)")
            time.sleep(interval)
            
        except KeyboardInterrupt:
            print("\n看板已停止。")
            break
        except Exception as e:
            print(f"\n⚠️ 刷新出错: {e}")
            time.sleep(5)

if __name__ == "__main__":
    loop_dashboard(10)
