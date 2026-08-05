import requests


class TelegramNotifier:
    def __init__(self, db):
        self.db = db

    def _send(self, message):
        token = self.db.get_setting('TELEGRAM_BOT_TOKEN')
        chat_id = self.db.get_setting('TELEGRAM_CHAT_ID')
        if not token or not chat_id:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
                timeout=10
            )
        except Exception:
            pass

    def notify_stream_started(self, filename):
        self._send(f"🟢 <b>Stream Started</b>\n📹 {filename}")

    def notify_stream_stopped(self):
        self._send("🔴 <b>Stream Stopped</b>")

    def notify_stream_rotated(self, session_num):
        self._send(
            f"🔄 <b>Stream Rotated</b> (Session #{session_num})\n"
            "New Facebook Live session started automatically."
        )

    def notify_stream_crashed(self, attempt):
        self._send(f"⚠️ <b>FFmpeg Crashed</b> — Restarting (Attempt {attempt})")

    def notify_next_video(self, filename, index, total):
        self._send(f"▶️ <b>Next Video</b> [{index}/{total}]\n📹 {filename}")
