from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default='user') # user, admin
    created_at = Column(DateTime, default=datetime.utcnow)
    
    configs = relationship("ExchangeConfig", back_populates="user")
    instances = relationship("StrategyInstance", back_populates="user")

class ExchangeConfig(Base):
    __tablename__ = 'exchange_configs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    exchange_name = Column(String, default='binance')
    api_key_enc = Column(String) # Encrypted API Key
    secret_key_enc = Column(String) # Encrypted Secret Key
    
    user = relationship("User", back_populates="configs")

class StrategyInstance(Base):
    __tablename__ = 'strategy_instances'
    
    id = Column(String, primary_key=True) # UUID
    user_id = Column(Integer, ForeignKey('users.id'))
    symbol = Column(String, nullable=False)
    strategy_name = Column(String, nullable=False)
    config_json = Column(Text) # JSON string of params
    indicators_json = Column(Text) # JSON string of indicators config
    mode = Column(String, default='backtest') # backtest, live
    status = Column(String, default='PENDING') # PENDING, RUNNING, STOPPED, ERROR
    progress = Column(Float, default=0.0) # 0.0 to 100.0
    pid = Column(Integer, nullable=True)
    log_path = Column(String, nullable=True)
    metrics_json = Column(Text, nullable=True) # 新增：用于存储回测指标 (Max Drawdown, Win Rate, etc.)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="instances")

class BacktestResult(Base):
    """
    专门用于存储回测/实盘的历史绩效报告。
    每次策略运行结束(COMPLETED/STOPPED)时，生成一条记录。
    """
    __tablename__ = 'backtest_results'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    instance_id = Column(String) # 关联的原始实例 ID (非外键，因为实例可能被删除)
    
    strategy_name = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    mode = Column(String) # backtest, live
    timeframe = Column(String)
    
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    
    # 参数快照
    params_json = Column(Text)
    
    # 核心绩效指标
    initial_capital = Column(Float)
    final_value = Column(Float)
    net_profit = Column(Float)
    return_rate = Column(Float) # %
    max_drawdown = Column(Float) # %
    sharpe_ratio = Column(Float)
    win_rate = Column(Float)
    total_trades = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)

class TradeRecord(Base):
    __tablename__ = 'trades'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    instance_id = Column(String, ForeignKey('strategy_instances.id'))
    
    symbol = Column(String)
    side = Column(String)         # BUY or SELL
    price = Column(Float)
    size = Column(Float)
    value = Column(Float)
    commission = Column(Float)
    pnl = Column(Float)           # 仅平仓时有值
    timestamp = Column(DateTime, default=datetime.utcnow)
    order_id = Column(String)
    strategy_id = Column(String)  # 保留旧字段，对应 strategy_name
    extra_data = Column(Text)     # 新增：用于存储关联信息 (JSON)，例如 Trade 关联的 orders

    def __repr__(self):
        return f"<Trade(symbol='{self.symbol}', side='{self.side}', price={self.price}, pnl={self.pnl})>"

class EquityRecord(Base):
    __tablename__ = 'equity'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    instance_id = Column(String, ForeignKey('strategy_instances.id'), nullable=True) # 可选，如果是账户级净值则为空
    
    timestamp = Column(DateTime, default=datetime.utcnow)
    total_value = Column(Float)   # 账户总权益
    cash = Column(Float)          # 可用现金

    def __repr__(self):
        return f"<Equity(time='{self.timestamp}', value={self.total_value})>"

class SignalRecord(Base):
    __tablename__ = 'signals'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    instance_id = Column(String, ForeignKey('strategy_instances.id'))
    
    timestamp = Column(DateTime, default=datetime.utcnow)
    symbol = Column(String)
    signal_type = Column(String)
    price = Column(Float)
    comment = Column(String)

class OptimizationJob(Base):
    """
    参数调优任务表
    """
    __tablename__ = 'optimization_jobs'

    id = Column(String, primary_key=True) # UUID
    user_id = Column(Integer, ForeignKey('users.id'))
    
    strategy_name = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    
    # 搜索配置 (JSON)
    # e.g., {"fast_period": {"start": 5, "end": 20, "step": 1}, "slow_period": ...}
    params_config = Column(Text) 
    
    # 系统配置 (JSON): timeframe, days, capital
    sys_config = Column(Text)
    
    status = Column(String, default='PENDING') # PENDING, RUNNING, COMPLETED, ERROR
    progress = Column(Float, default=0.0)
    pid = Column(Integer, nullable=True)
    
    # 结果 (JSON)
    # 存储 Top N 的参数组合及其指标
    # e.g., [{"params": {...}, "metrics": {"return": 0.1, "sharpe": 1.5}}, ...]
    result_json = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")
