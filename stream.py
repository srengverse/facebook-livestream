import subprocess
import threading
import time
import os
import signal
import psutil

# Rotate the Facebook Live session every 7h50m to stay under the 8-hour limit.
# Facebook ends broadcasts automatically at 8 hours, so we rotate 10 minutes early.
ROTATE_INTERVAL_SECONDS = 7 * 3600 + 50 * 60  # 28,200 seconds


class StreamManager:
    def __init__(self, db, fb_api):
        self.db = db
        self.fb_api = fb_api
        self.process = None
        self.current_video = None
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.restarts = 0
        self.stream_start_time = None  # tracks when the current FB live session started

    def start_stream(self, video_id):
        if self.process and self.process.poll() is None:
            return False, "Stream is already running"

        # Get video info
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM videos WHERE id = ?', (video_id,))
            video = cursor.fetchone()
            if not video:
                return False, "Video not found"
            self.current_video = dict(video)

        # Create Facebook Live Video
        live_info = self.fb_api.create_live_video(
            title=self.db.get_setting('STREAM_TITLE', 'Live Stream'),
            description=self.db.get_setting('STREAM_DESCRIPTION', 'Streaming...')
        )

        if not live_info:
            return False, "Failed to create Facebook Live video"

        stream_url = live_info.get('secure_stream_url')
        live_video_id = live_info.get('id')

        # Update DB status
        self.db.update_stream_status(
            True,
            live_video_id=live_video_id,
            stream_url=live_info.get('stream_url'),
            secure_stream_url=stream_url,
            restarts=0
        )
        self.restarts = 0
        self.stream_start_time = time.time()

        # Start FFmpeg
        self.stop_event.clear()
        success = self._launch_ffmpeg(self.current_video['filepath'], stream_url)

        if success:
            self.monitor_thread = threading.Thread(
                target=self._monitor_stream,
                args=(video_id,),
                daemon=True
            )
            self.monitor_thread.start()
            self.db.log('INFO', f"Started streaming: {self.current_video['filename']}")
            return True, "Stream started successfully"
        else:
            return False, "Failed to launch FFmpeg"

    def _launch_ffmpeg(self, filepath, stream_url):
        """Start FFmpeg, looping the video file indefinitely."""
        cmd = [
            'ffmpeg',
            '-re',
            '-stream_loop', '-1',
            '-i', filepath,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-f', 'flv',
            stream_url
        ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                preexec_fn=os.setsid  # allows killing the whole process group
            )
            return True
        except Exception as e:
            self.db.log('ERROR', f"FFmpeg Launch Error: {str(e)}")
            return False

    def _kill_ffmpeg(self):
        """Terminate the current FFmpeg process cleanly."""
        if self.process:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def _rotate_stream(self):
        """
        End the current Facebook Live session and start a fresh one.
        Called automatically every ROTATE_INTERVAL_SECONDS to stay under the 8-hour limit.
        """
        self.db.log('INFO', "Rotating Facebook Live session (approaching 8-hour limit)...")

        # 1. End the old Facebook live video
        status = self.db.get_stream_status()
        if status and status.get('live_video_id'):
            self.fb_api.end_live_video(status['live_video_id'])

        # 2. Kill the current FFmpeg process
        self._kill_ffmpeg()

        # 3. Create a new Facebook Live video
        live_info = self.fb_api.create_live_video(
            title=self.db.get_setting('STREAM_TITLE', 'Live Stream'),
            description=self.db.get_setting('STREAM_DESCRIPTION', 'Streaming...')
        )

        if not live_info:
            self.db.log('ERROR', "Stream rotation failed: could not create a new Facebook Live video. Stopping.")
            self.db.update_stream_status(False)
            return False

        stream_url = live_info.get('secure_stream_url')
        live_video_id = live_info.get('id')

        # 4. Update DB with new session info
        self.db.update_stream_status(
            True,
            live_video_id=live_video_id,
            stream_url=live_info.get('stream_url'),
            secure_stream_url=stream_url,
            restarts=0
        )
        self.restarts = 0
        self.stream_start_time = time.time()

        # 5. Restart FFmpeg with the new RTMPS URL
        success = self._launch_ffmpeg(self.current_video['filepath'], stream_url)
        if success:
            self.db.log('INFO', "Stream rotated successfully — new Facebook Live session started.")
        else:
            self.db.log('ERROR', "Stream rotation failed: could not relaunch FFmpeg. Stopping.")
            self.db.update_stream_status(False)

        return success

    def _monitor_stream(self, video_id):
        """
        Background thread that:
          - Restarts FFmpeg if it crashes unexpectedly.
          - Rotates the Facebook Live session before the 8-hour Facebook limit.
        """
        while not self.stop_event.is_set():
            # --- Check for 8-hour rotation ---
            if self.stream_start_time is not None:
                elapsed = time.time() - self.stream_start_time
                if elapsed >= ROTATE_INTERVAL_SECONDS:
                    success = self._rotate_stream()
                    if not success:
                        self.stop_event.set()
                        break
                    # After rotation the process is fresh; continue monitoring
                    time.sleep(10)
                    continue

            # --- Check if FFmpeg crashed ---
            if self.process and self.process.poll() is not None:
                self.restarts += 1
                self.db.log('WARNING', f"FFmpeg process died. Restarting... (Attempt {self.restarts})")
                self.db.update_stream_status(True, restarts=1)

                # Reuse the current stream URL from DB
                status = self.db.get_stream_status()
                current_url = status.get('secure_stream_url') if status else None

                if current_url and self._launch_ffmpeg(self.current_video['filepath'], current_url):
                    self.db.log('INFO', f"FFmpeg restarted (attempt {self.restarts})")
                else:
                    self.db.log('ERROR', "Failed to restart FFmpeg. Stopping stream.")
                    self.stop_stream()
                    break

            time.sleep(10)

    def stop_stream(self):
        self.stop_event.set()

        status = self.db.get_stream_status()
        if status and status.get('live_video_id'):
            self.fb_api.end_live_video(status['live_video_id'])

        self._kill_ffmpeg()

        self.db.update_stream_status(False)
        self.stream_start_time = None
        self.db.log('INFO', "Stream stopped")
        return True, "Stream stopped"

    def get_status(self):
        status = self.db.get_stream_status()
        if status and status['is_streaming'] and self.process:
            try:
                p = psutil.Process(self.process.pid)
                status['cpu'] = p.cpu_percent()
                status['memory'] = p.memory_info().rss / (1024 * 1024)
            except Exception:
                status['cpu'] = 0
                status['memory'] = 0

            # Include elapsed seconds so the UI can show how long the current session has run
            if self.stream_start_time:
                status['session_elapsed'] = int(time.time() - self.stream_start_time)
                status['rotate_in'] = max(0, ROTATE_INTERVAL_SECONDS - status['session_elapsed'])
            else:
                status['session_elapsed'] = 0
                status['rotate_in'] = ROTATE_INTERVAL_SECONDS

        return status
