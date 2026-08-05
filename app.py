from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
from functools import wraps
import os
import secrets
from config import Config
from database import Database
from system_monitor import SystemMonitor
from facebook_api import FacebookAPI
from stream import StreamManager
from telegram_notifier import TelegramNotifier

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

db = Database()
monitor = SystemMonitor()
fb_api = FacebookAPI(db)
telegram = TelegramNotifier(db)
stream_manager = StreamManager(db, fb_api, telegram)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

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

    # If credentials are not configured yet, show a setup notice
    if not admin_user or not admin_pass:
        return render_template('login.html', error=None, not_configured=True)

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == admin_user and password == admin_pass:
            session['logged_in'] = True
            return redirect(url_for('index'))
        error = 'Invalid username or password.'

    return render_template('login.html', error=error, not_configured=False)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

@app.route('/')
@login_required
def index():
    return render_template('index.html')


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

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
        db.set_setting('PAGE_ACCESS_TOKEN', data.get('token'))
        db.set_setting('PAGE_ID', data.get('page_id'))
        info = fb_api.get_page_info()
        if info:
            return jsonify({'status': 'success', 'page_info': info})
        return jsonify({'status': 'error', 'message': 'Invalid token or page ID'}), 400

    return jsonify({
        'token': db.get_setting('PAGE_ACCESS_TOKEN', ''),
        'page_id': db.get_setting('PAGE_ID', '')
    })


@app.route('/api/telegram', methods=['GET', 'POST'])
@login_required
def handle_telegram_settings():
    if request.method == 'POST':
        data = request.json
        db.set_setting('TELEGRAM_BOT_TOKEN', data.get('bot_token', ''))
        db.set_setting('TELEGRAM_CHAT_ID', data.get('chat_id', ''))
        # Send a test message to verify
        telegram._send('✅ <b>Telegram connected!</b>\nYour stream notifications are now active.')
        return jsonify({'status': 'success'})

    return jsonify({
        'bot_token': db.get_setting('TELEGRAM_BOT_TOKEN', ''),
        'chat_id': db.get_setting('TELEGRAM_CHAT_ID', '')
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

        filename = secrets.token_hex(8) + "_" + file.filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        db.add_video(file.filename, filepath)
        return jsonify({'status': 'success', 'filename': file.filename})

    return jsonify(db.get_videos())


@app.route('/api/videos/<int:video_id>', methods=['DELETE', 'PUT'])
@login_required
def manage_video(video_id):
    if request.method == 'DELETE':
        db.delete_video(video_id)
        return jsonify({'status': 'success'})

    # PUT — rename
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

    # Accept either a single video_id or a playlist of video_ids
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


if __name__ == '__main__':
    Config.init_app(app)
    app.run(host='0.0.0.0', port=app.config['PORT'], debug=app.config['DEBUG'])
