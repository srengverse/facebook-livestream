import unittest
import os
import sys
import json
from werkzeug.security import generate_password_hash

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, validate_rtmp_destination
from config import Config

class SecurityTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['DEBUG'] = True  # Set to True for testing defaults
        self.client = app.test_client()
        
        # Set dummy admin credentials
        os.environ['ADMIN_USERNAME'] = 'admin'
        os.environ['ADMIN_PASSWORD'] = generate_password_hash('password')

    def test_login_no_plaintext_fallback(self):
        # Set plaintext password in environment
        os.environ['ADMIN_PASSWORD'] = 'password'
        
        # Reload app config would be hard, but we can test the logic in app.py directly
        # if we mock the environment. For this test, we check if login fails with plaintext.
        with app.test_request_context():
            response = self.client.post('/login', data={
                'username': 'admin',
                'password': 'password'
            })
            # Should not redirect to index, should stay on login with error
            self.assertNotEqual(response.location, '/index')
            self.assertIn(b'System configuration error', response.data)

    def test_rtmp_injection_prevention(self):
        # Test stream key injection
        insecure_key = "key; rm -rf /"
        destination, error = validate_rtmp_destination(
            "Test", "custom", "rtmp://localhost/live", insecure_key
        )
        self.assertIsNone(destination)
        self.assertIn("insecure characters", error)

        # Test URL injection
        insecure_url = "rtmp://localhost/live;[option=value]"
        destination, error = validate_rtmp_destination(
            "Test", "custom", insecure_url, "key"
        )
        self.assertIsNone(destination)
        self.assertIn("insecure characters", error)

    def test_path_traversal_prevention(self):
        # Mock a file upload with traversal in filename
        from io import BytesIO
        # Use a valid extension to pass allowed_file check
        data = {
            'video': (BytesIO(b"dummy content"), "../../../etc/passwd.mp4")
        }
        
        # Need to be logged in
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            
        response = self.client.post('/api/videos', data=data, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 200)
        res_data = json.loads(response.data)
        self.assertEqual(res_data['status'], 'success')
        # The filename should be sanitized, not have ../
        self.assertNotIn('..', res_data['filename'])
        self.assertEqual(res_data['filename'], 'etc_passwd.mp4')

    def test_production_secrets_requirement(self):
        # Set debug to False to simulate production
        app.debug = False
        Config.SECRET_KEY = None
        
        with self.assertRaises(RuntimeError):
            Config.init_app(app)
        
        # Restore for other tests
        app.debug = True

if __name__ == '__main__':
    unittest.main()
