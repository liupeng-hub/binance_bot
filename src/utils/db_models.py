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
    accounts = relationship("ExchangeAccount", back_populates="user")
    instances = relationship("StrategyInstance", back_populates="user")

class ExchangeAccount(Base):
    """
    交易所账户表 (多账户支持)
    """
    __tablename__ = 'exchange_accounts'
    
    id = Column(String, primary_key=True) # UUID
    user_id = Column(Integer, ForeignKey('users.id'))
    
    alias = Column(String, nullable=False) # 账户别名
    exchange = Column(String, default='binance') # binance, okx, etc.
    account_type = Column(String, default='live') # live, testnet
    
    api_key_enc = Column(String)
    secret_key_enc = Column(String)
    
    # 额外配置 (JSON): passphrase, subaccount_id, etc.
    extra_config = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="accounts")
    instances = relationship("StrategyInstance", back_populates="account")

class ExchangeConfig(Base):
    __tablename__ = 'exchange_configs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    exchange_name = Column(String, default='binance')
    
    # 真实交易 (Live)
    api_key_enc = Column(String) # Encrypted API Key
    secret_key_enc = Column(String) # Encrypted Secret Key
    
    # 测试网交易 (Testnet)
    testnet_api_key_enc = Column(String) # Encrypted API Key (Testnet)
    testnet_secret_key_enc = Column(String) # Encrypted Secret Key (Testnet)
    
    user = relationship("User", back_populates="configs")

class StrategyInstance(Base):
    __tablename__ = 'strategy_instances'
    
    id = Column(String, primary_key=True) # UUID
    user_id = Column(Integer, ForeignKey('users.id'))
    account_id = Column(String, ForeignKey('exchange_accounts.id'), nullable=True) # 关联的具体账户
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
    account = relationship("ExchangeAccount", back_populates="instances")

class StrategyState(Base):
    """
    策略状态持久化表 (P0)
    用于存储策略的运行时状态（持仓、未成交订单），以便重启恢复。
    """
    __tablename__ = 'strategy_states'
    
    id = Column(Integer, primary_key=True)
    instance_id = Column(String, ForeignKey('strategy_instances.id'), unique=True, nullable=False)
    
    # 状态数据 (JSON)
    # {
    #   "positions": {"BTC/USDT": {"size": 1.0, "price": 50000}},
    #   "open_orders": [{"id": "123", "symbol": "BTC/USDT", "side": "BUY", ...}],
    #   "metadata": {"last_processed_dt": "..."}
    # }
    state_json = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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

class Tournament(Base):
    """
    策略竞技场 (锦标赛) 表
    """
    __tablename__ = 'tournaments'
    
    id = Column(String, primary_key=True) # UUID
    user_id = Column(Integer, ForeignKey('users.id'))
    
    name = Column(String, nullable=False)
    # 配置 (JSON): 包含策略池、标的池、周期池、资金、时间范围、优化模式等
    config_json = Column(Text)
    
    status = Column(String, default='PENDING') # PENDING, RUNNING, PAUSED, STOPPED, COMPLETED, ERROR
    progress = Column(Float, default=0.0) # 总进度
    total_tasks = Column(Integer, default=0) # 预估总子任务数
    completed_tasks = Column(Integer, default=0) # 已完成子任务数
    
    pid = Column(Integer, nullable=True) # 后台 Runner 进程 ID
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    # 关联结果
    results = relationship("TournamentResult", back_populates="tournament", cascade="all, delete-orphan")

class TournamentResult(Base):
    """
    锦标赛结果明细表
    """
    __tablename__ = 'tournament_results'
    
    id = Column(String, primary_key=True) # UUID
    tournament_id = Column(String, ForeignKey('tournaments.id'))
    
    strategy_name = Column(String)
    symbol = Column(String)
    timeframe = Column(String)
    
    # 最终使用的参数 (如果是深度优化，则是优选后的参数)
    params_json = Column(Text)
    
    # 评价指标 (JSON): net_profit, sharpe, max_dd, win_rate, etc.
    metrics_json = Column(Text)
    
    # 资金曲线 (JSON): 用于前端绘制 "赛跑图" (简化版，非全量)
    equity_curve_json = Column(Text)
    
    status = Column(String) # COMPLETED, ERROR
    error_msg = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    tournament = relationship("Tournament", back_populates="results")

class OptimizationJob(Base):
    """
    参数调优任务表
    """
    __tablename__ = 'optimization_jobs'

    id = Column(String, primary_key=True) # UUID
    user_id = Column(Integer, ForeignKey('users.id'))
    
    # 新增: 关联锦标赛 (可选)
    # 如果该调优任务是由锦标赛触发的 (深度优化模式)，则关联之
    tournament_id = Column(String, ForeignKey('tournaments.id'), nullable=True)
    
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

class MarketData(Base):
    """
    市场数据表 (K线数据)
    设计为兼容 TimescaleDB 的 Hypertable
    """
    __tablename__ = 'market_data'
    
    # 联合主键: time + symbol + timeframe
    # 注意: 在 TimescaleDB 中，time 必须是主键的一部分
    timestamp = Column(DateTime, primary_key=True, nullable=False)
    symbol = Column(String, primary_key=True, nullable=False)
    timeframe = Column(String, primary_key=True, nullable=False) # e.g. '1m', '1h'
    
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    
    # 额外的元数据 (可选)
    # created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<MarketData({self.symbol} {self.timeframe} @ {self.timestamp}: C={self.close})>"
