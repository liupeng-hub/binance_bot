from src.utils.db_manager import db_manager
from src.utils.db_models import User
import hashlib

def create_default_admin():
    db_manager.init_db()
    session = db_manager.get_session()
    
    username = "admin"
    password = "admin"
    
    existing = session.query(User).filter_by(username=username).first()
    if not existing:
        print(f"Creating default admin user: {username}/{password}")
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        new_user = User(username=username, password_hash=pwd_hash, role='admin')
        session.add(new_user)
        session.commit()
        print("Done.")
    else:
        print(f"User {username} already exists.")
    
    session.close()

if __name__ == "__main__":
    create_default_admin()
