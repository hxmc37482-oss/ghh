import sqlite3
from datetime import datetime, timedelta
import pytz

class Database:
    def __init__(self, db_name):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                subscription_end TEXT,
                requests_count INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                invoice_id TEXT,
                status TEXT,
                date TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                target_username TEXT,
                status TEXT,
                date TEXT
            )
        ''')
        self.conn.commit()
    
    def add_user(self, user_id, username):
        self.cursor.execute(
            'INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)',
            (user_id, username)
        )
        self.conn.commit()
    
    def get_user(self, user_id):
        self.cursor.execute(
            'SELECT * FROM users WHERE user_id = ?', (user_id,)
        )
        return self.cursor.fetchone()
    
    def update_subscription(self, user_id, days):
        moscow_tz = pytz.timezone('Europe/Moscow')
        now = datetime.now(moscow_tz)
        
        user = self.get_user(user_id)
        if user and user[2]:
            end_date = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S')
            end_date = moscow_tz.localize(end_date)
            if end_date > now:
                new_end = end_date + timedelta(days=days)
            else:
                new_end = now + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
        
        self.cursor.execute(
            'UPDATE users SET subscription_end = ? WHERE user_id = ?',
            (new_end.strftime('%Y-%m-%d %H:%M:%S'), user_id)
        )
        self.conn.commit()
        return new_end
    
    def check_subscription(self, user_id):
        user = self.get_user(user_id)
        if not user or not user[2]:
            return False
        
        moscow_tz = pytz.timezone('Europe/Moscow')
        now = datetime.now(moscow_tz)
        end_date = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S')
        end_date = moscow_tz.localize(end_date)
        
        return end_date > now
    
    def add_payment(self, user_id, amount, invoice_id, status='pending'):
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cursor.execute(
            '''INSERT INTO payments (user_id, amount, invoice_id, status, date)
               VALUES (?, ?, ?, ?, ?)''',
            (user_id, amount, invoice_id, status, date)
        )
        # Обновляем total_spent
        self.cursor.execute(
            'UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?',
            (amount, user_id)
        )
        self.conn.commit()
    
    def update_payment(self, invoice_id, status):
        self.cursor.execute(
            'UPDATE payments SET status = ? WHERE invoice_id = ?',
            (status, invoice_id)
        )
        self.conn.commit()
    
    def increment_requests(self, user_id):
        self.cursor.execute(
            'UPDATE users SET requests_count = requests_count + 1 WHERE user_id = ?',
            (user_id,)
        )
        self.conn.commit()
    
    def add_request(self, user_id, target_username):
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cursor.execute(
            '''INSERT INTO requests (user_id, target_username, status, date)
               VALUES (?, ?, ?, ?)''',
            (user_id, target_username, 'pending', date)
        )
        self.conn.commit()
    
    def get_all_users(self):
        self.cursor.execute('SELECT * FROM users')
        return self.cursor.fetchall()
    
    def get_user_requests_today(self, user_id):
        today = datetime.now().strftime('%Y-%m-%d')
        self.cursor.execute(
            'SELECT COUNT(*) FROM requests WHERE user_id = ? AND date LIKE ?',
            (user_id, f'{today}%')
        )
        return self.cursor.fetchone()[0]