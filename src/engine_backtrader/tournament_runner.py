import argparse
import sys
import os
import json
import time
import uuid
import pandas as pd
import traceback
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils.db_manager import db_manager
from src.utils.db_models import Tournament, TournamentResult
from src.utils.backtester import Backtester
from src.utils.metrics import calculate_metrics

def run_single_match(match_config):
    """
    运行单场比赛 (单个选手回测)
    """
    try:
        strategy_name = match_config['strategy']
        symbol = match_config['symbol']
        timeframe = match_config['timeframe']
        initial_cash = match_config['initial_cash']
        start_date = match_config['start_date']
        end_date = match_config['end_date']
        commission = match_config.get('commission', 0.0004)
        
        # 实例化回测引擎
        bt = Backtester(
            strategy_name=strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            commission=commission
        )
        
        # 运行回测 (使用默认参数)
        # TODO: Support Deep Optimization mode (Grid Search params)
        final_value, history_df = bt.run()
        
        # 计算详细指标
        metrics = calculate_metrics(history_df, initial_capital=initial_cash)
        
        # 提取资金曲线 (简化，每天取一点，减少存储)
        if not history_df.empty:
            # Resample to daily to save space
            history_df['datetime'] = pd.to_datetime(history_df['datetime'])
            curve = history_df.set_index('datetime')['value'].resample('D').last().fillna(method='ffill').reset_index()
            curve_json = curve.to_json(orient='records', date_format='iso')
        else:
            curve_json = "[]"
            
        return {
            "status": "COMPLETED",
            "metrics": metrics,
            "equity_curve": curve_json,
            "params": bt.strategy_params or {}, # Default params
            "error": None
        }
        
    except Exception as e:
        return {
            "status": "ERROR",
            "metrics": {},
            "equity_curve": "[]",
            "params": {},
            "error": str(e)
        }

def run_tournament(tournament_id):
    session = db_manager.get_session()
    try:
        # 1. 获取锦标赛配置
        tournament = session.query(Tournament).filter_by(id=tournament_id).first()
        if not tournament:
            print(f"Tournament {tournament_id} not found")
            return

        # Restore status to RUNNING if it was PAUSED or PENDING
        if tournament.status != 'RUNNING':
            tournament.status = 'RUNNING'
            session.commit()
        
        config = json.loads(tournament.config_json)
        strategies = config.get('strategies', [])
        symbols = config.get('symbols', [])
        timeframes = config.get('timeframes', [])
        mode = config.get('mode', 'quick') # quick or deep
        
        # 2. 生成任务列表 (Cartesian Product)
        all_tasks = []
        for strat in strategies:
            for sym in symbols:
                for tf in timeframes:
                    # 获取该策略的特定参数配置 (如果有)
                    strat_params = config.get('strategies_config', {}).get(strat, {})
                    # 获取该策略的优化器配置
                    opt_config = strat_params.get('opt_config', {})
                    
                    # TODO: If mode is 'deep', expand tasks based on opt_config (Grid Search)
                    # For now, we treat 'deep' with 'optuna' as a single task that runs optimization internally?
                    # OR we expand grid search here?
                    # The user requirement implies "Grid/Optuna" selection. 
                    # If Grid: Expand here. If Optuna: Single task running optuna?
                    # Let's keep it simple: One task per (Strat, Sym, TF) and let run_single_match handle the optimization logic 
                    # if 'opt_config' is present.
                    
                    all_tasks.append({
                        "strategy": strat,
                        "symbol": sym,
                        "timeframe": tf,
                        "initial_cash": config.get('initial_cash', 10000),
                        "start_date": config.get('start_date'),
                        "end_date": config.get('end_date'),
                        "commission": config.get('commission', 0.0004),
                        "opt_config": opt_config
                    })
        
        total_tasks = len(all_tasks)
        
        # 3. 检查已完成的任务 (支持断点续传)
        existing_results = session.query(TournamentResult).filter_by(tournament_id=tournament_id).all()
        # Create a set of signatures: "{strategy}|{symbol}|{timeframe}"
        # Note: If we expand grid search parameters, signature must include params.
        # For now, assuming 1 task per combination (internal optimization), this signature is unique enough.
        completed_signatures = set()
        for res in existing_results:
            if res.status == 'COMPLETED':
                completed_signatures.add(f"{res.strategy_name}|{res.symbol}|{res.timeframe}")
        
        tasks_to_run = []
        for t in all_tasks:
            sig = f"{t['strategy']}|{t['symbol']}|{t['timeframe']}"
            if sig not in completed_signatures:
                tasks_to_run.append(t)
        
        completed_count = len(completed_signatures)
        print(f"Tournament {tournament.name}: Total {total_tasks}, Completed {completed_count}, Remaining {len(tasks_to_run)}")
        
        # Update Total Tasks count
        tournament.total_tasks = total_tasks
        tournament.completed_tasks = completed_count
        tournament.progress = completed_count / total_tasks if total_tasks > 0 else 0
        session.commit()
        
        if not tasks_to_run:
            print("All tasks completed.")
            tournament.status = 'COMPLETED'
            tournament.progress = 1.0
            session.commit()
            return

        # 4. 执行任务 (使用进程池并行)
        # 限制最大并发数，避免数据库连接耗尽或内存溢出
        max_workers = min(os.cpu_count(), 4) 
        
        completed_count = 0
        
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {executor.submit(run_single_match, task): task for task in tasks_to_run}
            
            for future in as_completed(future_to_task):
                # Check for PAUSE/STOP signal
                session.expire(tournament)
                if tournament.status == 'PAUSED':
                    print("Tournament Paused. Waiting...")
                    while tournament.status == 'PAUSED':
                        time.sleep(5)
                        session.expire(tournament)
                        if tournament.status == 'STOPPED': break
                
                if tournament.status == 'STOPPED':
                    print("Tournament Stopped by User.")
                    break

                task = future_to_task[future]
                try:
                    result = future.result()
                    
                    # 4. 保存结果
                    res_record = TournamentResult(
                        id=str(uuid.uuid4()),
                        tournament_id=tournament_id,
                        strategy_name=task['strategy'],
                        symbol=task['symbol'],
                        timeframe=task['timeframe'],
                        params_json=json.dumps(result['params']),
                        metrics_json=json.dumps(result['metrics']),
                        equity_curve_json=result['equity_curve'],
                        status=result['status'],
                        error_msg=result['error']
                    )
                    session.add(res_record)
                    
                    completed_count += 1
                    progress = completed_count / total_tasks
                    
                    # 更新主任务进度
                    tournament.progress = progress
                    tournament.completed_tasks = completed_count
                    session.commit()
                    
                    # Redis Push (Optional)
                    # redis_client.publish_tournament_progress(...)
                    
                    print(f"Match Completed: {task['strategy']} on {task['symbol']} ({completed_count}/{total_tasks})")
                    
                except Exception as e:
                    print(f"Task Execution Error: {e}")
        
        if tournament.status != 'STOPPED':
            tournament.status = 'COMPLETED'
            tournament.progress = 1.0
            session.commit()
            print("Tournament Completed Successfully")

    except Exception as e:
        print(f"Tournament Failed: {e}")
        traceback.print_exc()
        if tournament:
            tournament.status = 'ERROR'
            session.commit()
    finally:
        session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--tournament_id', required=True, help='Tournament ID')
    args = parser.parse_args()
    
    run_tournament(args.tournament_id)
