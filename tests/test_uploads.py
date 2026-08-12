import unittest
import os
import sys
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from database import Database

class UploadTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['UPLOAD_FOLDER'] = 'test_uploads'
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        
        self.client = app.test_client()
        self.db_path = 'test_uploads.db'
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        
        # Use a fresh DB for each test
        self.db = Database(self.db_path)
        # Monkey patch the app's db
        import app as flask_app
        flask_app.db = self.db
        
        # Login
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

    def tearDown(self):
        import shutil
        if os.path.exists(app.config['UPLOAD_FOLDER']):
            shutil.rmtree(app.config['UPLOAD_FOLDER'])
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    @patch('app.is_valid_video')
    @patch('app.has_sufficient_space')
    def test_valid_mp4_upload(self, mock_space, mock_valid):
        mock_space.return_value = True
        mock_valid.return_value = (True, {
            'format': {'duration': '10.5', 'bit_rate': '1000'},
            'streams': [{'codec_type': 'video', 'width': 1280, 'height': 720}]
        })
        
        data = {'video': (BytesIO(b"fake video content"), "test.mp4")}
        response = self.client.post('/api/videos', data=data, content_type='multipart/form-data')
        
        self.assertEqual(response.status_code, 200)
        res_data = json.loads(response.data)
        self.assertEqual(res_data['status'], 'success')
        
        # Verify DB
        videos = self.db.get_videos()
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]['filename'], 'test.mp4')
        self.assertEqual(videos[0]['resolution'], '1280x720')

    def test_invalid_extension(self):
        data = {'video': (BytesIO(b"fake content"), "test.exe")}
        response = self.client.post('/api/videos', data=data, content_type='multipart/form-data')
        
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"File type not allowed", response.data)

    @patch('app.is_valid_video')
    @patch('app.has_sufficient_space')
    def test_path_traversal_prevention(self, mock_space, mock_valid):
        mock_space.return_value = True
        mock_valid.return_value = (True, {'format': {}, 'streams': []})
        
        data = {'video': (BytesIO(b"fake content"), "../../../etc/passwd.mp4")}
        response = self.client.post('/api/videos', data=data, content_type='multipart/form-data')
        
        # Should sanitize to etc_passwd.mp4
        self.assertEqual(response.status_code, 200)
        res_data = json.loads(response.data)
        self.assertEqual(res_data['filename'], 'etc_passwd.mp4')

    @patch('app.is_valid_video')
    @patch('app.has_sufficient_space')
    def test_oversized_upload(self, mock_space, mock_valid):
        # The 500MB limit is enforced by Flask config MAX_CONTENT_LENGTH
        # We can test our manual space check though
        mock_space.return_value = False
        
        data = {'video': (BytesIO(b"fake content"), "large.mp4")}
        response = self.client.post('/api/videos', data=data, content_type='multipart/form-data')
        
        self.assertEqual(response.status_code, 507)
        self.assertIn(b"Insufficient disk space", response.data)

    @patch('app.is_valid_video')
    @patch('app.has_sufficient_space')
    def test_corrupted_file(self, mock_space, mock_valid):
        mock_space.return_value = True
        mock_valid.return_value = (False, "Invalid or corrupted video file")
        
        data = {'video': (BytesIO(b"corrupted content"), "bad.mp4")}
        response = self.client.post('/api/videos', data=data, content_type='multipart/form-data')
        
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Invalid or corrupted video file", response.data)
        
        # Verify no file remains
        files = os.listdir(app.config['UPLOAD_FOLDER'])
        self.assertEqual(len(files), 0)

    @patch('app.is_valid_video')
    @patch('app.has_sufficient_space')
    def test_db_failure_cleanup(self, mock_space, mock_valid):
        mock_space.return_value = True
        mock_valid.return_value = (True, {'format': {}, 'streams': []})
        
        # Mock DB failure
        with patch.object(self.db, 'add_video', side_effect=Exception("DB Down")):
            data = {'video': (BytesIO(b"content"), "db_fail.mp4")}
            response = self.client.post('/api/videos', data=data, content_type='multipart/form-data')
            
            self.assertEqual(response.status_code, 500)
            # File should be deleted
            files = os.listdir(app.config['UPLOAD_FOLDER'])
            self.assertEqual(len(files), 0)

if __name__ == '__main__':
    unittest.main()
