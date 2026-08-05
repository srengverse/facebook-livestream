import sqlite3
import os
from datetime import datetime

class Database:
    def __init__(self, db_path='database.db'):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Settings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            # Videos table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    duration TEXT,
                    resolution TEXT,
                    bitrate TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Logs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT,
                    message TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Stream status table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stream_status (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    is_streaming BOOLEAN DEFAULT 0,
                    live_video_id TEXT,
                    stream_url TEXT,
                    secure_stream_url TEXT,
                    start_time TIMESTAMP,
                    restarts INTEGER DEFAULT 0
                )
            ''')
            
            # Initialize stream status if not exists
            cursor.execute('INSERT OR IGNORE INTO stream_status (id, is_streaming) VALUES (1, 0)')
            
            conn.commit()

    def log(self, level, message):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO logs (level, message) VALUES (?, ?)', (level, message))
            conn.commit()

    def get_logs(self, limit=100):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_setting(self, key, default=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row['value'] if row else default

    def set_setting(self, key, value):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
            conn.commit()

    def add_video(self, filename, filepath, duration=None, resolution=None, bitrate=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO videos (filename, filepath, duration, resolution, bitrate)
                VALUES (?, ?, ?, ?, ?)
            ''', (filename, filepath, duration, resolution, bitrate))
            conn.commit()

    def get_videos(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM videos ORDER BY created_at DESC')
            return [dict(row) for row in cursor.fetchall()]

    def update_video_filename(self, video_id, new_filename):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE videos SET filename = ? WHERE id = ?', (new_filename, video_id))
            conn.commit()

    def delete_video(self, video_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT filepath FROM videos WHERE id = ?', (video_id,))
            row = cursor.fetchone()
            if row and os.path.exists(row['filepath']):
                os.remove(row['filepath'])
            cursor.execute('DELETE FROM videos WHERE id = ?', (video_id,))
            conn.commit()

    def update_stream_status(self, is_streaming, **kwargs):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if is_streaming:
                cursor.execute('''
                    UPDATE stream_status SET 
                    is_streaming = 1,
                    live_video_id = ?,
                    stream_url = ?,
                    secure_stream_url = ?,
                    start_time = ?,
                    restarts = restarts + ?
                    WHERE id = 1
                ''', (
                    kwargs.get('live_video_id'),
                    kwargs.get('stream_url'),
                    kwargs.get('secure_stream_url'),
                    datetime.now().isoformat(),
                    kwargs.get('restarts', 0)
                ))
            else:
                cursor.execute('UPDATE stream_status SET is_streaming = 0, start_time = NULL WHERE id = 1')
            conn.commit()

    def get_stream_status(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM stream_status WHERE id = 1')
            row = cursor.fetchone()
            return dict(row) if row else None
