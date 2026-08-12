import unittest
from unittest.mock import MagicMock, patch
import requests
import json
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from facebook_api import FacebookAPI
from config import Config

class TestFacebookAPI(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        # Mock credentials
        self.db.get_setting.side_effect = lambda k, default=None: {
            'PAGE_ACCESS_TOKEN': 'test_token',
            'PAGE_ID': '123456789'
        }.get(k, default)
        
        self.api = FacebookAPI(self.db)

    @patch('requests.request')
    def test_get_page_info_success(self, mock_request):
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'name': 'Test Page', 'fan_count': 100}
        mock_request.return_value = mock_response

        result = self.api.get_page_info()
        
        self.assertEqual(result['name'], 'Test Page')
        self.assertEqual(result['fan_count'], 100)
        mock_request.assert_called_once()

    @patch('requests.request')
    def test_create_live_video_success(self, mock_request):
        # Mock successful live video creation
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'id': 'live_123',
            'secure_stream_url': 'rtmps://live.facebook.com/123'
        }
        mock_request.return_value = mock_response

        result = self.api.create_live_video("Title", "Desc")
        
        self.assertEqual(result['id'], 'live_123')
        self.assertEqual(result['secure_stream_url'], 'rtmps://live.facebook.com/123')

    @patch('requests.request')
    def test_create_live_video_invalid_response(self, mock_request):
        # Mock response missing ID or URL
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'something': 'else'}
        mock_request.return_value = mock_response

        result = self.api.create_live_video()
        self.assertIsNone(result)
        self.db.log.assert_called_with('ERROR', "FB API Create Live: Invalid response structure")

    @patch('requests.request')
    def test_auth_error_categorization(self, mock_request):
        # Mock OAuth error (code 190)
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            'error': {
                'message': 'Invalid OAuth access token.',
                'code': 190,
                'error_subcode': 463
            }
        }
        mock_request.return_value = mock_response

        result, error = self.api._request('GET', 'me')
        self.assertIsNone(result)
        self.assertIn("AUTH_ERROR", error)

    @patch('requests.request')
    def test_retry_on_server_error(self, mock_request):
        # Mock 500 error followed by 200 success
        mock_fail = MagicMock()
        mock_fail.status_code = 500
        mock_fail.json.return_value = {'error': 'server error'}
        
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {'data': 'ok'}
        
        mock_request.side_effect = [mock_fail, mock_success]

        # Use 0 backoff for fast tests
        with patch('time.sleep'):
            result, error = self.api._request('GET', 'me', retries=1)
            
        self.assertEqual(result['data'], 'ok')
        self.assertEqual(mock_request.call_count, 2)

    @patch('requests.request')
    def test_end_live_video_idempotency(self, mock_request):
        # Mock "already ended" error
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            'error': {
                'message': 'This live video has already ended.',
                'code': 100
            }
        }
        mock_request.return_value = mock_response

        result = self.api.end_live_video('123')
        self.assertTrue(result) # Should return True for idempotency

if __name__ == '__main__':
    unittest.main()
