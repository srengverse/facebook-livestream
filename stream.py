import subprocess
import threading
import time
import os
import signal
import psutil
import logging

# Rotate the Facebook Live session every 7h50m to stay under the 8-hour limit.
ROTATE_INTERVAL_SECONDS = 7 * 3600 + 50 * 60  # 28,200 seconds

class StreamManager:
    def __init__(self, db, fb_api, telegram=None):
        self.db = db
        self.fb_api = fb_api
        self.telegram = telegram
        self.process = None
        self.playlist = []        # list of video dicts
        self.playlist_index = 0
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.restarts = 0
        self.stream_start_time = None
        self.session_count = 0    # counts FB live sessions created
        self.logger = logging.getLogger("StreamManager")

    def start_stream(self, video_ids: list):
        if self.process and self.process.poll() is None:
            return False, "Stream is already running"

        # Build playlist
        self.playlist = []
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            for vid_id in video_ids:
                cursor.execute('SELECT * FROM videos WHERE id = ?', (vid_id,))
                row = cursor.fetchone()
                if row:
                    self.playlist.append(dict(row))

        if not self.playlist:
            return False, "No valid videos found"

        self.playlist_index = 0
        live_info = self._create_fb_live()
        if not live_info:
            return False, "Failed to create Facebook Live video"

        stream_url = live_info.get('secure_stream_url')
        self.restarts = 0
        self.stop_event.clear()

        success = self._launch_ffmpeg(self.playlist[0]['filepath'], stream_url)
        if not success:
            return False, "Failed to launch FFmpeg"

        self.monitor_thread = threading.Thread(
            target=self._monitor_stream,
            args=(stream_url,),
            daemon=True
        )
        self.monitor_thread.start()

        first_video = self.playlist[0]['filename']
        self.db.log('INFO', f"Started streaming playlist ({len(self.playlist)} videos): {first_video}")
        if self.telegram:
            self.telegram.notify_stream_started(first_video)

        return True, "Stream started successfully"

    def stop_stream(self):
        self.stop_event.set()
        status = self.db.get_stream_status()
        if status and status.get('live_video_id'):
            self.fb_api.end_live_video(status['live_video_id'])

        self._kill_ffmpeg()
        self.db.update_stream_status(False)
        self.stream_start_time = None
        self.db.log('INFO', "Stream stopped")

        if self.telegram:
            self.telegram.notify_stream_stopped()

        return True, "Stream stopped"

    def get_status(self):
        status = self.db.get_stream_status()
        if status and status['is_streaming'] and self.process:
            try:
                p = psutil.Process(self.process.pid)
                status['cpu'] = p.cpu_percent()
                status['memory'] = p.memory_info().rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                status['cpu'] = 0
                status['memory'] = 0

            if self.stream_start_time:
                elapsed = int(time.time() - self.stream_start_time)
                status['session_elapsed'] = elapsed
                status['rotate_in'] = max(0, ROTATE_INTERVAL_SECONDS - elapsed)
            
            status['playlist_total'] = len(self.playlist)
            status['playlist_index'] = self.playlist_index
            if self.playlist and self.playlist_index < len(self.playlist):
                status['current_video_name'] = self.playlist[self.playlist_index]['filename']

        return status

    def _create_fb_live(self):
        try:
            live_info = self.fb_api.create_live_video(
                title=self.db.get_setting('STREAM_TITLE', 'Live Stream'),
                description=self.db.get_setting('STREAM_DESCRIPTION', 'Streaming...')
            )
            if live_info:
                self.session_count += 1
                self.stream_start_time = time.time()
                self.db.update_stream_status(
                    True,
                    live_video_id=live_info.get('id'),
                    stream_url=live_info.get('stream_url'),
                    secure_stream_url=live_info.get('secure_stream_url'),
                    restarts=0
                )
            return live_info
        except Exception as e:
            self.db.log('ERROR', f"Failed to create FB live: {str(e)}")
            return None

    def _launch_ffmpeg(self, filepath, stream_url):
        # Optimized FFmpeg parameters for stability
        cmd = [
            'ffmpeg', '-re',
            '-i', filepath,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-f', 'flv',
            # Add reconnection parameters for network stability
            '-flvflags', 'no_duration_filesize',
            stream_url
        ]
        try:
            # Use a log file for FFmpeg output to avoid pipe filling up
            log_file = open("logs/ffmpeg.log", "a")
            self.process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                preexec_fn=os.setsid
            )
            return True
        except Exception as e:
            self.db.log('ERROR', f"FFmpeg launch error: {e}")
            return False

    def _kill_ffmpeg(self):
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
        self.db.log('INFO', "Rotating Facebook Live session...")
        status = self.db.get_stream_status()
        if status and status.get('live_video_id'):
            self.fb_api.end_live_video(status['live_video_id'])

        self._kill_ffmpeg()
        live_info = self._create_fb_live()
        if not live_info:
            self.db.update_stream_status(False)
            return None

        stream_url = live_info.get('secure_stream_url')
        current_video = self.playlist[self.playlist_index]
        if not self._launch_ffmpeg(current_video['filepath'], stream_url):
            self.db.update_stream_status(False)
            return None

        if self.telegram:
            self.telegram.notify_stream_rotated(self.session_count)
        return stream_url

    def _advance_playlist(self, stream_url):
        self.playlist_index = (self.playlist_index + 1) % len(self.playlist)
        next_video = self.playlist[self.playlist_index]
        self.db.log('INFO', f"Playlist advancing to: {next_video['filename']}")
        
        if self.telegram:
            self.telegram.notify_next_video(next_video['filename'], self.playlist_index + 1, len(self.playlist))
            
        return self._launch_ffmpeg(next_video['filepath'], stream_url)

    def _monitor_stream(self, stream_url):
        current_url = stream_url
        while not self.stop_event.is_set():
            # 8-hour rotation
            if self.stream_start_time and (time.time() - self.stream_start_time >= ROTATE_INTERVAL_SECONDS):
                new_url = self._rotate_stream()
                if new_url is None: break
                current_url = new_url
                time.sleep(5)
                continue

            # Process check
            if self.process:
                exit_code = self.process.poll()
                if exit_code is not None:
                    if exit_code == 0:
                        # Finished normally
                        if not self._advance_playlist(current_url):
                            self.db.update_stream_status(False)
                            break
                    else:
                        # Crashed
                        self.restarts += 1
                        self.db.log('WARNING', f"FFmpeg crashed (exit {exit_code}). Restarting... (attempt {self.restarts})")
                        self.db.update_stream_status(True, restarts=1)
                        if self.telegram: self.telegram.notify_stream_crashed(self.restarts)
                        
                        current_video = self.playlist[self.playlist_index]
                        if not self._launch_ffmpeg(current_video['filepath'], current_url):
                            self.db.update_stream_status(False)
                            break
            
            time.sleep(5)
