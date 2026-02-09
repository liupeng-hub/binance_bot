import argparse
import sys
import os
import json
import backtrader as bt
from datetime import datetime
import itertools
import multiprocessing
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

# 设置路径
current_dir = os.path.dirname(os.path.abspath(__file__))
# current_dir: .../src/engine_backtrader
# parent: .../src
project_root = os.path.dirname(os.path.dirname(current_dir))
# project_root: .../binance_bot

# 将项目根目录加入 path，以便可以使用 from src.utils import ...
sys.path.append(project_root)

from src.utils.db_manager import db_manager
from src.utils.db_models import OptimizationJob, User, ExchangeConfig
from src.engine_backtrader.bt_binance_store import BinanceStore
from src.utils.strategy_loader import StrategyLoader

def run_grid_search(cerebro, strategy_cls, params_config, capital):
    """
    执行网格搜索优化
    """
    # 5. 生成参数范围
    opt_params = {}
    total_combinations = 1
    
    for p_name, p_range in params_config.items():
        # 兼容旧格式 (默认 int)
        p_type = p_range.get('type', 'int')
        
        if p_type == 'int':
            start = int(p_range.get('start', 0))
            end = int(p_range.get('end', 0))
            step = int(p_range.get('step', 1))
            
            values = []
            curr = start
            while curr <= end:
                values.append(curr)
                curr += step
                
        elif p_type == 'float':
            start = float(p_range.get('start', 0.0))
            end = float(p_range.get('end', 0.0))
            step = float(p_range.get('step', 0.01))
            
            # 使用 np.arange 并处理浮点精度
            epsilon = step / 10000.0
            values = np.arange(start, end + epsilon, step).tolist()
            # 再次确保精度 (round)
            values = [round(x, 6) for x in values]
        
        if not values:
            values = [start]
            
        opt_params[p_name] = values
        total_combinations *= len(values)
        
    print(f"   [Grid] Total Combinations: {total_combinations}")
    
    if total_combinations > 1000:
            print("⚠️ Warning: Large parameter space. This might take a while.")
    
    # 添加优化策略
    cerebro.optstrategy(strategy_cls, **opt_params)
    
    # 运行
    print("   Running Grid Search...")
    results = cerebro.run(maxcpus=multiprocessing.cpu_count())
    
    # 处理结果
    final_results = []
    
    for run_instances in results:
        strat = run_instances[0]
        
        run_params = {}
        for p_name in opt_params.keys():
            run_params[p_name] = getattr(strat.p, p_name)
        
        metrics = extract_metrics(strat, capital)
        
        final_results.append({
            'params': run_params,
            'metrics': metrics
        })
        
    return final_results

def run_optuna_search(strategy_cls, params_config, data_feed, capital, n_trials=50):
    """
    执行贝叶斯优化 (Optuna)
    """
    print(f"   [Optuna] Starting optimization with {n_trials} trials...")
    
    def objective(trial):
        # 1. 为本次试验采样参数
        trial_params = {}
        for p_name, p_range in params_config.items():
            p_type = p_range.get('type', 'int')
            start = p_range.get('start')
            end = p_range.get('end')
            
            if p_type == 'int':
                trial_params[p_name] = trial.suggest_int(p_name, int(start), int(end))
            elif p_type == 'float':
                # step 对于 suggest_float 是可选的
                step = p_range.get('step', None)
                trial_params[p_name] = trial.suggest_float(p_name, float(start), float(end), step=step)

        # 2. 运行回测
        cerebro = bt.Cerebro()
        cerebro.adddata(data_feed)
        cerebro.addstrategy(strategy_cls, **trial_params)
        
        cerebro.broker.setcash(capital)
        cerebro.broker.setcommission(commission=0.001)
        
        # 只运行一次
        strats = cerebro.run()
        strat = strats[0]
        
        # 3. 返回优化目标 (例如: 净利润)
        final_value = strat.broker.get_value()
        pnl = final_value - capital
        
        # 记录其他指标作为 custom attribute
        # Optuna 不直接支持多目标返回 (除非使用 multi-objective study)，
        # 这里我们把 metrics 存入 trial.user_attrs
        # 但在 objective 函数内部很难直接传出复杂对象
        # 我们可以只返回 PnL 作为目标
        
        return pnl

    # 创建 Study
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=n_trials)
    
    print("   [Optuna] Optimization finished.")
    
    # 提取结果
    final_results = []
    
    # 重新回测 Top N 的参数以获取完整指标? 
    # 或者我们信任 Optuna 的 trial.user_attrs (如果我们在 objective 里 set 了)
    # 为了简单，我们只从 study.trials 中提取参数和目标值(value)
    # 但我们需要完整的 metrics (如 drawdown)，所以在 objective 里最好还是重跑一下或者 hack 一下
    
    # 简单做法：只返回 params 和 net_profit，其他 metrics 设为 null 或估算
    # 更好的做法：遍历 trials，拿出 params，再次快速回测一遍? (有点慢)
    # 折衷：在 objective 里计算所有 metrics 并 set_user_attr
    
    # 让我们修改一下 objective，把 metrics 存起来
    # 但由于 scope 问题，我们得重写 objective
    
    # 重写带 user_attrs 的 objective
    def objective_with_attrs(trial):
        trial_params = {}
        for p_name, p_range in params_config.items():
            p_type = p_range.get('type', 'int')
            start = p_range.get('start')
            end = p_range.get('end')
            if p_type == 'int':
                trial_params[p_name] = trial.suggest_int(p_name, int(start), int(end))
            elif p_type == 'float':
                step = p_range.get('step', None)
                trial_params[p_name] = trial.suggest_float(p_name, float(start), float(end), step=step)

        cerebro = bt.Cerebro()
        cerebro.adddata(data_feed)
        cerebro.addstrategy(strategy_cls, **trial_params)
        
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trade_analyzer')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        
        cerebro.broker.setcash(capital)
        cerebro.broker.setcommission(commission=0.001)
        
        strats = cerebro.run()
        strat = strats[0]
        
        metrics = extract_metrics(strat, capital)
        
        # 存入 user_attrs
        for k, v in metrics.items():
            trial.set_user_attr(k, v)
            
        return metrics['net_profit']

    # 重新运行 study (覆盖之前的)
    study = optuna.create_study(direction='maximize')
    study.optimize(objective_with_attrs, n_trials=n_trials)

    for trial in study.trials:
        if trial.state != optuna.trial.TrialState.COMPLETE:
            continue
            
        final_results.append({
            'params': trial.params,
            'metrics': trial.user_attrs
        })
        
    return final_results

