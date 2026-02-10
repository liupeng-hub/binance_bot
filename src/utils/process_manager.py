import subprocess
import os
import sys
import signal
import psutil
from .db_manager import db_manager
from .db_models import StrategyInstance, TradeRecord, EquityRecord, SignalRecord
from .redis_client import redis_client
from datetime import datetime

class ProcessManager:
    def __init__(self):
        # 定位 instance_runner.py
        # src/utils/process_manager.py -> src/utils -> src -> binance_bot
        self.root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.runner_script = os.path.join(self.root_dir, 'instance_runner.py')
        
    def start_instance(self, instance_id):
        """启动策略实例进程"""
        session = db_manager.get_session()
        instance = session.query(StrategyInstance).filter_by(id=instance_id).first()
        
        if not instance:
            session.close()
            return False, "Instance not found"
            
        if instance.status == 'RUNNING':
            # 检查进程是否真的在运行
            if instance.pid and psutil.pid_exists(instance.pid):
                session.close()
                return False, "Instance is already running"
            else:
                # 僵尸状态，重置
                instance.status = 'STOPPED'
                session.commit()
        
        try:
            # --- 1. 准备日志路径 ---
            # 构建日志路径 (提前定义，供后续使用)
            log_dir = os.path.join(self.root_dir, 'logs', 'instances')
            os.makedirs(log_dir, exist_ok=True)
            
            # 格式化时间戳: YYYYMMDD_HHMMSS
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 新的文件名格式: time_instanceId.log，方便按名称排序
            log_filename = f"{ts_str}_{instance_id}.log"
            log_file = os.path.join(log_dir, log_filename)

            # --- 2. 数据清理与模式处理 ---
            # 区分 回测 (Backtest) 和 实盘 (Live) 的启动逻辑
            
            file_mode = 'w' # 默认覆盖日志
            
            if instance.mode == 'live':
                # [实盘模式]: 
                # 1. 保留历史数据 (Trade/Equity/Signal)
                # 2. 如果之前有日志文件，我们是继续追加还是创建新的？
                #    用户需求是"方便排序查找新日志"，倾向于每次启动都生成新文件。
                #    但为了不丢失旧日志引用，我们可以让 log_path 指向最新的这个。
                #    或者：实盘模式通常希望看连续日志。
                #    折中方案：每次启动都生成带时间戳的新文件。
                file_mode = 'w' # 既然是新文件，就用 write 模式
                
                # 可选: 在新日志开头注明接续信息
                # with open(log_file, 'w') as f:
                #    f.write(f"RESTART SESSION {datetime.now()} for Instance {instance_id}\n")
            else:
                # [回测模式]: 
                # 1. 清理该实例的历史数据 (Fresh Start)
                # 2. 生成新日志文件
                session.query(TradeRecord).filter_by(instance_id=instance_id).delete()
                session.query(EquityRecord).filter_by(instance_id=instance_id).delete()
                session.query(SignalRecord).filter_by(instance_id=instance_id).delete()
                instance.progress = 0.0
            
            session.commit()
            
            # --- 3. 启动进程 ---
            
            # 启动子进程
            # 注意：使用 python3
            # 添加 -u 参数，禁用缓冲，确保日志实时输出
            cmd = [sys.executable, '-u', self.runner_script, '--instance_id', instance_id]
            
            # 使用 nohup 模式或 detach (在 Windows/Linux 有差异，这里针对 POSIX)
            with open(log_file, file_mode) as f:
                process = subprocess.Popen(
                    cmd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    cwd=self.root_dir,
                    preexec_fn=os.setpgrp # 独立进程组
                )
            
            # 更新 DB
            instance.pid = process.pid
            instance.status = 'RUNNING'
            # 无论之前是否有路径，都更新为最新的 log_file
            instance.log_path = log_file 
            session.commit()
            
            # Redis 推送
            redis_client.publish_status(instance_id, {'status': 'RUNNING', 'pid': process.pid, 'log_path': log_file})
            
            return True, f"Started with PID {process.pid}"
            
        except Exception as e:
            instance.status = 'ERROR'
            session.commit()
            return False, str(e)
        finally:
            session.close()

    def stop_instance(self, instance_id):
        """
        停止策略实例
        """
        session = db_manager.get_session()
        instance = session.query(StrategyInstance).filter_by(id=instance_id).first()
        
        if not instance:
            session.close()
            return False, "Instance not found"
            
        pid = instance.pid
        if pid:
            try:
                # 尝试终止进程
                os.kill(pid, signal.SIGTERM)
                # 等待一会儿确保退出? (可选)
            except ProcessLookupError:
                pass # 进程已经不存在了
            except Exception as e:
                print(f"Error killing process {pid}: {e}")
        
        instance.status = 'STOPPED'
        instance.pid = None
        session.commit()
        
        # Redis 推送
        redis_client.publish_status(instance_id, {'status': 'STOPPED', 'pid': None})
        
        session.close()
        
        return True, "Stopped"

    def start_optimization(self, job_id):
        """
        启动优化任务 (异步进程)
        """
        # 修正路径: src/utils/process_manager.py -> src -> engine_backtrader -> optimization_runner.py
        # root_dir is binance_bot
        script_path = os.path.join(self.root_dir, 'src', 'engine_backtrader', 'optimization_runner.py')
        
        # 准备日志
        log_dir = os.path.join(self.root_dir, 'logs', 'optimization')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"opt_{job_id}.log")
        
        # 构建命令
        cmd = [sys.executable, '-u', script_path, '--job_id', str(job_id)]
        
        try:
            with open(log_file, 'w') as f:
                # 启动子进程
                process = subprocess.Popen(
                    cmd,
                    cwd=self.root_dir, # Use project root as cwd
                    stdout=f, 
                    stderr=subprocess.STDOUT
                )
            
            # 记录 PID
            return True, process.pid
            
        except Exception as e:
            return False, str(e)

process_manager = ProcessManager()
