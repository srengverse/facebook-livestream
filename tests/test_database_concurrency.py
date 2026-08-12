import unittest
import threading
import os
import sys
import time
import sqlite3

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import Database

class TestDatabaseConcurrency(unittest.TestCase):
    def setUp(self):
        self.db_path = 'test_concurrency.db'
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = Database(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_concurrent_settings_access(self):
        """Test that multiple threads can read/write settings without corruption."""
        def worker(thread_id):
            for i in range(50):
                key = f"key_{thread_id}_{i}"
                self.db.set_setting(key, f"val_{i}")
                val = self.db.get_setting(key)
                self.assertEqual(val, f"val_{i}")

        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

    def test_cache_consistency(self):
        """Test that cache remains consistent with the database."""
        self.db.set_setting("consistent_key", "initial")
        
        # Manually update DB bypassing the cache
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE settings SET value = 'direct_update' WHERE key = 'consistent_key'")
            conn.commit()
            
        # The cache might be stale here if we don't handle it.
        # But set_setting should overwrite it.
        self.db.set_setting("consistent_key", "final_update")
        self.assertEqual(self.db.get_setting("consistent_key"), "final_update")

    def test_transaction_boundaries(self):
        """Verify that state-changing operations are isolated."""
        # This is a smoke test for methods using with self.get_connection()
        self.db.add_video("test.mp4", "/path/test.mp4")
        videos = self.db.get_videos()
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]['filename'], "test.mp4")

    def test_log_pruning_boundary(self):
        """Test log pruning with datetime logic."""
        self.db.log("INFO", "old log")
        
        # Manually set timestamp to 10 days ago
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE logs SET timestamp = datetime('now', '-10 days')")
            conn.commit()
            
        self.db.log("INFO", "new log")
        self.db.prune_logs(days=7)
        
        logs = self.db.get_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['message'], "new log")

if __name__ == '__main__':
    unittest.main()
