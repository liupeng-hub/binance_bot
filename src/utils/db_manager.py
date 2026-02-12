from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from cryptography.fernet import Fernet
import os
import hashlib
import json
import uuid
from dotenv import load_dotenv
from .db_models import Base, User, TradeRecord, EquityRecord, SignalRecord, StrategyState, StrategyInstance, ExchangeAccount

class DBManager:
    def __init__(self, db_url=None):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        # 加载 .env 文件
        load_dotenv(os.path.join(root_dir, '.env'))
        
        # 优先从环境变量读取数据库连接串
        # e.g. postgresql://user:pass@localhost:5432/mydb
        self.db_url = os.environ.get('DATABASE_URL')
        
        if not self.db_url:
            if db_url:
                self.db_url = db_url
            else:
                # 默认存储在 data/trades.db
                db_path = os.path.join(root_dir, 'data', 'trades.db')
                self.db_url = f'sqlite:///{db_path}'
            
        # 密钥管理 (用于加密 API Key)
        # 在生产环境中，这个 KEY 应该从环境变量读取，绝对不能硬编码或存储在代码库中
        # 这里为了演示方便，如果不存在则生成一个并保存到 .secret_key 文件
        key_file = os.path.join(root_dir, '.secret_key')
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                self.cipher_key = f.read()
        else:
            self.cipher_key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(self.cipher_key)
        
        self.cipher = Fernet(self.cipher_key)
            
        # 根据 URL 类型配置 Engine
        connect_args = {}
        if self.db_url.startswith('sqlite'):
            connect_args = {'check_same_thread': False}
            self.engine = create_engine(self.db_url, echo=False, connect_args=connect_args)
        else:
            # PostgreSQL 等远程数据库的连接优化
            self.engine = create_engine(
                self.db_url,
                echo=False,
                connect_args=connect_args,
                pool_pre_ping=True,      # 每次取连接前先探测，防止超时断开
                pool_recycle=1800,       # 缩短回收时间 (1小时 -> 30分钟)
                pool_size=int(os.environ.get('DB_POOL_SIZE', 10)),      # 增大默认池大小 (5 -> 10)
                max_overflow=int(os.environ.get('DB_MAX_OVERFLOW', 20)), # 增大溢出限制 (10 -> 20)
                pool_timeout=int(os.environ.get('DB_POOL_TIMEOUT', 60)) # 延长超时等待 (30 -> 60秒)
            )
            
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False, autoflush=True, autocommit=False)
        
    def init_db(self):
        """创建表结构并初始化默认管理员"""
        # 1. 创建普通表
        Base.metadata.create_all(self.engine)
        
        # 1.5 简单的 Schema 迁移 (检查并添加新列)
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(self.engine)
            if 'strategy_instances' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('strategy_instances')]
                if 'account_id' not in cols:
                    print("⚠️ Migrating: Adding account_id to strategy_instances...")
                    with self.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE strategy_instances ADD COLUMN account_id VARCHAR;"))
                        conn.commit()
        except Exception as e:
            print(f"⚠️ Migration check failed: {e}")
        
        # 2. 如果是 PostgreSQL，尝试启用 TimescaleDB 扩展并转换超表
        if 'postgresql' in self.db_url:
            self._init_timescaledb()
            
        self.create_admin_if_not_exists()

    def _init_timescaledb(self):
        """尝试初始化 TimescaleDB (如果可用)"""
        try:
            from sqlalchemy import text
            with self.engine.connect() as conn:
                # 启用扩展 (需要 superuser 权限，如果失败则忽略)
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
                    conn.commit()
                    print("✅ TimescaleDB extension enabled.")
                except Exception as e:
                    print(f"⚠️ Could not enable TimescaleDB extension (might need superuser): {e}")
                    # 如果无法启用扩展，后续转换超表也会失败，所以直接返回
                    return 

                # 转换 MarketData 为超表
                # 按 timestamp 分区
                try:
                    # 检查是否已经是超表
                    # 注意: 这里的 SQL 语法是针对 PG/Timescale 的
                    conn.execute(text("SELECT create_hypertable('market_data', 'timestamp', if_not_exists => TRUE);"))
                    conn.commit()
                    print("✅ MarketData converted to Hypertable.")
                except Exception as e:
                    print(f"⚠️ Failed to convert market_data to hypertable: {e}")
        except Exception as e:
            print(f"⚠️ Error initializing TimescaleDB: {e}")
        
    def get_session(self):
        return self.Session()

    def dispose(self):
        try:
            self.engine.dispose()
        except Exception:
            pass

    def execute_with_retry(self, func, max_retries=3):
        """执行数据库操作的重试逻辑"""
        last_exception = None
        for attempt in range(max_retries):
            session = self.get_session()
            try:
                return func(session)
            except Exception as e:
                last_exception = e
                session.rollback()
                print(f"⚠️ Database operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                import time
                time.sleep(1) # 等待 1 秒后重试
            finally:
                session.close()
        raise last_exception
    
    def create_admin_if_not_exists(self):
        session = self.Session()
        admin = session.query(User).filter_by(username='admin').first()
        if not admin:
            # 默认密码: admin123
            pwd_hash = hashlib.sha256('admin123'.encode()).hexdigest()
            new_admin = User(username='admin', password_hash=pwd_hash, role='admin')
            session.add(new_admin)
            session.commit()
            print("Default admin user created (admin/admin123)")
        session.close()
    
    def get_all_users(self, session):
        """获取所有用户 (Admin Use)"""
        return session.query(User).all()

    def encrypt_secret(self, text):
        if not text: return None
        return self.cipher.encrypt(text.encode()).decode()

    def decrypt_secret(self, encrypted_text):
        if not encrypted_text: return None
        return self.cipher.decrypt(encrypted_text.encode()).decode()

    # --- Exchange Account Management ---
    def add_exchange_account(self, session, user_id, alias, api_key, secret_key, account_type='live', exchange='binance', extra_config=None):
        """添加新的交易所账户配置"""
        # Check alias uniqueness for this user
        existing = session.query(ExchangeAccount).filter_by(user_id=user_id, alias=alias).first()
        if existing:
            raise ValueError(f"Account alias '{alias}' already exists.")
            
        new_account = ExchangeAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            alias=alias,
            exchange=exchange,
            account_type=account_type,
            api_key_enc=self.encrypt_secret(api_key),
            secret_key_enc=self.encrypt_secret(secret_key),
            extra_config=json.dumps(extra_config) if extra_config else None
        )
        session.add(new_account)
        return new_account

    def get_exchange_accounts(self, session, user_id):
        """获取用户的所有账户配置"""
        return session.query(ExchangeAccount).filter_by(user_id=user_id).all()

    def get_exchange_account(self, session, account_id):
        return session.query(ExchangeAccount).filter_by(id=account_id).first()

    def delete_exchange_account(self, session, account_id, user_id):
        """删除账户配置 (需检查是否有运行中的实例关联)"""
        # Check for running instances
        running_instances = session.query(StrategyInstance).filter_by(account_id=account_id, status='RUNNING').first()
        if running_instances:
            raise ValueError("Cannot delete account with running instances.")
            
        account = session.query(ExchangeAccount).filter_by(id=account_id, user_id=user_id).first()
        if account:
            session.delete(account)
            session.commit() # Commit the deletion
            return True
        return False

    def delete_instance_cascade(self, session, instance_id: str):
        """删除实例及其相关记录，避免外键约束冲突"""
        try:
            # 依次删除依赖表记录
            session.query(TradeRecord).filter_by(instance_id=instance_id).delete(synchronize_session=False)
            session.query(EquityRecord).filter_by(instance_id=instance_id).delete(synchronize_session=False)
            session.query(SignalRecord).filter_by(instance_id=instance_id).delete(synchronize_session=False)
            session.query(StrategyState).filter_by(instance_id=instance_id).delete(synchronize_session=False)
            # 最后删除实例
            session.query(StrategyInstance).filter_by(id=instance_id).delete(synchronize_session=False)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            print(f"Delete cascade failed: {e}")
            return False

# 单例实例
db_manager = DBManager()
