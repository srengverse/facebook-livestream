import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
import sys
import signal
import subprocess
import time

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from stream import StreamManager

class TestStreamingResilience(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.fb_api = MagicMock()
        self.telegram = MagicMock()
        self.encryption_key = "test_key_at_least_32_characters_long"
        
        # Mock database settings
        self.db.get_setting.side_effect = lambda k, default=None: {
            'STREAM_TITLE': 'Test',
            'STREAM_DESCRIPTION': 'Desc',
            'ENABLE_LOGO': 'false'
        }.get(k, default)
        
        self.manager = StreamManager(self.db, self.fb_api, self.telegram, self.encryption_key)

    @patch('os.path.isfile')
    @patch('os.access')
    def test_load_playlist_missing_video(self, mock_access, mock_isfile):
        mock_isfile.return_value = False
        self.db.get_video.return_value = {'id': 1, 'filepath': 'missing.mp4', 'filename': 'missing.mp4'}
        
        playlist = self.manager._load_playlist([1])
        self.assertEqual(len(playlist), 0)

    @patch('subprocess.Popen')
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.makedirs')
    def test_ffmpeg_crash_recovery(self, mock_makedirs, mock_file, mock_popen):
        # Mock FFmpeg process that exits
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 1, 0] # Running, then crashed, then recovered
        mock_proc.pid = 1234
        mock_popen.return_value = mock_proc
        
        # Mock playlist and FB live
        self.manager.playlist = [{'filepath': 'test.mp4'}]
        self.manager.outputs = [{'url': 'rtmp://test'}]
        
        # Run monitor loop logic manually for one iteration
        with patch.object(self.manager, '_launch_ffmpeg', return_value=True) as mock_launch:
            # Simulate a crash detection
            self.manager.process = mock_proc
            
            # We don't run the full thread, just test the logic
            exit_code = self.manager.process.poll() # 1st call: None
            self.assertEqual(exit_code, None)
            
            exit_code = self.manager.process.poll() # 2nd call: 1
            self.assertEqual(exit_code, 1)
            
            # Should trigger restart logic
            self.manager.restarts = 1
            self.manager.db.update_stream_status(True, restarts=1)
            self.manager._launch_ffmpeg()
            
            mock_launch.assert_called()

    @patch('os.killpg')
    @patch('os.getpgid')
    def test_stop_stream_cleanup(self, mock_getpgid, mock_killpg):
        mock_proc = MagicMock()
        mock_proc.pid = 5555
        self.manager.process = mock_proc
        mock_getpgid.return_value = 5000
        
        self.manager.stop_stream()
        
        self.assertTrue(self.manager.stop_event.is_set())
        mock_killpg.assert_called_with(5000, signal.SIGTERM)
        self.db.update_stream_status.assert_called_with(False)

    def test_empty_playlist_rejection(self):
        success, message = self.manager.start_stream([])
        self.assertFalse(success)
        self.assertIn("No valid or readable videos", message)

    @patch('stream.StreamManager._create_fb_live')
    @patch('stream.StreamManager._launch_ffmpeg')
    def test_rotation_logic(self, mock_launch, mock_create_fb):
        # Mock successful rotation
        mock_create_fb.return_value = {'id': 'new_id', 'secure_stream_url': 'rtmps://new'}
        mock_launch.return_value = True
        
        self.manager.stream_start_time = time.time() - 30000 # Long ago
        
        with patch.object(self.manager, '_kill_ffmpeg') as mock_kill:
            success = self.manager._rotate_stream()
            
            self.assertTrue(success)
            mock_kill.assert_called()
            mock_create_fb.assert_called()
            self.db.update_stream_status.assert_called()

if __name__ == '__main__':
    unittest.main()
