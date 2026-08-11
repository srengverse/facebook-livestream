from flask import Flask, request, jsonify, render_template, session, redirect, url_for, abort
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect, generate_csrf
from functools import wraps
import os
import secrets
import werkzeug
from werkzeug.security import generate_password_hash, check_password_hash
import threading
import time
import json
import signal
import sys
from datetime import datetime
from config import Config
from database import Database
from system_monitor import SystemMonitor
from facebook_api import FacebookAPI
from stream import StreamManager
from telegram_notifier import TelegramNotifier

app = Flask(__name__)
app.config.from_object(Config)

# Security: Limit upload size (e.g., 500MB)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024 

# CSRF Protection
csrf = CSRFProtect(app)

# CORS configuration
CORS(app)

db = Database()
monitor = SystemMonitor()
fb_api = FacebookAPI(db)
telegram = TelegramNotifier(db)
stream_manager = StreamManager(db, fb_api, telegram)

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
        
        # Check if admin_pass is hashed
        is_valid = False
        if admin_pass.startswith(('pbkdf2:sha256:', 'scrypt:')):
            is_valid = (username == admin_user and check_password_hash(admin_pass, password))
        else:
            # Fallback to plaintext (not recommended, but for initial setup)
            is_valid = (username == admin_user and password == admin_pass)
            
        if is_valid:
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
        
        if file and allowed_file(file.filename):
            # Security: Sanitize filename
            original_filename = werkzeug.utils.secure_filename(file.filename)
            filename = secrets.token_hex(8) + "_" + original_filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            db.add_video(original_filename, filepath)
            return jsonify({'status': 'success', 'filename': original_filename})
        else:
            return jsonify({'status': 'error', 'message': 'File type not allowed'}), 400

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

@app.route('/api/branding', methods=['GET', 'POST'])
@login_required
def handle_branding():
    if request.method == 'POST':
        # Handle logo upload
        if 'logo' in request.files:
            file = request.files['logo']
            if file and allowed_logo(file.filename):
                filename = "logo_" + secrets.token_hex(4) + "_" + werkzeug.utils.secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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
