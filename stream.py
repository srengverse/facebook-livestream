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
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.restarts = 0
        self.stream_start_time = None
        self.session_count = 0    # counts FB live sessions created
        self.logger = logging.getLogger("StreamManager")
        self.playlist_file = "uploads/playlist.txt"

    def start_stream(self, video_ids: list):
        if self.process and self.process.poll() is None:
            return False, "Stream is already running"

        # Build playlist
        self.playlist = []
        for vid_id in video_ids:
            video_data = self.db.get_video(vid_id)
            if video_data:
                # Validate file exists and is readable
                if os.path.exists(video_data['filepath']) and os.access(video_data['filepath'], os.R_OK):
                    self.playlist.append(video_data)
                else:
                    self.db.log('WARNING', f"Video file missing or unreadable: {video_data['filename']}")

        if not self.playlist:
            return False, "No valid or readable videos found"

        # Create playlist file for FFmpeg concat
        self._generate_playlist_file()

        live_info = self._create_fb_live()
        if not live_info:
            return False, "Failed to create Facebook Live video"

        stream_url = live_info.get('secure_stream_url') or live_info.get('stream_url')
        if not stream_url:
            self.stop_stream()
            return False, "Facebook API did not return a stream URL."

        self.restarts = 0
        self.stop_event.clear()

        success = self._launch_ffmpeg(stream_url)
        if not success:
            return False, "Failed to launch FFmpeg"

        self.monitor_thread = threading.Thread(
            target=self._monitor_stream,
            args=(stream_url,),
            daemon=True
        )
        self.monitor_thread.start()

        self.db.log('INFO', f"Started seamless streaming with {len(self.playlist)} videos")
        if self.telegram:
            self.telegram.notify_stream_started(f"{len(self.playlist)} videos (Looping)")

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
            status['current_video_name'] = "Seamless Playlist Loop"

        return status

    def _generate_playlist_file(self):
        """Create a text file for FFmpeg concat demuxer."""
        try:
            with open(self.playlist_file, "w") as f:
                for video in self.playlist:
                    # Escape single quotes for FFmpeg
                    path = os.path.abspath(video['filepath']).replace("'", "'\\''")
                    f.write(f"file '{path}'\n")
            return True
        except Exception as e:
            self.db.log('ERROR', f"Failed to generate playlist file: {e}")
            return False

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

    def _launch_ffmpeg(self, stream_url):
        """
        Launch FFmpeg using concat demuxer for seamless looping.
        Supports logo overlay if enabled in settings.
        """
        enable_logo = self.db.get_setting('ENABLE_LOGO', 'false') == 'true'
        logo_path = self.db.get_setting('LOGO_PATH')
        logo_pos = self.db.get_setting('LOGO_POSITION', 'top-right')

        # Base command
        # -fflags +genpts: Regenerate PTS for smoother streaming
        # -avoid_negative_ts make_zero: Fix potential timestamp issues
        cmd = [
            'ffmpeg', '-re', 
            '-stream_loop', '-1', 
            '-f', 'concat', 
            '-safe', '0', 
            '-i', self.playlist_file,
            '-fflags', '+genpts',
            '-avoid_negative_ts', 'make_zero'
        ]

        if enable_logo and logo_path and os.path.exists(logo_path):
            # If logo is enabled, we need to re-encode because copy codec doesn't support filters
            cmd += ['-i', logo_path]
            
            # Position logic
            pos_filter = "main_w-overlay_w-10:10" # default top-right
            if logo_pos == 'top-left': pos_filter = "10:10"
            elif logo_pos == 'bottom-left': pos_filter = "10:main_h-overlay_h-10"
            elif logo_pos == 'bottom-right': pos_filter = "main_w-overlay_w-10:main_h-overlay_h-10"
            
            # Complex filter for overlay
            cmd += ['-filter_complex', f"[1:v]scale=150:-1[logo];[0:v][logo]overlay={pos_filter}"]
            # Use threads 0 for auto-detection
            cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-b:v', '3000k', '-maxrate', '3000k', '-bufsize', '6000k', '-threads', '0']
            cmd += ['-pix_fmt', 'yuv420p', '-g', '60', '-c:a', 'aac', '-b:a', '128k']
        else:
            # No logo, use stream copy for efficiency
            cmd += ['-c', 'copy']

        # flvflags no_duration_filesize is standard for RTMP
        cmd += ['-f', 'flv', '-flvflags', 'no_duration_filesize', stream_url]
        
        try:
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
        """End current FB live and start a new one before 8-hour limit."""
        self.db.log('INFO', "Rotating Facebook Live session (8-hour limit)...")
        status = self.db.get_stream_status()
        if status and status.get('live_video_id'):
            self.fb_api.end_live_video(status['live_video_id'])

        self._kill_ffmpeg()
        live_info = self._create_fb_live()
        if not live_info:
            self.db.update_stream_status(False)
            return None

        stream_url = live_info.get('secure_stream_url') or live_info.get('stream_url')
        if not self._launch_ffmpeg(stream_url):
            self.db.update_stream_status(False)
            return None

        if self.telegram:
            self.telegram.notify_stream_rotated(self.session_count)
        return stream_url

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
                    # FFmpeg crashed or stopped unexpectedly
                    self.restarts += 1
                    self.db.log('WARNING', f"FFmpeg stopped (exit {exit_code}). Attempt {self.restarts}")
                    
                    if self.restarts > 5:
                        self.db.log('ERROR', "Too many FFmpeg restarts. Stopping stream.")
                        self.stop_stream()
                        break

                    self.db.update_stream_status(True, restarts=1)
                    if self.telegram: 
                        self.telegram.notify_stream_crashed(self.restarts)
                    
                    # Relaunch using the same URL (if still valid)
                    if not self._launch_ffmpeg(current_url):
                        self.db.log('ERROR', "Failed to relaunch FFmpeg. Stopping.")
                        self.stop_stream()
                        break
            
            time.sleep(5)
