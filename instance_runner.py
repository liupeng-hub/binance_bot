import argparse
import sys
import os
import json
import backtrader as bt
from datetime import datetime
import signal

# 设置路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'src'))

# Optimize DB connection for single instance process
os.environ['DB_POOL_SIZE'] = '1'
os.environ['DB_MAX_OVERFLOW'] = '5'

from src.utils.db_manager import db_manager
from src.utils.db_models import StrategyInstance, ExchangeConfig, User, BacktestResult
from src.utils.redis_client import redis_client
from src.engine_backtrader.bt_binance_store import BinanceStore
from src.engine_backtrader.bt_db_analyzer import SQLiteAnalyzer
from src.engine_backtrader.bt_redis_analyzer import RedisMarketFeed
from src.utils.strategy_loader import StrategyLoader

# 全局变量用于信号处理
instance_id_global = None

class RedisLogStream:
    def __init__(self, instance_id, original_stream):
        self.instance_id = instance_id
        self.original_stream = original_stream

    def write(self, message):
        self.original_stream.write(message)
        if message.strip():
            redis_client.publish_log(self.instance_id, message.strip())

    def flush(self):
        self.original_stream.flush()

def handle_exit(signum, frame):
    print(f"\nReceived signal {signum}, exiting...")
    if instance_id_global:
        session = db_manager.get_session()
        instance = session.query(StrategyInstance).filter_by(id=instance_id_global).first()
        if instance:
            instance.status = 'STOPPED'
            instance.pid = None
            session.commit()
            # Redis 推送
            redis_client.publish_status(instance_id_global, {'status': 'STOPPED', 'pid': None})
        session.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

