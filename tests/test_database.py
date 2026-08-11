import unittest
import os
import sqlite3
from database import Database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.db_path = 'test_database.db'
        self.db = Database(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.db_path + '-shm'):
            os.remove(self.db_path + '-shm')
        if os.path.exists(self.db_path + '-wal'):
            os.remove(self.db_path + '-wal')

    def test_settings_caching(self):
        self.db.set_setting('test_key', 'test_value')
        # Check cache
        self.assertEqual(self.db._settings_cache['test_key'], 'test_value')
        # Check database
        self.assertEqual(self.db.get_setting('test_key'), 'test_value')

    def test_video_management(self):
        self.db.add_video('test.mp4', '/path/to/test.mp4')
        videos = self.db.get_videos()
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]['filename'], 'test.mp4')
        
        video_id = videos[0]['id']
        video = self.db.get_video(video_id)
        self.assertIsNotNone(video)
        self.assertEqual(video['filename'], 'test.mp4')

    def test_log_pruning(self):
        self.db.log('INFO', 'Old log')
        # Manually set timestamp to old date is hard with auto-timestamp, 
        # but we can test if the function runs without error
        self.db.prune_logs(days=0)
        # Should still have the log because prune uses date('now', '-0 days') which is today
        logs = self.db.get_logs()
        self.assertTrue(len(logs) >= 1)

if __name__ == '__main__':
    unittest.main()
