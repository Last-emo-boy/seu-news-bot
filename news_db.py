import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "news.db"

class NewsDB:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self._create_table()
    
    def _create_table(self):
        cursor = self.conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS news
                          (channel TEXT, title TEXT, url TEXT PRIMARY KEY, 
                           pub_date TEXT, created_at TEXT)''')
        self.conn.commit()

    def insert_news(self, news_list):
        cursor = self.conn.cursor()
        for channel, title, url, pub_date in news_list:
            try:
                cursor.execute('''INSERT INTO news 
                               VALUES (?, ?, ?, ?, ?)''',
                               (channel, title, url, pub_date, 
                                datetime.now().isoformat()))
            except sqlite3.IntegrityError:
                continue
        self.conn.commit()

    def get_latest_date(self, channel):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT pub_date FROM news 
                       WHERE channel = ? 
                       ORDER BY pub_date DESC LIMIT 1''', (channel,))
        result = cursor.fetchone()
        return result[0] if result else None

    def get_news(self, channel=None, page=1, per_page=10, keyword=None, start_date=None, end_date=None):
        cursor = self.conn.cursor()
        query = "SELECT * FROM news"
        conditions = []
        params = []
        if channel:
            conditions.append("channel = ?")
            params.append(channel)
        if keyword:
            conditions.append("title LIKE ?")
            params.append(f"%{keyword}%")
        if start_date:
            conditions.append("pub_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("pub_date <= ?")
            params.append(end_date)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY pub_date DESC LIMIT ? OFFSET ?"
        params.extend([per_page, (page - 1) * per_page])
        cursor.execute(query, params)
        return cursor.fetchall()


    def close(self):
        self.conn.close()