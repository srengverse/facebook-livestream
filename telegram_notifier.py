import requests
import time
import logging
import threading

class TelegramNotifier:
    """Handles Telegram notifications with cooldowns and reliability features."""
    
    def __init__(self, db):
        self.db = db
        self.logger = logging.getLogger("TelegramNotifier")
        self._last_sent = {}
        self._lock = threading.Lock()
        # Cooldown in seconds for repeated error messages
        self.cooldown_period = 300 

    def _should_send(self, key):
        """Check if we should send a message based on cooldown."""
        with self._lock:
            now = time.time()
            if key in self._last_sent:
                if now - self._last_sent[key] < self.cooldown_period:
                    return False
            self._last_sent[key] = now
            return True

    def _send(self, message, cooldown_key=None):
        """Internal helper to send Telegram messages safely."""
        if cooldown_key and not self._should_send(cooldown_key):
            return

        token = self.db.get_setting('TELEGRAM_BOT_TOKEN')
        chat_id = self.db.get_setting('TELEGRAM_CHAT_ID')
        
        if not token or not chat_id:
            return
            
        # Security: Basic validation of token and chat_id
        if ":" not in str(token) or not str(chat_id).replace('-', '').isdigit():
            self.logger.warning("Invalid Telegram credentials format")
            return

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
                timeout=10
            )
            if response.status_code != 200:
                self.logger.error(f"Telegram API error ({response.status_code}): {response.text}")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Telegram connection error: {e}")

    def notify_stream_started(self, details):
        self._send(f"🟢 <b>Stream Started</b>\nℹ️ {details}")

    def notify_stream_stopped(self):
        self._send("🔴 <b>Stream Stopped</b>")

    def notify_stream_rotated(self, session_num):
        self._send(
            f"🔄 <b>Stream Rotated</b> (Session #{session_num})\n"
            "New Facebook Live session started automatically."
        )

    def notify_stream_crashed(self, attempt):
        # We allow crash notifications but cooldown repeated ones
        self._send(f"⚠️ <b>FFmpeg Crashed</b> — Restarting (Attempt {attempt})", cooldown_key=f"crash_{attempt}")

    def notify_restart_failed(self, restarts):
        self._send(f"❌ <b>Restart Failed</b>\nReached {restarts} attempts. Stream stopped.", cooldown_key="restart_failed")

    def notify_facebook_error(self, error):
        # Categorize error to avoid spamming the same one
        err_type = error.split(':')[0] if ':' in error else "generic"
        self._send(f"🚫 <b>Facebook API Error</b>\n{error}", cooldown_key=f"fb_err_{err_type}")

    def notify_destination_failure(self, name, platform):
        self._send(f"📡 <b>Destination Failure</b>\nTarget: {name} ({platform})", cooldown_key=f"dest_fail_{name}")

    def notify_system_alert(self, alert_type, message):
        self._send(f"🔔 <b>System Alert: {alert_type}</b>\n{message}", cooldown_key=f"sys_alert_{alert_type}")
