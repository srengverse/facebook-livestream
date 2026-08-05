from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import os
import secrets
from config import Config
from database import Database
from system_monitor import SystemMonitor
from facebook_api import FacebookAPI
from stream import StreamManager

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

db = Database()
monitor = SystemMonitor()
fb_api = FacebookAPI(db)
stream_manager = StreamManager(db, fb_api)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    sys_status = monitor.get_system_stats()
    stream_status = stream_manager.get_status()
    return jsonify({
        'system': sys_status,
        'stream': stream_status
    })

@app.route('/api/facebook', methods=['GET', 'POST'])
def handle_facebook_settings():
    if request.method == 'POST':
        data = request.json
        db.set_setting('PAGE_ACCESS_TOKEN', data.get('token'))
        db.set_setting('PAGE_ID', data.get('page_id'))
        # Verify token
        info = fb_api.get_page_info()
        if info:
            return jsonify({'status': 'success', 'page_info': info})
        return jsonify({'status': 'error', 'message': 'Invalid token or page ID'}), 400
    
    return jsonify({
        'token': db.get_setting('PAGE_ACCESS_TOKEN', ''),
        'page_id': db.get_setting('PAGE_ID', '')
    })

@app.route('/api/videos', methods=['GET', 'POST'])
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
        
        # In a real app, we'd use ffprobe here to get metadata
        # For now, we'll just add it to DB
        db.add_video(file.filename, filepath)
        return jsonify({'status': 'success', 'filename': file.filename})

    videos = db.get_videos()
    return jsonify(videos)

@app.route('/api/videos/<int:video_id>', methods=['DELETE'])
def delete_video(video_id):
    db.delete_video(video_id)
    return jsonify({'status': 'success'})

@app.route('/api/start', methods=['POST'])
def start_stream():
    data = request.json
    video_id = data.get('video_id')
    if not video_id:
        return jsonify({'status': 'error', 'message': 'No video selected'}), 400
    
    success, message = stream_manager.start_stream(video_id)
    if success:
        return jsonify({'status': 'success', 'message': message})
    return jsonify({'status': 'error', 'message': message}), 500

@app.route('/api/stop', methods=['POST'])
def stop_stream():
    success, message = stream_manager.stop_stream()
    if success:
        return jsonify({'status': 'success', 'message': message})
    return jsonify({'status': 'error', 'message': message}), 500

@app.route('/api/logs')
def get_logs():
    logs = db.get_logs()
    return jsonify(logs)

if __name__ == '__main__':
    Config.init_app(app)
    app.run(host='0.0.0.0', port=app.config['PORT'], debug=app.config['DEBUG'])
