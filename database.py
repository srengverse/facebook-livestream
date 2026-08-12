import sqlite3
import os
import threading
from datetime import datetime
from contextlib import contextmanager

class Database:
    def __init__(self, db_path='database.db'):
        self.db_path = db_path
        self._settings_cache = {}
        self._cache_lock = threading.Lock()
        self._db_lock = threading.Lock()
        self.init_db()

    @contextmanager
    def get_connection(self):
        """Context manager for thread-safe SQLite connections with proper cleanup."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
            yield conn
        finally:
            conn.close()

    def init_db(self):
        # Ensure required directories exist
        os.makedirs('logs', exist_ok=True)
        os.makedirs('uploads', exist_ok=True)
        
        with self._db_lock:
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
                # Index for faster log retrieval and pruning
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp DESC)')
                
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
                
                # Schedules table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS schedules (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        video_ids TEXT NOT NULL,
                        scheduled_time TIMESTAMP NOT NULL,
                        is_active BOOLEAN DEFAULT 1,
                        last_run TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                # Index for schedule lookups
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_schedules_active_time ON schedules(is_active, scheduled_time)')
                
                # Multi-platform RTMP destinations
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS stream_destinations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        platform TEXT NOT NULL CHECK (platform IN ('youtube', 'custom')),
                        rtmp_url TEXT NOT NULL,
                        stream_key_encrypted TEXT NOT NULL,
                        enabled BOOLEAN NOT NULL DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_destinations_enabled ON stream_destinations(enabled)')

                # Initialize stream status if not exists
                cursor.execute('INSERT OR IGNORE INTO stream_status (id, is_streaming) VALUES (1, 0)')
                
                conn.commit()

    def log(self, level, message):
        with self.get_connection() as conn:
            conn.execute('INSERT INTO logs (level, message) VALUES (?, ?)', (level, message))
            conn.commit()

    def get_logs(self, limit=100):
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def prune_logs(self, days=7):
        """Remove logs older than X days to save space."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM logs WHERE timestamp < datetime('now', ?)", (f'-{days} days',))
            conn.commit()

    def get_setting(self, key, default=None):
        with self._cache_lock:
            if key in self._settings_cache:
                return self._settings_cache[key]
            
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            val = row['value'] if row else default
            
            with self._cache_lock:
                self._settings_cache[key] = val
            return val

    def set_setting(self, key, value):
        with self.get_connection() as conn:
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
            conn.commit()
            
        with self._cache_lock:
            self._settings_cache[key] = str(value)

    def add_video(self, filename, filepath, duration=None, resolution=None, bitrate=None):
        with self.get_connection() as conn:
            conn.execute('''
                INSERT INTO videos (filename, filepath, duration, resolution, bitrate)
                VALUES (?, ?, ?, ?, ?)
            ''', (filename, filepath, duration, resolution, bitrate))
            conn.commit()

    def get_videos(self):
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM videos ORDER BY created_at DESC')
            return [dict(row) for row in cursor.fetchall()]

    def get_video(self, video_id):
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM videos WHERE id = ?', (video_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_video_filename(self, video_id, new_filename):
        with self.get_connection() as conn:
            conn.execute('UPDATE videos SET filename = ? WHERE id = ?', (new_filename, video_id))
            conn.commit()

    def delete_video(self, video_id):
        """Robustly delete a video and its file."""
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT filepath FROM videos WHERE id = ?', (video_id,))
            row = cursor.fetchone()
            
            if not row:
                return False
            
            filepath = row['filepath']
            
            # 1. Delete from DB first to prevent UI showing it if file delete fails
            conn.execute('DELETE FROM videos WHERE id = ?', (video_id,))
            conn.commit()
            
            # 2. Delete the file
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    # File might be already gone or locked, we already removed DB record
                    pass
            
            return True

    def add_destination(self, name, platform, rtmp_url, stream_key_encrypted, enabled=True):
        with self.get_connection() as conn:
            cursor = conn.execute(
                '''
                INSERT INTO stream_destinations
                    (name, platform, rtmp_url, stream_key_encrypted, enabled)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (name, platform, rtmp_url, stream_key_encrypted, int(bool(enabled))),
            )
            conn.commit()
            return cursor.lastrowid

    def get_destinations(self, enabled_only=False):
        with self.get_connection() as conn:
            query = 'SELECT * FROM stream_destinations'
            if enabled_only:
                query += ' WHERE enabled = 1'
            query += ' ORDER BY created_at ASC, id ASC'
            cursor = conn.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def get_destination(self, destination_id):
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM stream_destinations WHERE id = ?', (destination_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_destination(self, destination_id, *, name=None, platform=None, rtmp_url=None,
                           stream_key_encrypted=None, enabled=None):
        fields, values = [], []
        for column, value in (
            ('name', name),
            ('platform', platform),
            ('rtmp_url', rtmp_url),
            ('stream_key_encrypted', stream_key_encrypted),
        ):
            if value is not None:
                fields.append(f'{column} = ?')
                values.append(value)

        if enabled is not None:
            fields.append('enabled = ?')
            values.append(int(bool(enabled)))

        if not fields:
            return False

        fields.append('updated_at = CURRENT_TIMESTAMP')
        values.append(destination_id)
        
        with self.get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE stream_destinations SET {', '.join(fields)} WHERE id = ?", values
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_destination(self, destination_id):
        with self.get_connection() as conn:
            cursor = conn.execute('DELETE FROM stream_destinations WHERE id = ?', (destination_id,))
            conn.commit()
            return cursor.rowcount > 0

    def update_stream_status(self, is_streaming, *, new_session=False, **kwargs):
        with self.get_connection() as conn:
            if is_streaming:
                fields = ['is_streaming = 1']
                values = []
                for field in ('live_video_id', 'stream_url', 'secure_stream_url', 'restarts'):
                    if field in kwargs:
                        fields.append(f'{field} = ?')
                        values.append(kwargs[field])

                if new_session:
                    fields.append('start_time = ?')
                    values.append(datetime.now().isoformat())

                conn.execute(f"UPDATE stream_status SET {', '.join(fields)} WHERE id = 1", values)
            else:
                conn.execute('''
                    UPDATE stream_status
                    SET is_streaming = 0,
                        live_video_id = NULL,
                        stream_url = NULL,
                        secure_stream_url = NULL,
                        start_time = NULL,
                        restarts = 0
                    WHERE id = 1
                ''')
            conn.commit()

    def get_stream_status(self):
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM stream_status WHERE id = 1')
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_schedule(self, video_ids, scheduled_time):
        with self.get_connection() as conn:
            conn.execute('INSERT INTO schedules (video_ids, scheduled_time) VALUES (?, ?)', 
                         (video_ids, scheduled_time))
            conn.commit()

    def get_schedules(self):
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM schedules ORDER BY scheduled_time ASC')
            return [dict(row) for row in cursor.fetchall()]

    def delete_schedule(self, schedule_id):
        with self.get_connection() as conn:
            conn.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
            conn.commit()

    def get_due_schedules(self):
        with self.get_connection() as conn:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                'SELECT * FROM schedules WHERE is_active = 1 AND scheduled_time <= ? AND (last_run IS NULL OR last_run < scheduled_time)', 
                (now,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def mark_schedule_run(self, schedule_id):
        with self.get_connection() as conn:
            conn.execute('UPDATE schedules SET last_run = ?, is_active = 0 WHERE id = ?', 
                         (datetime.now().isoformat(), schedule_id))
            conn.commit()
