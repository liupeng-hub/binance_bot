from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from cryptography.fernet import Fernet
import os
import hashlib
import json
from .db_models import Base, User

class DBManager:
    def __init__(self, db_url=None):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
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
        self.Session = sessionmaker(bind=self.engine)
        
    def init_db(self):
        """创建表结构并初始化默认管理员"""
        # 1. 创建普通表
        Base.metadata.create_all(self.engine)
        
        # 2. 如果是 PostgreSQL，尝试启用 TimescaleDB 扩展并转换超表
        if 'postgresql' in self.db_url:
            self._init_timescaledb()
            
        self.create_admin_if_not_exists()

    def _init_timescaledb(self):
        """尝试初始化 TimescaleDB (如果可用)"""
        try:
            with self.engine.connect() as conn:
                # 启用扩展 (需要 superuser 权限，如果失败则忽略)
                try:
                    conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")
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
                    conn.execute("SELECT create_hypertable('market_data', 'timestamp', if_not_exists => TRUE);")
                    conn.commit()
                    print("✅ MarketData converted to Hypertable.")
                except Exception as e:
                    print(f"⚠️ Failed to convert market_data to hypertable: {e}")
        except Exception as e:
            print(f"⚠️ Error initializing TimescaleDB: {e}")
        
    def get_session(self):
        return self.Session()
    
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

    def encrypt_secret(self, text):
        if not text: return None
        return self.cipher.encrypt(text.encode()).decode()

    def decrypt_secret(self, encrypted_text):
        if not encrypted_text: return None
        return self.cipher.decrypt(encrypted_text.encode()).decode()

# 单例实例
db_manager = DBManager()