def main():
    global instance_id_global
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance_id', required=True, help='Strategy Instance ID')
    args = parser.parse_args()
    instance_id_global = args.instance_id
    
    # 启用 Redis 日志推送
    sys.stdout = RedisLogStream(args.instance_id, sys.stdout)
    sys.stderr = RedisLogStream(args.instance_id, sys.stderr)
    
    # 获取实例配置
    session = db_manager.get_session()
    instance = session.query(StrategyInstance).filter_by(id=args.instance_id).first()
    
    if not instance:
        print(f"Instance {args.instance_id} not found")
        return

    user_id = instance.user_id
    symbol = instance.symbol
    strategy_name = instance.strategy_name
    mode = instance.mode if hasattr(instance, 'mode') else 'backtest'
    
    # 获取用户名
    user = session.query(User).filter_by(id=user_id).first()
    username = user.username if user else f"ID:{user_id}"
    
    # 解析 JSON 配置
    full_config = {}
    if instance.config_json:
        try:
            full_config = json.loads(instance.config_json)
        except Exception as e:
            print(f"Error parsing config_json: {e}")

    # 兼容新旧数据结构
    if 'params' in full_config:
        config = full_config['params']
        sys_config = full_config.get('sys', {})
    else:
        config = full_config
        sys_config = {}
        
    # 移除策略类不接受的冗余参数
    if 'symbol' in config:
        del config['symbol']
    if 'strategy_config' in config and strategy_name not in ['GridMartinStrategy']:
        # GridMartinStrategy 仍然需要 strategy_config
        # 其他策略如果不需要 strategy_config，可以尝试移除，但这里保守起见
        # 目前主要问题是 symbol
        del config['strategy_config']
        
    timeframe = sys_config.get('timeframe', '1m')
    days = sys_config.get('days', 30)
    capital = float(sys_config.get('capital', 1000000.0))
    
    # 环境标识
    testnet = sys_config.get('testnet', True)
    env_str = "🧪 测试网 (Futures Testnet)" if testnet else "💰 正式网 (REAL MONEY)"

    # 获取用户 API Key
    user_config = session.query(ExchangeConfig).filter_by(user_id=user_id).first()
    
    api_key = None
    secret_key = None
    
    if user_config:
        if testnet:
            # 优先使用 DB 中的 Testnet Key
            if user_config.testnet_api_key_enc:
                api_key = db_manager.decrypt_secret(user_config.testnet_api_key_enc)
                secret_key = db_manager.decrypt_secret(user_config.testnet_secret_key_enc)
            
            # Fallback to Env if DB is empty
            if not api_key:
                api_key = os.environ.get('BINANCE_TESTNET_API_KEY')
                secret_key = os.environ.get('BINANCE_TESTNET_SECRET_KEY')
        else:
            # 实盘模式使用 Real Key
            if user_config.api_key_enc:
                api_key = db_manager.decrypt_secret(user_config.api_key_enc)
                secret_key = db_manager.decrypt_secret(user_config.secret_key_enc)
                
            # Fallback to Env if DB is empty
            if not api_key:
                api_key = os.environ.get('BINANCE_API_KEY')
                secret_key = os.environ.get('BINANCE_SECRET_KEY')
    
    # 如果还是没有 Key (且是实盘或测试网需要鉴权)，则尝试从 Env 读取 (针对没有 user_config 的情况)
    if not api_key:
        if testnet:
             api_key = os.environ.get('BINANCE_TESTNET_API_KEY')
             secret_key = os.environ.get('BINANCE_TESTNET_SECRET_KEY')
        else:
             api_key = os.environ.get('BINANCE_API_KEY')
             secret_key = os.environ.get('BINANCE_SECRET_KEY')

    session.close() 

    # --- 调试信息打印 ---
    print("="*50)
    print(f"🛠️  [DEBUG] 实例启动调试信息:")
    print(f"   - 实例 ID: {args.instance_id}")
    print(f"   - 运行模式: {mode.upper()}")
    
    print(f"   - 运行环境: {env_str}")
    
    # API Key 脱敏打印
    if api_key:
        masked_key = f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) > 10 else "***"
        print(f"   - 使用 API Key: {masked_key}")
    else:
        print(f"   - 使用 API Key: ❌ 未配置 (将尝试读取 .env 或 运行在公共数据模式)")
    print("="*50)

    print(f"🚀 Starting Instance {args.instance_id}")
    print(f"   Mode: {mode.upper()}")
    print(f"   User: {username}")
    print(f"   Symbol: {symbol}")
    print(f"   Strategy: {strategy_name}")
    print(f"   Config: {config}")

    # 加载策略类
    loader = StrategyLoader(os.path.join(current_dir, 'src', 'strategies'))
    strategies = loader.load_strategies()
    
    if strategy_name not in strategies:
        print(f"❌ Strategy {strategy_name} not found in library")
        # Update status to ERROR
        session = db_manager.get_session()
        instance = session.query(StrategyInstance).filter_by(id=args.instance_id).first()
        if instance:
            instance.status = 'ERROR'
            session.commit()
            # Redis 推送
            redis_client.publish_status(args.instance_id, {'status': 'ERROR'})
        session.close()
        return
        
    strategy_cls = strategies[strategy_name]['cls']
    
    # 初始化 Cerebro
    cerebro = bt.Cerebro()
    
    # 从配置中获取测试网设置 (默认 True 确保安全)
    testnet = sys_config.get('testnet', True)
    
    # 初始化 Store
    store = BinanceStore(api_key=api_key, secret_key=secret_key, testnet=testnet)
    
    # --- Risk Manager Setup (Phase 3) ---
    from src.engine_backtrader.risk_manager import RiskManager
    from src.engine_backtrader.risk_proxy_broker import RiskProxyBroker
    
    # 简单的硬编码风控配置 (后续可移至 config_json)
    risk_config = {
        'max_order_value': 500000.0, # 稍微放宽以便测试
        'max_daily_drawdown': 0.10,
        'restricted_symbols': ['LUNA/USDT'] 
    }
    risk_manager = RiskManager(risk_config)
    
    # Wrap the broker
    real_broker = cerebro.broker
    # 如果是实盘，Store 会提供 broker，需要在那里拦截
    # 但在这里我们是在 cerebro 初始化后配置 broker
    # 注意: cerebro.broker 默认是一个 Simulation Broker
    
    # 配置初始资金 (Simulation)
    cerebro.broker.setcash(capital)
    cerebro.broker.setcommission(commission=0.001)
    
    # 将 Cerebro 的 broker 替换为 Proxy
    # 注意: 如果是 Live 模式，store.get_broker() 会返回 Live Broker，也需要 Wrap
    # 但 instance_runner 目前主要处理 Backtest/Sim 逻辑 (虽然代码里有 BinanceStore)
    # 让我们确保在 Live 模式下也生效
    
    # 如果 mode 是 live，我们需要从 store 获取 live broker
    # 但是 instance_runner.py 的逻辑目前似乎是混合的
    # 让我们查看 line 176 附近，原本是 cerebro.broker.setcash...
    
    # 统一 Wrap 逻辑:
    if mode == 'live' and api_key:
         # 实盘模式
         real_broker = store.get_broker()
         # 替换
         cerebro.broker = RiskProxyBroker(real_broker, risk_manager)
    else:
         # 模拟模式
         # 先设置好 sim broker 的参数
         cerebro.broker.setcash(capital)
         cerebro.broker.setcommission(commission=0.001)
         # 然后 Wrap
         cerebro.broker = RiskProxyBroker(cerebro.broker, risk_manager)
         
    print("✅ Risk Manager activated.")
    
    # 获取数据 (默认 30 天)
    # TODO: 从 instance config 中读取 days, timeframe
    print(f"   Timeframe: {timeframe} | Days: {days}")
    
    # --- Phase 1: 数据完整性校验与重试 ---
    max_retries = 3
    data = None
    is_live = (mode == 'live')
    
    for attempt in range(max_retries):
        try:
            # 对于实盘模式，必须启用 _realtime=True
            data = store.get_data(
                symbol=symbol, 
                days=days, 
                timeframe=timeframe, 
                _realtime=is_live,
                instance_id=args.instance_id # 传入 ID 用于实时推送
            )
            if len(data) > 0 or is_live: # 实盘模式下，即使初始数据为空也允许继续
                print(f"✅ Data loaded successfully (Attempt {attempt + 1})")
                break
            else:
                print(f"⚠️ Warning: Loaded empty data (Attempt {attempt + 1})")
        except Exception as e:
            print(f"⚠️ Data fetch failed (Attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2)
                
    if data is None:
        print("❌ Critical Error: Failed to load data after retries. Aborting.")
        # Update status to ERROR
        session = db_manager.get_session()
        instance = session.query(StrategyInstance).filter_by(id=args.instance_id).first()
        if instance:
            instance.status = 'ERROR'
            session.commit()
        session.close()
        return
    # ------------------------------------
    
    data._name = symbol # 显式设置名称，防止 TradeRecord 中 symbol 为空
    cerebro.adddata(data)
    
    # 添加策略
    cerebro.addstrategy(strategy_cls, **config)
    
    # 添加 DB Analyzer (传入 user_id 和 instance_id)
    cerebro.addanalyzer(SQLiteAnalyzer, _name='db', 
                        user_id=user_id, 
                        instance_id=args.instance_id,
                        mode=mode)
    
    # --- Realtime Market Feed (Redis) ---
    if mode == 'live':
        cerebro.addanalyzer(RedisMarketFeed, _name='redis_feed',
                            instance_id=args.instance_id,
                            symbol=symbol)
    # ------------------------------------

    # --- P0: 添加核心指标分析器 ---
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trade_analyzer')
    # ---------------------------
    
    # 模拟资金
    # cerebro.broker.setcash(capital)
    # cerebro.broker.setcommission(commission=0.001)

    # 运行
    try:
        # Phase 1: 增加对 Cerebro 运行时的全局捕获
        print("Starting Cerebro engine...")
        results = cerebro.run()
        print("Cerebro finished.")
        
        # 提取指标
        if not results:
            raise RuntimeError("Cerebro returned no results (empty run?)")
            
        strat = results[0]
        metrics = {}
        
        # 1. Drawdown
        dd = strat.analyzers.drawdown.get_analysis()
        if dd:
            metrics['max_drawdown'] = dd.get('max', {}).get('drawdown', 0.0)
            
        # 2. Trade Analyzer
        ta = strat.analyzers.trade_analyzer.get_analysis()
        if ta:
            total_trades = ta.get('total', {}).get('total', 0)
            metrics['total_trades'] = total_trades
            if total_trades > 0:
                won = ta.get('won', {}).get('total', 0)
                metrics['win_rate'] = won / total_trades
                metrics['pnl_net'] = ta.get('pnl', {}).get('net', {}).get('total', 0.0)
        
        print(f"Metrics: {metrics}")

        # 正常结束 (回测模式下)
        session = db_manager.get_session()
        instance = session.query(StrategyInstance).filter_by(id=args.instance_id).first()
        if instance:
            # 如果是实盘模式却异常结束了，标记为 STOPPED 而不是 COMPLETED
            if mode == 'live':
                instance.status = 'STOPPED'
                print("⚠️ Live instance finished unexpectedly.")
            else:
                instance.status = 'COMPLETED'
                
            instance.pid = None
            instance.metrics_json = json.dumps(metrics) # 保存指标
            
            # --- Phase 1: 自动归档到 BacktestResult 表 ---
            try:
                # 计算最终权益和收益率
                final_value = cerebro.broker.getvalue()
                net_profit = final_value - capital
                return_rate = (net_profit / capital) * 100.0
                
                # 提取参数
                params_str = json.dumps(config)
                
                # 创建记录
                result = BacktestResult(
                    user_id=user_id,
                    instance_id=args.instance_id,
                    strategy_name=strategy_name,
                    symbol=symbol,
                    mode=mode,
                    timeframe=timeframe,
                    start_time=data.datetime.datetime(0), # Start of data
                    end_time=datetime.utcnow(),
                    params_json=params_str,
                    initial_capital=capital,
                    final_value=final_value,
                    net_profit=net_profit,
                    return_rate=return_rate,
                    max_drawdown=metrics.get('max_drawdown', 0.0),
                    win_rate=metrics.get('win_rate', 0.0),
                    total_trades=metrics.get('total_trades', 0)
                )
                session.add(result)
                print(f"✅ Backtest result archived for {strategy_name}")
            except Exception as e:
                print(f"⚠️ Failed to archive backtest result: {e}")
            # ---------------------------------------------

            session.commit()
            
            # Redis 推送最终状态
            redis_client.publish_status(args.instance_id, {
                'status': instance.status, 
                'pid': None,
                'metrics': metrics
            })
        session.close()
        
    except Exception as e:
        import traceback
        print(f"Runtime Error: {e}")
        print("--- Traceback ---")
        traceback.print_exc()
        
        session = db_manager.get_session()
        instance = session.query(StrategyInstance).filter_by(id=args.instance_id).first()
        if instance:
            instance.status = 'ERROR'
            session.commit()
        session.close()

if __name__ == '__main__':
    main()
