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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS news (
                key TEXT,
                source TEXT,
                channel TEXT,
                title TEXT,
                url TEXT PRIMARY KEY, 
                pub_date TEXT,
                created_at TEXT
            )
        ''')
        self.conn.commit()
    
    def insert_news(self, news_list, key=None):
        """
        插入新闻数据。
        
        参数：
          - news_list: 新闻记录列表，每条记录格式为 (source, channel, title, url, pub_date)
          - key: 可选的复合键（如 "教务处:zxdt"），若提供，则存入 key 字段；否则以 channel 作为默认 key。
        """
        cursor = self.conn.cursor()
        for record in news_list:
            source, channel, title, url, pub_date = record
            record_key = key if key is not None else channel
            try:
                cursor.execute('''
                    INSERT INTO news (key, source, channel, title, url, pub_date, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (record_key, source, channel, title, url, pub_date, datetime.now().isoformat()))
            except sqlite3.IntegrityError:
                continue
        self.conn.commit()
    
    def get_latest_date(self, key):
        """
        获取指定复合键（如 "教务处:zxdt"）的最新发布时间。
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT pub_date FROM news 
            WHERE key = ? 
            ORDER BY pub_date DESC LIMIT 1
        ''', (key,))
        result = cursor.fetchone()
        return result[0] if result else None
    
    def get_news(self, source=None, channel=None, page=1, per_page=10, keyword=None, start_date=None, end_date=None):
        """
        查询新闻记录，可根据新闻来源、栏目、关键词、发布日期区间进行过滤。
        返回格式为 (source, channel, title, url, pub_date)
        """
        cursor = self.conn.cursor()
        query = "SELECT source, channel, title, url, pub_date FROM news"
        conditions = []
        params = []
        if source:
            conditions.append("source = ?")
            params.append(source)
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
