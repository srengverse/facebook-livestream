from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect, generate_csrf
from functools import wraps
import os
import secrets
import werkzeug
from werkzeug.security import check_password_hash
import threading
import time
import json
import signal
import sys
from sqlite3 import IntegrityError
from urllib.parse import urlparse
from config import Config
from database import Database
from system_monitor import SystemMonitor
from facebook_api import FacebookAPI
from stream import StreamManager
from telegram_notifier import TelegramNotifier
from security_utils import SecretCipher, redact_url
from media_utils import is_valid_video, has_sufficient_space

app = Flask(__name__)
app.config.from_object(Config)

# Security: Limit upload size (e.g., 500MB)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024 

# CSRF Protection
csrf = CSRFProtect(app)

# CORS configuration
CORS(app, resources={r"/api/*": {"origins": app.config.get('ALLOWED_ORIGINS')}})

db = Database()
monitor = SystemMonitor()
fb_api = FacebookAPI(db)
telegram = TelegramNotifier(db)
stream_manager = StreamManager(
    db,
    fb_api,
    telegram,
    encryption_key=app.config.get('DESTINATION_ENCRYPTION_KEY'),
)

# --- Background Scheduler ---
class BackgroundTasks:
    def __init__(self, db, stream_manager):
        self.db = db
        self.stream_manager = stream_manager
        self.stop_event = threading.Event()
        self.last_prune = 0

    def run(self):
        while not self.stop_event.is_set():
            try:
                # 1. Run scheduled streams
                due = self.db.get_due_schedules()
                for s in due:
                    self.db.log('INFO', f"Running scheduled stream for schedule #{s['id']}")
                    video_ids = json.loads(s['video_ids'])
                    success, message = self.stream_manager.start_stream(video_ids)
                    if success:
                        self.db.mark_schedule_run(s['id'])
                    else:
                        self.db.log('ERROR', f"Scheduled stream failed: {message}")
                
                # 2. Prune old logs once a day
                now = time.time()
                if now - self.last_prune > 86400:
                    self.db.prune_logs(days=7)
                    self.last_prune = now
                    
            except Exception as e:
                self.db.log('ERROR', f"Background task error: {str(e)}")
            
            # Sleep in small increments to allow faster shutdown
            for _ in range(30):
                if self.stop_event.is_set(): break
                time.sleep(1)

    def stop(self):
        self.stop_event.set()

bg_tasks = BackgroundTasks(db, stream_manager)
scheduler_thread = threading.Thread(target=bg_tasks.run, daemon=True)
scheduler_thread.start()

# --- Graceful Shutdown ---
def signal_handler(sig, frame):
    print("\nShutting down gracefully...")
    bg_tasks.stop()
    stream_manager.stop_stream()
    monitor.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

ALLOWED_EXTENSIONS = {'mp4', 'mkv', 'mov', 'avi'}
ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg'}
RTMP_SCHEMES = {'rtmp', 'rtmps'}
SUPPORTED_DESTINATION_PLATFORMS = {'youtube', 'custom'}


def get_destination_cipher():
    """Create the encryption helper only when multi-platform credentials are used."""
    encryption_key = app.config.get('DESTINATION_ENCRYPTION_KEY') or app.config.get('SECRET_KEY')
    return SecretCipher(encryption_key)


def validate_rtmp_destination(name, platform, rtmp_url, stream_key):
    """Validate a destination before it can reach FFmpeg or persistent storage."""
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        return None, 'Destination name must contain 1 to 80 characters.'
    if platform not in SUPPORTED_DESTINATION_PLATFORMS:
        return None, 'Unsupported destination platform.'
    if not isinstance(rtmp_url, str) or len(rtmp_url) > 1024:
        return None, 'RTMP server URL is invalid.'
    if not isinstance(stream_key, str) or not 1 <= len(stream_key.strip()) <= 1024:
        return None, 'Stream key is required.'

    parsed = urlparse(rtmp_url.strip())
    if parsed.scheme.lower() not in RTMP_SCHEMES or not parsed.netloc:
        return None, 'Server URL must use rtmp:// or rtmps:// and include a hostname.'
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None, 'Server URL cannot contain credentials, a query string, or a fragment.'
    # SECURITY: Prevent injection into FFmpeg command and tee muxer syntax
    # Disallow characters that can be used for shell injection or FFmpeg option breaking
    forbidden = ('\\r', '\\n', '\\x00', '|', '[', ']', '"', "'", ';', '>', '<', '&', '$', '(', ')', '`', '{', '}', '*', '?', '!', '#')
    if any(char in stream_key for char in forbidden):
        return None, 'Stream key contains unsupported or insecure characters.'
    if any(char in rtmp_url for char in forbidden):
        return None, 'RTMP URL contains unsupported or insecure characters.'

    normalized_url = rtmp_url.strip().rstrip('/')
    return {
        'name': name.strip(),
        'platform': platform,
        'rtmp_url': normalized_url,
        'stream_key': stream_key.strip().lstrip('/'),
    }, None