def extract_metrics(strat, capital):
    metrics = {}
    final_value = strat.broker.get_value()
    pnl = final_value - capital
    metrics['net_profit'] = pnl
    metrics['return_rate'] = (pnl / capital) * 100.0
    
    ta = strat.analyzers.trade_analyzer.get_analysis()
    total_trades = ta.get('total', {}).get('total', 0)
    metrics['total_trades'] = total_trades
    if total_trades > 0:
        metrics['win_rate'] = ta.get('won', {}).get('total', 0) / total_trades
    else:
        metrics['win_rate'] = 0.0
        
    dd = strat.analyzers.drawdown.get_analysis()
    metrics['max_drawdown'] = dd.get('max', {}).get('drawdown', 0.0)
    
    return metrics

def run_optimization_job(job_id):
    # ... (前部分不变)
    print(f"🚀 Starting Optimization Job: {job_id}")
    
    session = db_manager.get_session()
    job = session.query(OptimizationJob).filter_by(id=job_id).first()
    
    if not job:
        print(f"❌ Job {job_id} not found")
        return

    try:
        job.status = 'RUNNING'
        job.pid = os.getpid()
        session.commit()
        
        strategy_name = job.strategy_name
        symbol = job.symbol
        params_config = json.loads(job.params_config)
        sys_config = json.loads(job.sys_config)
        
        timeframe = sys_config.get('timeframe', '1h')
        days = sys_config.get('days', 30)
        capital = float(sys_config.get('capital', 100000.0))
        algorithm = sys_config.get('algorithm', 'grid') # 获取算法类型
        
        print(f"   Strategy: {strategy_name}")
        print(f"   Algorithm: {algorithm}")
        
        # 加载策略
        loader = StrategyLoader(os.path.join(project_root, 'src', 'strategies'))
        strategies = loader.load_strategies()
        strategy_cls = strategies[strategy_name]['cls']
        
        # 准备数据 (Optuna 需要复用 data feed)
        store = BinanceStore(testnet=True)
        data = store.get_data(symbol=symbol, days=days, timeframe=timeframe, use_websocket=False)
        
        final_results = []
        
        if algorithm == 'grid':
            # Grid Search 需要 Cerebro 实例
            cerebro = bt.Cerebro(optreturn=False)
            cerebro.adddata(data)
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trade_analyzer')
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
            cerebro.broker.setcash(capital)
            cerebro.broker.setcommission(commission=0.001)
            
            final_results = run_grid_search(cerebro, strategy_cls, params_config, capital)
            
        elif algorithm == 'optuna':
            n_trials = int(sys_config.get('n_trials', 50))
            # Optuna 内部会创建 Cerebro，传入 data 对象即可 (Backtrader Data 是可复用的吗？通常是)
            # 为了安全，Store.get_data 返回的是新实例最好，或者我们只传 store 和参数
            # Backtrader 的 Data Feed 一旦被 Cerebro run 过，可能会耗尽 iterator
            # 所以在 Optuna 循环里，每次都得重新加载数据，或者 reset
            # 最稳妥：每次 trial 重新 create data
            # 为了性能：Preload data into memory (PandasData) then reuse
            # 这里的 store.get_data 返回的是 PandasData (如果底层是)，可以复用吗？
            # 让我们在 run_optuna_search 里每次都 store.get_data
            
            # 由于 store.get_data 可能涉及 API 调用，太慢。
            # 应该先下载为 DataFrame，然后使用 bt.feeds.PandasData
            # 假设 store.get_data 返回的是 bt.feeds.PandasData，且基于 df
            # 我们在外面先拿一次，然后 clone？
            
            # 优化：
            # df = store.get_historical_df(...) 
            # 然后在 loop 里 bt.feeds.PandasData(dataname=df)
            
            # 目前 store.get_data 封装了逻辑，我们暂时假设它足够快(如果是读DB/Cache)
            # 或者我们简单地传 store 和参数进去
            
            # 修改 run_optuna_search 签名，传入 store 和 data_args
            
            final_results = run_optuna_search(strategy_cls, params_config, data, capital, n_trials)
            
        # 排序并保存
        final_results.sort(key=lambda x: x['metrics']['net_profit'], reverse=True)
        top_results = final_results[:50]
        
        job.result_json = json.dumps(top_results)
        job.status = 'COMPLETED'
        job.progress = 100.0
        job.updated_at = datetime.utcnow()
        session.commit()
        
        print("✅ Optimization Job Completed.")
        
    except Exception as e:
        # ... (错误处理不变)
        import traceback
        traceback.print_exc()
        print(f"❌ Error: {e}")
        job.status = 'ERROR'
        session.commit()
    finally:
        session.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--job_id', required=True, help='Optimization Job ID')
    args = parser.parse_args()
    
    run_optimization_job(args.job_id)
