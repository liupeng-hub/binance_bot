import click
import sys
import os
import json
import backtrader as bt
from dotenv import load_dotenv

# 添加 src 到路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# 导入内部模块 (注意：需要先修复 import 路径后才能正常工作)
# 暂时使用占位符，后续步骤会修复所有 import
# from engine_backtrader.bt_binance_store import BinanceStore
# from strategies.bt_strategy_martingale import GridStrategy

@click.group()
def cli():
    """Binance Bot CLI - 专业量化交易系统"""
    load_dotenv()

@click.command()
@click.option('--strategy', required=True, help='选择策略 (使用 list 命令查看可用策略)')
@click.option('--symbol', default='BTC/USDT', help='交易标的 (例如 BTC/USDT)')
@click.option('--mode', default='sim', type=click.Choice(['sim', 'live']), help='运行模式: sim(模拟) 或 live(实盘)')
@click.option('--days', default=30, help='回测/初始化加载的历史天数')
@click.option('--timeframe', default='1h', type=click.Choice(['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d']), help='K线周期')
@click.option('--params', default='{}', help='策略参数 (JSON 字符串)')
@click.option('--no-ws', is_flag=True, help='禁用 WebSocket (使用 HTTP 轮询)')
def trade(strategy, symbol, mode, days, timeframe, params, no_ws):
    """运行交易机器人 (实盘或模拟)"""
    from src.engine_backtrader.bt_binance_store import BinanceStore
    from src.utils.strategy_loader import StrategyLoader
    from src.utils.log_utils import format_log
    
    # 加载策略
    loader = StrategyLoader(os.path.join(os.path.dirname(__file__), 'src', 'strategies'))
    strategies = loader.load_strategies()
    
    if strategy not in strategies:
        click.secho(f"❌ 错误: 未找到策略 '{strategy}'", fg='red')
        click.echo("可用策略:")
        for name in strategies.keys():
            click.echo(f"  - {name} ({strategies[name].get('display_name', name)})")
        return

    strat_info = strategies[strategy]
    strat_cls = strat_info['cls']
    
    click.echo(f"🚀 启动交易引擎 | 策略: {strat_info.get('display_name', strategy)} | 模式: {mode} | 标的: {symbol}")
    
    cerebro = bt.Cerebro()
    
    # 解析自定义参数
    try:
        strategy_params = json.loads(params)
    except json.JSONDecodeError:
        click.secho("❌ 参数格式错误: 请提供有效的 JSON 字符串", fg='red')
        return

    # 合并默认参数与用户参数以进行显示
    effective_params = strat_info.get('params', {}).copy()
    effective_params.update(strategy_params)
    
    click.echo(f"   🛠️  策略参数: {json.dumps(effective_params, indent=2)}")

    # 初始化 Store
    store = BinanceStore(env_file='.env', testnet=(mode=='sim'))
    
    if mode == 'live':
        click.secho("⚠️  警告: 正在以【实盘模式】运行，使用【真实资金】交易！", fg='red', bold=True)
        cerebro.broker = store.get_broker()
    else:
        click.echo("ℹ️  正在以【模拟模式】运行。")
        cerebro.broker.setcash(100000.0)
        cerebro.broker.setcommission(commission=0.001)

    # 添加数据
    use_websocket = not no_ws
    # 转换 timeframe 字符串为 Backtrader 常量
    tf_map = {
        '1m': bt.TimeFrame.Minutes, '3m': bt.TimeFrame.Minutes, '5m': bt.TimeFrame.Minutes, 
        '15m': bt.TimeFrame.Minutes, '30m': bt.TimeFrame.Minutes,
        '1h': bt.TimeFrame.Minutes, '2h': bt.TimeFrame.Minutes, '4h': bt.TimeFrame.Minutes, 
        '6h': bt.TimeFrame.Minutes, '8h': bt.TimeFrame.Minutes, '12h': bt.TimeFrame.Minutes,
        '1d': bt.TimeFrame.Days
    }
    # 对于分钟级数据，compression 需要相应调整 (例如 1h = 60m)
    # 简化起见，这里先统一传给 Store 处理，或者假设 Store 返回标准 BT Data
    # 注意：BinanceStore.get_data 目前可能需要 timeframe 字符串
    
    data = store.get_data(symbol=symbol, days=days, timeframe=timeframe, use_websocket=use_websocket)
    cerebro.adddata(data, name=symbol)
        
    # 添加策略
    cerebro.addstrategy(strat_cls, **strategy_params)

    # 运行
    cerebro.run()

@cli.command()
def list_strategies():
    """列出所有可用策略"""
    from src.utils.strategy_loader import StrategyLoader
    
    loader = StrategyLoader(os.path.join(os.path.dirname(__file__), 'src', 'strategies'))
    strategies = loader.load_strategies()
    
    click.echo(f"发现 {len(strategies)} 个策略:")
    for name, info in strategies.items():
        click.secho(f"\n📌 {info.get('display_name', name)} ({name})", fg='green', bold=True)
        click.echo(f"   {info.get('doc', '').strip().splitlines()[0]}") # 第一行文档
        
        params = info.get('params', {})
        if params:
            click.echo("   ⚙️  默认参数:")
            for k, v in params.items():
                click.echo(f"      - {k}: {v}")
            
            # 生成 CLI 示例
            example_json = json.dumps(params).replace('"', '\\"') # 简单转义用于 CLI 显示
            click.echo(f"   📋 CLI 示例: --params '{json.dumps(params)}'")

@cli.command()
@click.option('--symbol', default='BTC/USDT', help='目标标的')
@click.option('--days', default=180, help='分析历史天数')
def gen(symbol, days):
    """生成策略配置 (基于历史数据分析)"""
    from src.generators.run_strategy_gen import run_analysis
    
    click.echo(f"📊 开始分析数据并生成配置 | 标的: {symbol} | 历史: {days}天")
    run_analysis(symbol=symbol, days=days)
    click.echo("✅ 配置生成完成，已保存至 config/strategies/")

if __name__ == '__main__':
    cli()
