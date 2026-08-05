import subprocess
import threading
import time
import os
import signal
import psutil

class StreamManager:
    def __init__(self, db, fb_api):
        self.db = db
        self.fb_api = fb_api
        self.process = None
        self.current_video = None
        self.stop_event = threading.Event()
        self.monitor_thread = None
        self.restarts = 0

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

        # Start FFmpeg
        self.stop_event.clear()
        success = self._launch_ffmpeg(self.current_video['filepath'], stream_url)
        
        if success:
            self.monitor_thread = threading.Thread(target=self._monitor_stream, args=(video_id, stream_url))
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            self.db.log('INFO', f"Started streaming: {self.current_video['filename']}")
            return True, "Stream started successfully"
        else:
            return False, "Failed to launch FFmpeg"

    def _launch_ffmpeg(self, filepath, stream_url):
        # Command to loop video forever
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
            # Use subprocess.Popen to run in background
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                preexec_fn=os.setsid # To kill process group
            )
            return True
        except Exception as e:
            self.db.log('ERROR', f"FFmpeg Launch Error: {str(e)}")
            return False

    def _monitor_stream(self, video_id, stream_url):
        while not self.stop_event.is_set():
            if self.process.poll() is not None:
                # Process crashed or stopped unexpectedly
                self.restarts += 1
                self.db.log('WARNING', f"FFmpeg process died. Restarting... (Attempt {self.restarts})")
                self.db.update_stream_status(True, restarts=1)
                
                # Try to restart FFmpeg
                if not self._launch_ffmpeg(self.current_video['filepath'], stream_url):
                    self.db.log('ERROR', "Failed to restart FFmpeg. Stopping stream.")
                    self.stop_stream()
                    break
            
            time.sleep(10)

    def stop_stream(self):
        self.stop_event.set()
        
        status = self.db.get_stream_status()
        if status and status['live_video_id']:
            self.fb_api.end_live_video(status['live_video_id'])

        if self.process:
            try:
                # Kill process group
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
            except:
                if self.process:
                    self.process.kill()
            self.process = None

        self.db.update_stream_status(False)
        self.db.log('INFO', "Stream stopped")
        return True, "Stream stopped"

    def get_status(self):
        status = self.db.get_stream_status()
        if status and status['is_streaming'] and self.process:
            # Get real-time stats from process if possible
            # For simplicity, we return the DB status + process info
            try:
                p = psutil.Process(self.process.pid)
                status['cpu'] = p.cpu_percent()
                status['memory'] = p.memory_info().rss / (1024 * 1024)
            except:
                status['cpu'] = 0
                status['memory'] = 0
        return status
