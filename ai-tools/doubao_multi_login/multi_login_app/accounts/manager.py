import sqlite3
from datetime import datetime
from .models import Account, encryption_util
import os
from utils.error_handling import handle_exception, validate_account_data, safe_execute

class AccountManager:
    def __init__(self, db_path='accounts.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                website TEXT NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    
    @handle_exception
    def add_account(self, name, website, username, password):
        valid, message = validate_account_data(name, website, username, password)
        if not valid:
            raise ValueError(message)
        
        encrypted_password = encryption_util.encrypt(password)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO accounts (name, website, username, password) VALUES (?, ?, ?, ?)",
            (name, website, username, encrypted_password)
        )
        account_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return Account(id=account_id, name=name, website=website, username=username, password=encrypted_password)
    
    @handle_exception
    def get_accounts(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts")
        rows = cursor.fetchall()
        conn.close()
        
        accounts = []
        for row in rows:
            account = Account(
                id=row[0],
                name=row[1],
                website=row[2],
                username=row[3],
                password=row[4],
                created_at=datetime.fromisoformat(row[5]) if row[5] else None,
                updated_at=datetime.fromisoformat(row[6]) if row[6] else None
            )
            accounts.append(account)
        return accounts
    
    @handle_exception
    def get_account(self, account_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return Account(
                id=row[0],
                name=row[1],
                website=row[2],
                username=row[3],
                password=row[4],
                created_at=datetime.fromisoformat(row[5]) if row[5] else None,
                updated_at=datetime.fromisoformat(row[6]) if row[6] else None
            )
        return None
    
    @handle_exception
    def update_account(self, account_id, **kwargs):
        account = self.get_account(account_id)
        if not account:
            return None
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if 'password' in kwargs:
            kwargs['password'] = encryption_util.encrypt(kwargs['password'])
        
        set_clause = []
        values = []
        for key, value in kwargs.items():
            set_clause.append(f"{key} = ?")
            values.append(value)
        values.append(account_id)
        
        query = f"UPDATE accounts SET {', '.join(set_clause)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()
        conn.close()
        
        return self.get_account(account_id)
    
    @handle_exception
    def delete_account(self, account_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected_rows > 0
    
    @handle_exception
    def get_decrypted_password(self, account):
        return encryption_util.decrypt(account.password)
    
    def close(self):
        # SQLite连接会在每次操作后自动关闭，这里不需要额外操作
        pass