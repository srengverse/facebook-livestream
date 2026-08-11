import os
import tempfile
import unittest

# Must be defined before importing the application configuration.
os.environ.setdefault("SECRET_KEY", "test-flask-secret-key-that-is-longer-than-thirty-two-characters")
os.environ.setdefault(
    "DESTINATION_ENCRYPTION_KEY",
    "test-destination-encryption-key-that-is-longer-than-thirty-two-characters",
)

import app as webapp
from database import Database


class TestDestinationAPI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db = webapp.db
        self.original_stream_db = webapp.stream_manager.db
        webapp.db = Database(os.path.join(self.temp_dir.name, "api-test.db"))
        webapp.stream_manager.db = webapp.db
        webapp.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = webapp.app.test_client()
        with self.client.session_transaction() as session:
            session["logged_in"] = True

    def tearDown(self):
        webapp.db = self.original_db
        webapp.stream_manager.db = self.original_stream_db
        self.temp_dir.cleanup()

    def test_destination_lifecycle_never_returns_stream_key(self):
        payload = {
            "name": "YouTube Primary",
            "platform": "youtube",
            "rtmp_url": "rtmp://a.rtmp.youtube.com/live2",
            "stream_key": "sensitive-youtube-stream-key",
            "enabled": True,
        }
        response = self.client.post("/api/destinations", json=payload)
        self.assertEqual(response.status_code, 201)

        response = self.client.get("/api/destinations")
        self.assertEqual(response.status_code, 200)
        destination = response.get_json()[0]
        self.assertEqual(destination["name"], "YouTube Primary")
        self.assertTrue(destination["stream_key_configured"])
        self.assertNotIn("stream_key", destination)
        self.assertNotIn("sensitive-youtube-stream-key", response.get_data(as_text=True))

        response = self.client.put(
            f"/api/destinations/{destination['id']}", json={"enabled": False}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(webapp.db.get_destination(destination["id"])["enabled"])

    def test_destination_rejects_invalid_rtmp_url(self):
        response = self.client.post(
            "/api/destinations",
            json={
                "name": "Invalid Target",
                "platform": "custom",
                "rtmp_url": "https://not-an-rtmp-endpoint.example/live",
                "stream_key": "stream-key",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("rtmp://", response.get_json()["message"])

    def test_settings_page_contains_destination_controls_and_csrf_token(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Multi-platform Destinations", html)
        self.assertIn('id="destination-form"', html)
        self.assertIn('name="csrf-token"', html)


if __name__ == "__main__":
    unittest.main()
