"""FFmpeg lifecycle management for reliable Facebook and multi-platform broadcasts."""

import logging
import os
import signal
import subprocess
import threading
import time
import psutil
from security_utils import SecretCipher, redact_url

# Rotate before Facebook's eight-hour Live session limit.
ROTATE_INTERVAL_SECONDS = 7 * 3600 + 50 * 60
MAX_RESTARTS = 10
INITIAL_RESTART_BACKOFF_SECONDS = 5
MAX_RESTART_BACKOFF_SECONDS = 300
PID_FILE = os.path.join("logs", "ffmpeg.pid")

class StreamManager:
    """Manage one FFmpeg encoder and distribute its output to multiple RTMP targets."""

    def __init__(self, db, fb_api, telegram=None, encryption_key=None):
        self.db = db
        self.fb_api = fb_api
        self.telegram = telegram
        self.encryption_key = encryption_key
        self.process = None
        self.playlist = []
        self.outputs = []
        self.destination_status = []
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.restarts = 0
        self.stream_start_time = None
        self.session_count = 0
        self.logger = logging.getLogger("StreamManager")
        self.playlist_file = os.path.join("uploads", "playlist.txt")
        self._lock = threading.RLock()
        
        # Cleanup any orphan FFmpeg process on startup
        self._cleanup_orphans()

    def _cleanup_orphans(self):
        """Find and kill any FFmpeg processes left behind by a previous run."""
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, "r") as f:
                    old_pid = int(f.read().strip())
                if psutil.pid_exists(old_pid):
                    proc = psutil.Process(old_pid)
                    if "ffmpeg" in proc.name().lower():
                        self.logger.info(f"Cleaning up orphan FFmpeg process: {old_pid}")
                        os.killpg(os.getpgid(old_pid), signal.SIGKILL)
                os.remove(PID_FILE)
            except (ValueError, OSError, psutil.NoSuchProcess, ProcessLookupError):
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)

    def is_running(self):
        """Return True only when FFmpeg is still running."""
        with self._lock:
            return self.process is not None and self.process.poll() is None

    def start_stream(self, video_ids):
        """Start a Facebook broadcast and fan a single encode out to all enabled targets."""
        with self._lock:
            if self.is_running():
                return False, "Stream is already running"

            self.playlist = self._load_playlist(video_ids)
            if not self.playlist:
                return False, "No valid or readable videos found"
            if not self._generate_playlist_file():
                return False, "Could not create the FFmpeg playlist"

            live_info = self._create_fb_live()
            if not live_info:
                return False, "Failed to create Facebook Live video. Check logs for API errors."

            facebook_url = live_info.get("secure_stream_url") or live_info.get("stream_url")
            if not facebook_url:
                self._safe_end_live(live_info.get("id"))
                return False, "Facebook did not return a valid stream URL."

            self.outputs = self._build_outputs(facebook_url)
            if not self.outputs:
                self._safe_end_live(live_info.get("id"))
                return False, "No valid streaming outputs are available"

            self.stop_event.clear()
            self.restarts = 0
            if not self._launch_ffmpeg():
                self._safe_end_live(live_info.get("id"))
                self.db.update_stream_status(False)
                return False, "Failed to launch FFmpeg"

            self.stream_start_time = time.time()
            self.session_count += 1
            self.db.update_stream_status(
                True,
                new_session=True,
                live_video_id=live_info.get("id"),
                stream_url=None,
                secure_stream_url=None,
                restarts=0,
            )
            
            # Start monitoring in a new thread
            if self.monitor_thread and self.monitor_thread.is_alive():
                pass # Already running
            else:
                self.monitor_thread = threading.Thread(target=self._monitor_stream, daemon=True)
                self.monitor_thread.start()

            self.db.log(
                "INFO",
                f"Started multi-platform stream with {len(self.playlist)} videos and "
                f"{len(self.outputs)} destination(s)",
            )
            if self.telegram:
                self.telegram.notify_stream_started(
                    f"{len(self.playlist)} video(s) to {len(self.outputs)} destination(s)"
                )
            return True, "Stream started successfully"

    def stop_stream(self):
        """Stop FFmpeg and close the current Facebook Live session safely."""
        with self._lock:
            self.stop_event.set()
            status = self.db.get_stream_status() or {}
            was_active = self.is_running() or bool(status.get("is_streaming"))
            
            self._kill_ffmpeg()
            self._safe_end_live(status.get("live_video_id"))
            self.db.update_stream_status(False)
            
            self.stream_start_time = None
            self.outputs = []
            self.destination_status = []
            self.restarts = 0

            if was_active:
                self.db.log("INFO", "Stream stopped")
                if self.telegram:
                    self.telegram.notify_stream_stopped()
            return True, "Stream stopped"

    def get_status(self):
        """Return safe status data; never expose stream keys or full RTMP URLs."""
        status = self.db.get_stream_status() or {"id": 1, "is_streaming": 0}
        running = self.is_running()

        if status.get("is_streaming") and not running:
            # Check if we are in recovery backoff
            if self.restarts > 0 and self.restarts <= MAX_RESTARTS and not self.stop_event.is_set():
                status["status_text"] = "RECOVERING"
            else:
                self.db.log("WARNING", "Cleared stale stream status")
                self.db.update_stream_status(False)
                status = self.db.get_stream_status() or status
                status["status_text"] = "OFFLINE"
        elif running:
            status["status_text"] = "LIVE"
        else:
            status["status_text"] = "OFFLINE"

        status["stream_url"] = None
        status["secure_stream_url"] = None
        status["destinations"] = self.destination_status

        if running:
            try:
                process = psutil.Process(self.process.pid)
                status["cpu"] = process.cpu_percent(interval=None)
                status["memory"] = round(process.memory_info().rss / (1024 * 1024), 2)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                status["cpu"] = 0
                status["memory"] = 0

            if self.stream_start_time:
                elapsed = int(time.time() - self.stream_start_time)
                status["session_elapsed"] = elapsed
                status["rotate_in"] = max(0, ROTATE_INTERVAL_SECONDS - elapsed)

            status["playlist_total"] = len(self.playlist)
            status["current_video_name"] = "Seamless Multi-platform Playlist Loop"
            
        return status

    def _load_playlist(self, video_ids):
        playlist = []
        seen_ids = set()
        for video_id in video_ids:
            if not isinstance(video_id, int) or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            video = self.db.get_video(video_id)
            if not video:
                continue
            if not os.path.isfile(video["filepath"]) or not os.access(video["filepath"], os.R_OK):
                continue
            playlist.append(video)
        return playlist

    def _generate_playlist_file(self):
        try:
            os.makedirs(os.path.dirname(self.playlist_file), exist_ok=True)
            with open(self.playlist_file, "w", encoding="utf-8") as playlist_file:
                for video in self.playlist:
                    path = os.path.abspath(video["filepath"]).replace("'", "'\\\\''")
                    playlist_file.write(f"file '{path}'\n")
            return True
        except OSError as exc:
            self.db.log("ERROR", f"Failed to generate FFmpeg playlist: {exc}")
            return False

    def _create_fb_live(self):
        try:
            return self.fb_api.create_live_video(
                title=self.db.get_setting("STREAM_TITLE", "Live Stream"),
                description=self.db.get_setting("STREAM_DESCRIPTION", "Streaming..."),
            )
        except Exception as exc:
            self.db.log("ERROR", f"Failed to create Facebook Live video: {exc}")
            return None

    def _build_outputs(self, facebook_url):
        outputs = [{"id": "facebook", "name": "Facebook Page", "platform": "facebook", "url": facebook_url}]
        statuses = [{"id": "facebook", "name": "Facebook Page", "platform": "facebook", "status": "connecting", "url": redact_url(facebook_url)}]

        encrypted_destinations = self.db.get_destinations(enabled_only=True)
        if not encrypted_destinations:
            self.destination_status = statuses
            return outputs

        try:
            cipher = SecretCipher(self.encryption_key)
        except ValueError as exc:
            self.db.log("ERROR", f"Multi-platform destinations disabled: {exc}")
            self.destination_status = statuses
            return outputs

        for destination in encrypted_destinations:
            try:
                stream_key = cipher.decrypt(destination["stream_key_encrypted"])
                url = f"{destination['rtmp_url'].rstrip('/')}/{stream_key.lstrip('/')}"
                outputs.append({"id": destination["id"], "name": destination["name"], "platform": destination["platform"], "url": url})
                statuses.append({"id": destination["id"], "name": destination["name"], "platform": destination["platform"], "status": "connecting", "url": redact_url(destination["rtmp_url"])})
            except Exception:
                self.db.log("ERROR", f"Destination decryption failed: {destination['name']}")

        self.destination_status = statuses
        return outputs

    @staticmethod
    def _escape_tee_url(url):
        return url.replace("\\", "\\\\").replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")

    def _build_tee_outputs(self):
        return "|".join(f"[f=flv:onfail=ignore]{self._escape_tee_url(item['url'])}" for item in self.outputs)

    def _launch_ffmpeg(self):
        with self._lock:
            if not self.outputs:
                return False

            enable_logo = self.db.get_setting("ENABLE_LOGO", "false") == "true"
            logo_path = self.db.get_setting("LOGO_PATH")
            logo_position = self.db.get_setting("LOGO_POSITION", "top-right")

            command = [
                "ffmpeg", "-hide_banner", "-nostdin", "-re",
                "-stream_loop", "-1", "-f", "concat", "-safe", "0",
                "-fflags", "+genpts+igndts", "-avoid_negative_ts", "make_zero",
                "-i", self.playlist_file,
            ]

            if enable_logo and logo_path and os.path.isfile(logo_path):
                position_map = {
                    "top-left": "10:10",
                    "top-right": "main_w-overlay_w-10:10",
                    "bottom-left": "10:main_h-overlay_h-10",
                    "bottom-right": "main_w-overlay_w-10:main_h-overlay_h-10",
                }
                position = position_map.get(logo_position, position_map["top-right"])
                command.extend([
                    "-loop", "1", "-i", logo_path,
                    "-filter_complex", f"[1:v]scale=150:-1[logo];[0:v][logo]overlay={position}:format=auto[v]",
                    "-map", "[v]", "-map", "0:a?",
                ])
            else:
                command.extend(["-map", "0:v:0", "-map", "0:a?"])

            command.extend([
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-pix_fmt", "yuv420p", "-profile:v", "high", "-b:v", "3000k",
                "-maxrate", "3500k", "-bufsize", "7000k", "-g", "60",
                "-keyint_min", "60", "-sc_threshold", "0", "-c:a", "aac",
                "-b:a", "128k", "-ar", "44100", "-ac", "2", "-f", "tee",
                "-use_fifo", "1",
                "-fifo_options", "attempt_recovery=1:max_recovery_attempts=0:recovery_wait_time=5:recover_any_error=1:drop_pkts_on_overflow=1",
                self._build_tee_outputs(),
            ])

            try:
                os.makedirs("logs", exist_ok=True)
                with open(os.path.join("logs", "ffmpeg.log"), "a", encoding="utf-8") as log_file:
                    self.process = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=log_file,
                        stderr=log_file,
                        start_new_session=True,
                    )
                
                # Record PID
                with open(PID_FILE, "w") as f:
                    f.write(str(self.process.pid))
                
                for dest in self.destination_status:
                    dest["status"] = "streaming"
                return True
            except Exception as exc:
                self.db.log("ERROR", f"FFmpeg launch error: {exc}")
                self.process = None
                return False

    def _kill_ffmpeg(self):
        with self._lock:
            process = self.process
            self.process = None
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
            
            if not process:
                return
            
            try:
                # Terminate the whole process group
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGTERM)
                
                # Wait for termination
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

    def _safe_end_live(self, live_video_id):
        if not live_video_id:
            return
        try:
            self.fb_api.end_live_video(live_video_id)
        except Exception as exc:
            self.db.log("ERROR", f"Failed to end Facebook Live: {exc}")

    def _rotate_stream(self):
        with self._lock:
            self.db.log("INFO", "Rotating Facebook Live session")
            status = self.db.get_stream_status() or {}
            old_live_id = status.get("live_video_id")
            
            # 1. Create new live video first to minimize downtime
            live_info = self._create_fb_live()
            if not live_info:
                return False
            
            new_url = live_info.get("secure_stream_url") or live_info.get("stream_url")
            if not new_url:
                self._safe_end_live(live_info.get("id"))
                return False
            
            # 2. Stop old FFmpeg and end old session
            self._kill_ffmpeg()
            self._safe_end_live(old_live_id)
            
            # 3. Start new FFmpeg
            self.outputs = self._build_outputs(new_url)
            if not self._launch_ffmpeg():
                self._safe_end_live(live_info.get("id"))
                self.db.update_stream_status(False)
                return False
            
            self.stream_start_time = time.time()
            self.session_count += 1
            self.restarts = 0
            self.db.update_stream_status(True, new_session=True, live_video_id=live_info.get("id"))
            
            if self.telegram:
                self.telegram.notify_stream_rotated(self.session_count)
            return True

    def _monitor_stream(self):
        backoff = INITIAL_RESTART_BACKOFF_SECONDS
        while not self.stop_event.wait(5):
            # 1. Check for rotation
            if self.stream_start_time and (time.time() - self.stream_start_time) >= ROTATE_INTERVAL_SECONDS:
                if not self._rotate_stream():
                    self.db.log("ERROR", "Rotation failed, stopping stream")
                    if self.telegram:
                        self.telegram.notify_facebook_error("Rotation failed: Duration limit reached but could not create new session.")
                    self.stop_stream()
                    break
                backoff = INITIAL_RESTART_BACKOFF_SECONDS
                continue

            # 2. Check if process is still running
            with self._lock:
                if self.stop_event.is_set():
                    break
                
                if self.process is None:
                    continue
                
                exit_code = self.process.poll()
                if exit_code is None:
                    backoff = INITIAL_RESTART_BACKOFF_SECONDS
                    continue

                # Process crashed
                self.restarts += 1
                self.db.log("WARNING", f"FFmpeg exited ({exit_code}), restart {self.restarts}")
                
                if self.restarts > MAX_RESTARTS:
                    self.db.log("ERROR", "Max restarts reached")
                    if self.telegram:
                        self.telegram.notify_restart_failed(self.restarts)
                    self.stop_stream()
                    break
                
                if self.telegram:
                    self.telegram.notify_stream_crashed(self.restarts)
                
                # Update status to recovering
                for dest in self.destination_status:
                    dest["status"] = "recovering"
                self.db.update_stream_status(True, restarts=self.restarts)

            # 3. Wait before restart
            if self.stop_event.wait(backoff):
                break
            
            # 4. Attempt restart
            with self._lock:
                if self.stop_event.is_set():
                    break
                if self._launch_ffmpeg():
                    self.db.log("INFO", f"FFmpeg recovered (restart {self.restarts})")
                    backoff = INITIAL_RESTART_BACKOFF_SECONDS
                else:
                    backoff = min(backoff * 2, MAX_RESTART_BACKOFF_SECONDS)
