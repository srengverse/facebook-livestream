import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    PAGE_ACCESS_TOKEN = os.getenv('PAGE_ACCESS_TOKEN')
    PAGE_ID = os.getenv('PAGE_ID')
    VIDEO_PATH = os.getenv('VIDEO_PATH', 'uploads/')
    STREAM_TITLE = os.getenv('STREAM_TITLE', 'My Live Stream')
    STREAM_DESCRIPTION = os.getenv('STREAM_DESCRIPTION', 'Streaming from my custom platform')
    # SECRET_KEY must be set to a high-entropy value in production.
    SECRET_KEY = os.getenv('SECRET_KEY', 'default_secret_key')
    # Used only to encrypt third-party RTMP stream keys in SQLite. Set independently
    # so changing Flask session settings does not invalidate stored destinations.
    DESTINATION_ENCRYPTION_KEY = os.getenv('DESTINATION_ENCRYPTION_KEY', '')
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///database.db')
    PORT = int(os.getenv('PORT', 5000))
    DEBUG = os.getenv('DEBUG', 'True') == 'True'
    LOG_PATH = os.getenv('LOG_PATH', 'logs/')
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads/')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    @staticmethod
    def init_app(app):
        if not os.path.exists(Config.UPLOAD_FOLDER):
            os.makedirs(Config.UPLOAD_FOLDER)
        if not os.path.exists(Config.LOG_PATH):
            os.makedirs(Config.LOG_PATH)
