import unittest
from unittest.mock import MagicMock, patch
import time
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from telegram_notifier import TelegramNotifier

class TestNotifications(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.get_setting.side_effect = lambda k, default=None: {
            'TELEGRAM_BOT_TOKEN': '123456:ABC-DEF',
            'TELEGRAM_CHAT_ID': '987654321'
        }.get(k, default)
        self.notifier = TelegramNotifier(self.db)

    @patch('requests.post')
    def test_send_success(self, mock_post):
        mock_post.return_value.status_code = 200
        self.notifier._send("Hello Test")
        mock_post.assert_called_once()

    @patch('requests.post')
    def test_cooldown_logic(self, mock_post):
        mock_post.return_value.status_code = 200
        
        # Set short cooldown for testing
        self.notifier.cooldown_period = 1
        
        # First call should send
        self.notifier.notify_stream_crashed(1)
        self.assertEqual(mock_post.call_count, 1)
        
        # Immediate second call should NOT send (cooldown)
        self.notifier.notify_stream_crashed(1)
        self.assertEqual(mock_post.call_count, 1)
        
        # Wait for cooldown to expire
        time.sleep(1.1)
        
        # Third call should send
        self.notifier.notify_stream_crashed(1)
        self.assertEqual(mock_post.call_count, 2)

    @patch('requests.post')
    def test_different_cooldown_keys(self, mock_post):
        mock_post.return_value.status_code = 200
        self.notifier.cooldown_period = 60
        
        # Send two different alerts
        self.notifier.notify_destination_failure("YouTube", "youtube")
        self.notifier.notify_destination_failure("Twitch", "custom")
        
        # Both should be sent because they have different keys
        self.assertEqual(mock_post.call_count, 2)

    @patch('requests.post')
    def test_missing_credentials(self, mock_post):
        # Mock missing settings
        self.db.get_setting.side_effect = lambda k, default=None: None
        
        self.notifier.notify_stream_started("test.mp4")
        mock_post.assert_not_called()

    @patch('requests.post')
    def test_facebook_error_cooldown(self, mock_post):
        mock_post.return_value.status_code = 200
        self.notifier.cooldown_period = 60
        
        # First error
        self.notifier.notify_facebook_error("AUTH_ERROR: Token expired")
        self.assertEqual(mock_post.call_count, 1)
        
        # Same type of error (AUTH_ERROR) should be throttled
        self.notifier.notify_facebook_error("AUTH_ERROR: Another token issue")
        self.assertEqual(mock_post.call_count, 1)
        
        # Different type should be sent
        self.notifier.notify_facebook_error("PERMISSION_ERROR: No access")
        self.assertEqual(mock_post.call_count, 2)

if __name__ == '__main__':
    unittest.main()
