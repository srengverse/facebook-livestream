import os
import tempfile
import unittest

from database import Database
from security_utils import SecretCipher, mask_secret, redact_url
from stream import StreamManager


TEST_ENCRYPTION_KEY = "test-encryption-key-which-is-longer-than-thirty-two-characters"


class DummyFacebookAPI:
    def create_live_video(self, **kwargs):
        return None

    def end_live_video(self, live_video_id):
        return True


class TestMultiPlatformStreaming(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.db = Database(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_stream_key_is_encrypted_and_destination_can_be_updated(self):
        cipher = SecretCipher(TEST_ENCRYPTION_KEY)
        encrypted = cipher.encrypt("youtube-secret-stream-key")
        destination_id = self.db.add_destination(
            "Primary YouTube",
            "youtube",
            "rtmp://a.rtmp.youtube.com/live2",
            encrypted,
        )

        stored = self.db.get_destination(destination_id)
        self.assertNotIn("youtube-secret-stream-key", stored["stream_key_encrypted"])
        self.assertEqual(cipher.decrypt(stored["stream_key_encrypted"]), "youtube-secret-stream-key")
        self.assertTrue(bool(stored["enabled"]))

        self.assertTrue(self.db.update_destination(destination_id, enabled=False))
        self.assertFalse(bool(self.db.get_destination(destination_id)["enabled"]))

    def test_tee_outputs_use_independent_failure_tolerance(self):
        manager = StreamManager(self.db, DummyFacebookAPI(), encryption_key=TEST_ENCRYPTION_KEY)
        manager.outputs = [
            {"id": "facebook", "name": "Facebook", "platform": "facebook", "url": "rtmps://facebook.example/live/key"},
            {"id": 1, "name": "YouTube", "platform": "youtube", "url": "rtmp://youtube.example/live/key"},
        ]

        tee_outputs = manager._build_tee_outputs()
        self.assertIn("[f=flv:onfail=ignore]rtmps://facebook.example/live/key", tee_outputs)
        self.assertIn("[f=flv:onfail=ignore]rtmp://youtube.example/live/key", tee_outputs)
        self.assertEqual(tee_outputs.count("onfail=ignore"), 2)

    def test_secret_redaction_helpers(self):
        self.assertEqual(mask_secret("secret-value"), "••••••••••••alue")
        self.assertEqual(redact_url("rtmps://host/live/key?signature=secret"), "rtmps://host/live/key")
        self.assertNotIn("secret", redact_url("rtmps://host/live/key?signature=secret"))


if __name__ == "__main__":
    unittest.main()