def serialize_destination(destination):
    """Return destination metadata without ever exposing its stream key."""
    return {
        'id': destination['id'],
        'name': destination['name'],
        'platform': destination['platform'],
        'rtmp_url': redact_url(destination['rtmp_url']),
        'stream_key_configured': bool(destination.get('stream_key_encrypted')),
        'stream_key_masked': 'Configured' if destination.get('stream_key_encrypted') else '',
        'enabled': bool(destination['enabled']),
        'created_at': destination['created_at'],
        'updated_at': destination['updated_at'],
    }

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_logo(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    admin_user = os.getenv('ADMIN_USERNAME', '').strip()
    admin_pass = os.getenv('ADMIN_PASSWORD', '').strip()

    if not admin_user or not admin_pass:
        return render_template('login.html', error=None, not_configured=True)

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        # SECURITY: Remove plaintext fallback. Enforce secure hashing.
        is_valid = False
        if admin_pass.startswith(('pbkdf2:sha256:', 'scrypt:')):
            is_valid = (username == admin_user and check_password_hash(admin_pass, password))
        else:
            # Log a critical security warning if the server is running with plaintext credentials
            app.logger.critical("SECURITY ALERT: ADMIN_PASSWORD is not hashed. Login denied.")
            error = 'System configuration error. Please contact administrator.'
            return render_template('login.html', error=error, not_configured=False)
            
        if is_valid:
            # Prevent session fixation by clearing old session data
            session.clear()
            session['logged_in'] = True
            session.permanent = True
            return redirect(url_for('index'))
        error = 'Invalid username or password.'

    return render_template('login.html', error=error, not_configured=False)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html', csrf_token=generate_csrf())

@app.route('/api/status')
@login_required
def get_status():
    sys_status = monitor.get_system_stats()
    stream_status = stream_manager.get_status()
    return jsonify({'system': sys_status, 'stream': stream_status})

@app.route('/api/facebook', methods=['GET', 'POST'])
@login_required
def handle_facebook_settings():
    if request.method == 'POST':
        data = request.json
        token = data.get('token', '').strip()
        page_id = data.get('page_id', '').strip()
        
        if not token or not page_id:
            return jsonify({'status': 'error', 'message': 'Token and Page ID are required'}), 400
            
        db.set_setting('PAGE_ACCESS_TOKEN', token)
        db.set_setting('PAGE_ID', page_id)
        
        info = fb_api.get_page_info()
        if info:
            return jsonify({'status': 'success', 'page_info': info})
        return jsonify({'status': 'error', 'message': 'Invalid token or page ID'}), 400

    token = db.get_setting('PAGE_ACCESS_TOKEN') or app.config.get('PAGE_ACCESS_TOKEN', '')
    page_id = db.get_setting('PAGE_ID') or app.config.get('PAGE_ID', '')
    
    info = None
    if token and page_id:
        # Update credentials in memory for the current check
        # Note: FacebookAPI uses db.get_setting, so we should ensure it has access to fallback
        info = fb_api.get_page_info()
        
    return jsonify({
        'token': token,
        'page_id': page_id,
        'page_info': info
    })

@app.route('/api/telegram', methods=['GET', 'POST'])
@login_required
def handle_telegram_settings():
    if request.method == 'POST':
        data = request.json
        db.set_setting('TELEGRAM_BOT_TOKEN', data.get('bot_token', ''))
        db.set_setting('TELEGRAM_CHAT_ID', data.get('chat_id', ''))
        telegram._send('✅ <b>Telegram connected!</b>\nYour stream notifications are now active.')
        return jsonify({'status': 'success'})

    return jsonify({
        'bot_token': db.get_setting('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN', ''),
        'chat_id': db.get_setting('TELEGRAM_CHAT_ID') or os.getenv('TELEGRAM_CHAT_ID', '')
    })

@app.route('/api/videos', methods=['GET', 'POST'])
@login_required
def handle_videos():
    if request.method == 'POST':
        if 'video' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file part'}), 400
        file = request.files['video']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No selected file'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'status': 'error', 'message': 'File type not allowed'}), 400

        # Security: Sanitize filename and prevent path traversal
        safe_name = werkzeug.utils.secure_filename(file.filename)
        if not safe_name:
            return jsonify({'status': 'error', 'message': 'Invalid filename'}), 400
        
        # Generate collision-resistant storage filename
        filename = secrets.token_hex(16) + "_" + safe_name
        upload_dir = os.path.abspath(app.config['UPLOAD_FOLDER'])
        filepath = os.path.abspath(os.path.join(upload_dir, filename))
        
        # Prevent path traversal
        if not filepath.startswith(upload_dir):
            return jsonify({'status': 'error', 'message': 'Invalid upload path'}), 400
            
        # Check disk space before saving (estimate based on Content-Length)
        content_length = request.content_length or 0
        if not has_sufficient_space(upload_dir, content_length):
            return jsonify({'status': 'error', 'message': 'Insufficient disk space'}), 507

        try:
            # Save file temporarily to validate content
            file.save(filepath)
            
            # Deep media validation
            is_valid, media_info = is_valid_video(filepath)
            if not is_valid:
                if os.path.exists(filepath):
                    os.remove(filepath)
                return jsonify({'status': 'error', 'message': media_info}), 400
            
            # Extract metadata
            format_info = media_info.get('format', {})
            duration = format_info.get('duration')
            bitrate = format_info.get('bit_rate')
            
            # Resolution from first video stream
            resolution = "unknown"
            for stream in media_info.get('streams', []):
                if stream.get('codec_type') == 'video':
                    resolution = f"{stream.get('width')}x{stream.get('height')}"
                    break

            # Atomic DB insert: if this fails, we must cleanup the file
            try:
                db.add_video(safe_name, filepath, duration=duration, resolution=resolution, bitrate=bitrate)
            except Exception as e:
                if os.path.exists(filepath):
                    os.remove(filepath)
                app.logger.error(f"Database error during video upload: {str(e)}")
                return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

            return jsonify({'status': 'success', 'filename': safe_name})
            
        except OSError as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            app.logger.error(f"IO error during video upload: {str(e)}")
            return jsonify({'status': 'error', 'message': 'File system error'}), 500
        except Exception as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            app.logger.error(f"Unexpected error during video upload: {str(e)}")
            return jsonify({'status': 'error', 'message': 'Upload failed'}), 500

    return jsonify(db.get_videos())

@app.route('/api/videos/<int:video_id>', methods=['DELETE', 'PUT'])
@login_required
def manage_video(video_id):
    if request.method == 'DELETE':
        db.delete_video(video_id)
        return jsonify({'status': 'success'})

    data = request.json
    new_name = (data.get('filename') or '').strip()
    if not new_name:
        return jsonify({'status': 'error', 'message': 'Filename cannot be empty'}), 400
    db.update_video_filename(video_id, new_name)
    return jsonify({'status': 'success'})

@app.route('/api/start', methods=['POST'])
@login_required
def start_stream():
    data = request.json
    video_ids = data.get('video_ids') or []
    if not video_ids and data.get('video_id'):
        video_ids = [data['video_id']]
    if not video_ids:
        return jsonify({'status': 'error', 'message': 'No video selected'}), 400

    success, message = stream_manager.start_stream(video_ids)
    if success:
        return jsonify({'status': 'success', 'message': message})
    return jsonify({'status': 'error', 'message': message}), 500

@app.route('/api/stop', methods=['POST'])
@login_required
def stop_stream():
    success, message = stream_manager.stop_stream()
    if success:
        return jsonify({'status': 'success', 'message': message})
    return jsonify({'status': 'error', 'message': message}), 500

@app.route('/api/logs')
@login_required
def get_logs():
    return jsonify(db.get_logs())

@app.route('/api/schedules', methods=['GET', 'POST'])
@login_required
def handle_schedules():
    if request.method == 'POST':
        data = request.json
        video_ids = data.get('video_ids')
        scheduled_time = data.get('scheduled_time')
        if not video_ids or not scheduled_time:
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400
        db.add_schedule(json.dumps(video_ids), scheduled_time)
        return jsonify({'status': 'success'})
    return jsonify(db.get_schedules())

@app.route('/api/schedules/<int:sid>', methods=['DELETE'])
@login_required
def delete_schedule(sid):
    db.delete_schedule(sid)
    return jsonify({'status': 'success'})

@app.route('/api/destinations', methods=['GET', 'POST'])
@login_required
def handle_destinations():
    if request.method == 'GET':
        return jsonify([serialize_destination(item) for item in db.get_destinations()])

    if stream_manager.is_running():
        return jsonify({'status': 'error', 'message': 'Stop the active broadcast before changing destinations.'}), 409

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON request body is required.'}), 400

    destination, error = validate_rtmp_destination(
        data.get('name'),
        data.get('platform'),
        data.get('rtmp_url'),
        data.get('stream_key'),
    )
    if error:
        return jsonify({'status': 'error', 'message': error}), 400

    try:
        destination_id = db.add_destination(
            destination['name'],
            destination['platform'],
            destination['rtmp_url'],
            get_destination_cipher().encrypt(destination['stream_key']),
            data.get('enabled', True),
        )
    except ValueError as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 503
    except IntegrityError:
        return jsonify({'status': 'error', 'message': 'A destination with this name already exists.'}), 409

    db.log('INFO', f"Added multi-platform destination: {destination['name']} ({destination['platform']})")
    return jsonify({'status': 'success', 'id': destination_id}), 201


@app.route('/api/destinations/<int:destination_id>', methods=['PUT', 'DELETE'])
@login_required
def manage_destination(destination_id):
    existing = db.get_destination(destination_id)
    if not existing:
        return jsonify({'status': 'error', 'message': 'Destination not found.'}), 404
    if stream_manager.is_running():
        return jsonify({'status': 'error', 'message': 'Stop the active broadcast before changing destinations.'}), 409

    if request.method == 'DELETE':
        db.delete_destination(destination_id)
        db.log('INFO', f"Removed multi-platform destination: {existing['name']}")
        return jsonify({'status': 'success'})

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'A JSON request body is required.'}), 400

    # For a toggle-only update, no secret is needed. A complete edit requires a key.
    if set(data).issubset({'enabled'}):
        db.update_destination(destination_id, enabled=bool(data['enabled']))
        return jsonify({'status': 'success'})

    stream_key = data.get('stream_key')
    if not stream_key:
        return jsonify({'status': 'error', 'message': 'Provide the stream key when editing a destination.'}), 400

    destination, error = validate_rtmp_destination(
        data.get('name'),
        data.get('platform'),
        data.get('rtmp_url'),
        stream_key,
    )
    if error:
        return jsonify({'status': 'error', 'message': error}), 400

    try:
        db.update_destination(
            destination_id,
            name=destination['name'],
            platform=destination['platform'],
            rtmp_url=destination['rtmp_url'],
            stream_key_encrypted=get_destination_cipher().encrypt(destination['stream_key']),
            enabled=data.get('enabled', existing['enabled']),
        )
    except ValueError as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 503
    except IntegrityError:
        return jsonify({'status': 'error', 'message': 'A destination with this name already exists.'}), 409

    db.log('INFO', f"Updated multi-platform destination: {destination['name']}")
    return jsonify({'status': 'success'})


