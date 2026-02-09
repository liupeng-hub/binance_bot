from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from cryptography.fernet import Fernet
import os
import hashlib
import json
from .db_models import Base, User

class DBManager:
    def __init__(self, db_path=None):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if db_path is None:
            # 默认存储在 data/trades.db
            db_path = os.path.join(root_dir, 'data', 'trades.db')
            
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
            
        # SQLite 连接字符串
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False, connect_args={'check_same_thread': False})
        self.Session = sessionmaker(bind=self.engine)
        
    def init_db(self):
        """创建表结构并初始化默认管理员"""
        Base.metadata.create_all(self.engine)
        self.create_admin_if_not_exists()
        
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
