from src.utils.db_manager import db_manager
from src.utils.db_models import User
import hashlib

db_manager.init_db()
session = db_manager.get_session()
user = session.query(User).filter_by(username='admin').first()
if user:
    new_pass = '123'
    user.password_hash = hashlib.sha256(new_pass.encode()).hexdigest()
    session.commit()
    print(f"Password for 'admin' reset to '{new_pass}'")
else:
    print("User 'admin' not found")
session.close()