@app.route('/api/branding', methods=['GET', 'POST'])
@login_required
def handle_branding():
    if request.method == 'POST':
        # Handle logo upload
        if 'logo' in request.files:
            file = request.files['logo']
            if file and allowed_logo(file.filename):
                safe_name = werkzeug.utils.secure_filename(file.filename)
                if safe_name:
                    filename = "logo_" + secrets.token_hex(8) + "_" + safe_name
                    filepath = os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    
                    if filepath.startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
                        file.save(filepath)
                        db.set_setting('LOGO_PATH', filepath)
        
        # Handle other branding settings
        data = request.form.to_dict()
        if not data and request.is_json:
            data = request.json
            
        if 'enable_logo' in data:
            db.set_setting('ENABLE_LOGO', data['enable_logo'])
        if 'logo_position' in data:
            db.set_setting('LOGO_POSITION', data['logo_position'])
            
        return jsonify({'status': 'success'})

    return jsonify({
        'logo_path': db.get_setting('LOGO_PATH', ''),
        'enable_logo': db.get_setting('ENABLE_LOGO', 'false'),
        'logo_position': db.get_setting('LOGO_POSITION', 'top-right')
    })

if __name__ == '__main__':
    Config.init_app(app)
    app.run(host='0.0.0.0', port=app.config['PORT'], debug=app.config['DEBUG'])
