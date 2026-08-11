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
                return False, "Failed to create Facebook Live video"

            facebook_url = live_info.get("secure_stream_url") or live_info.get("stream_url")
            if not facebook_url:
                self._safe_end_live(live_info.get("id"))
                return False, "Facebook did not return a stream URL"

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
                # URLs contain stream credentials and are intentionally not persisted.
                stream_url=None,
                secure_stream_url=None,
                restarts=0,
            )
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
            status = self.db.get_stream_status() or {}
            was_active = self.is_running() or bool(status.get("is_streaming"))
            self.stop_event.set()
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

        # A server restart cannot recover an FFmpeg child; do not show a stale live state.
        if status.get("is_streaming") and not running:
            self.db.log("WARNING", "Cleared stale stream status because no FFmpeg process is running")
            self.db.update_stream_status(False)
            status = self.db.get_stream_status() or status

        status["stream_url"] = None
        status["secure_stream_url"] = None
        status["destinations"] = self.destination_status

        if status.get("is_streaming") and running:
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
                self.db.log("WARNING", f"Requested video does not exist: {video_id}")
                continue
            if not os.path.isfile(video["filepath"]) or not os.access(video["filepath"], os.R_OK):
                self.db.log("WARNING", f"Video file missing or unreadable: {video['filename']}")
                continue
            playlist.append(video)
        return playlist

    def _generate_playlist_file(self):
        """Create an FFmpeg concat-demuxer playlist without shell interpolation."""
        try:
            os.makedirs(os.path.dirname(self.playlist_file), exist_ok=True)
            with open(self.playlist_file, "w", encoding="utf-8") as playlist_file:
                for video in self.playlist:
                    # FFmpeg concat format requires a quoted, escaped absolute path.
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
        except Exception as exc:  # API module already records HTTP failures.
            self.db.log("ERROR", f"Failed to create Facebook Live video: {exc}")
            return None

    def _build_outputs(self, facebook_url):
        """Build safe, in-memory-only output destinations for the FFmpeg tee muxer."""
        outputs = [{
            "id": "facebook",
            "name": "Facebook Page",
            "platform": "facebook",
            "url": facebook_url,
        }]
        statuses = [{
            "id": "facebook",
            "name": "Facebook Page",
            "platform": "facebook",
            "status": "connecting",
            "url": redact_url(facebook_url),
        }]

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
                outputs.append({
                    "id": destination["id"],
                    "name": destination["name"],
                    "platform": destination["platform"],
                    "url": url,
                })
                statuses.append({
                    "id": destination["id"],
                    "name": destination["name"],
                    "platform": destination["platform"],
                    "status": "connecting",
                    "url": redact_url(destination["rtmp_url"]),
                })
            except ValueError:
                self.db.log("ERROR", f"Destination could not be decrypted: {destination['name']}")

        self.destination_status = statuses
        return outputs

    @staticmethod
    def _escape_tee_url(url):
        """Escape tee-muxer separators without exposing URLs to a shell."""
        return url.replace("\\", "\\\\").replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")

    def _build_tee_outputs(self):
        # onfail=ignore keeps remaining outputs alive if a destination fails.
        # FIFO recovery is configured globally on the tee muxer command.
        return "|".join(
            f"[f=flv:onfail=ignore]{self._escape_tee_url(item['url'])}"
            for item in self.outputs
        )

    def _launch_ffmpeg(self):
        """Launch one encoder which fans out to every destination through FFmpeg tee."""
        if not self.outputs:
            return False

        enable_logo = self.db.get_setting("ENABLE_LOGO", "false") == "true"
        logo_path = self.db.get_setting("LOGO_PATH")
        logo_position = self.db.get_setting("LOGO_POSITION", "top-right")

        command = [
            "ffmpeg", "-hide_banner", "-nostdin", "-re",
            "-stream_loop", "-1", "-f", "concat", "-safe", "0",
            "-fflags", "+genpts", "-avoid_negative_ts", "make_zero",
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

        # Re-encode one time to guarantee an H.264/AAC stream compatible with
        # Facebook, YouTube, and standard RTMP endpoints. The tee muxer then copies
        # that encoded packet stream to all destinations without duplicate encoding.
        command.extend([
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-b:v", "3000k",
            "-maxrate", "3000k", "-bufsize", "6000k", "-g", "60",
            "-keyint_min", "60", "-sc_threshold", "0", "-c:a", "aac",
            "-b:a", "128k", "-ar", "44100", "-ac", "2", "-f", "tee",
            # Each output has an independent FIFO queue and retries failures.
            "-use_fifo", "1",
            "-fifo_options", (
                "attempt_recovery=1:max_recovery_attempts=0:recovery_wait_time=5:"
                "recover_any_error=1:drop_pkts_on_overflow=1"
            ),
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
            for destination in self.destination_status:
                destination["status"] = "streaming"
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            self.db.log("ERROR", f"FFmpeg launch error: {exc}")
            self.process = None
            return False

    def _kill_ffmpeg(self):
        process = self.process
        self.process = None
        if not process or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _safe_end_live(self, live_video_id):
        if not live_video_id:
            return
        try:
            if not self.fb_api.end_live_video(live_video_id):
                self.db.log("WARNING", "Facebook Live session did not confirm a clean close")
        except Exception as exc:
            self.db.log("ERROR", f"Failed to end Facebook Live video: {exc}")

    def _rotate_stream(self):
        """Create a fresh Facebook Live session before its maximum duration expires."""
        self.db.log("INFO", "Rotating Facebook Live session before the duration limit")
        previous_status = self.db.get_stream_status() or {}
        self._kill_ffmpeg()
        self._safe_end_live(previous_status.get("live_video_id"))

        live_info = self._create_fb_live()
        if not live_info:
            self.db.update_stream_status(False)
            return False

        facebook_url = live_info.get("secure_stream_url") or live_info.get("stream_url")
        if not facebook_url:
            self._safe_end_live(live_info.get("id"))
            self.db.update_stream_status(False)
            return False

        self.outputs = self._build_outputs(facebook_url)
        if not self._launch_ffmpeg():
            self._safe_end_live(live_info.get("id"))
            self.db.update_stream_status(False)
            return False

        self.stream_start_time = time.time()
        self.session_count += 1
        self.restarts = 0
        self.db.update_stream_status(
            True,
            new_session=True,
            live_video_id=live_info.get("id"),
            stream_url=None,
            secure_stream_url=None,
            restarts=0,
        )
        if self.telegram:
            self.telegram.notify_stream_rotated(self.session_count)
        return True

    def _monitor_stream(self):
        backoff = INITIAL_RESTART_BACKOFF_SECONDS
        while not self.stop_event.wait(5):
            if self.stream_start_time and time.time() - self.stream_start_time >= ROTATE_INTERVAL_SECONDS:
                if not self._rotate_stream():
                    self.stop_stream()
                    break
                backoff = INITIAL_RESTART_BACKOFF_SECONDS
                continue

            if not self.process:
                continue
            exit_code = self.process.poll()
            if exit_code is None:
                backoff = INITIAL_RESTART_BACKOFF_SECONDS
                continue

            self.restarts += 1
            for destination in self.destination_status:
                destination["status"] = "recovering"
            self.db.log("WARNING", f"FFmpeg stopped (exit {exit_code}); recovery attempt {self.restarts}")

            if self.restarts > MAX_RESTARTS:
                self.db.log("ERROR", "Maximum FFmpeg recovery attempts exceeded; stopping stream")
                self.stop_stream()
                break

            self.db.update_stream_status(True, restarts=self.restarts)
            if self.telegram:
                self.telegram.notify_stream_crashed(self.restarts)

            if self.stop_event.wait(backoff):
                break
            backoff = min(backoff * 2, MAX_RESTART_BACKOFF_SECONDS)

            with self._lock:
                if self.stop_event.is_set():
                    break
                if not self._launch_ffmpeg():
                    self.db.log("ERROR", "FFmpeg recovery launch failed")
                    continue

            self.db.log("INFO", f"FFmpeg recovered after restart attempt {self.restarts}")
