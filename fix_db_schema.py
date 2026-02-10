from src.utils.db_manager import db_manager
from sqlalchemy import text

def add_columns():
    session = db_manager.get_session()
    try:
        print("Checking for missing columns...")
        # Check if column exists (PostgreSQL specific)
        conn = session.connection()
        
        # Add testnet_api_key_enc
        try:
            conn.execute(text("ALTER TABLE exchange_configs ADD COLUMN testnet_api_key_enc VARCHAR"))
            print("✅ Added column: testnet_api_key_enc")
        except Exception as e:
            print(f"ℹ️ Column testnet_api_key_enc might already exist or error: {e}")
            
        # Add testnet_secret_key_enc
        try:
            conn.execute(text("ALTER TABLE exchange_configs ADD COLUMN testnet_secret_key_enc VARCHAR"))
            print("✅ Added column: testnet_secret_key_enc")
        except Exception as e:
            print(f"ℹ️ Column testnet_secret_key_enc might already exist or error: {e}")
            
        session.commit()
        print("Schema update completed.")
    except Exception as e:
        print(f"Error during schema update: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    add_columns()
