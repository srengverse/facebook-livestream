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
    SECRET_KEY = os.getenv('SECRET_KEY')
    DESTINATION_ENCRYPTION_KEY = os.getenv('DESTINATION_ENCRYPTION_KEY')
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///database.db')
    PORT = int(os.getenv('PORT', 5000))
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    LOG_PATH = os.getenv('LOG_PATH', 'logs/')
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads/')
    
    # Facebook API Configuration
    FACEBOOK_GRAPH_API_VERSION = os.getenv('FACEBOOK_GRAPH_API_VERSION', 'v20.0')
    FACEBOOK_API_TIMEOUT = int(os.getenv('FACEBOOK_API_TIMEOUT', '15'))
    
    # CORS Configuration
    ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:5000').split(',')
    
    # Session Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True').lower() == 'true'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    @staticmethod
    def init_app(app):
        # Validate critical secrets in production
        if not app.debug:
            if not Config.SECRET_KEY or len(Config.SECRET_KEY) < 32:
                raise RuntimeError("PRODUCTION ERROR: SECRET_KEY must be set to a strong random value (min 32 chars).")
            if not Config.DESTINATION_ENCRYPTION_KEY or len(Config.DESTINATION_ENCRYPTION_KEY) < 32:
                raise RuntimeError("PRODUCTION ERROR: DESTINATION_ENCRYPTION_KEY must be set (min 32 chars) for secure storage.")
        else:
            # Safe defaults for local development ONLY
            Config.SECRET_KEY = Config.SECRET_KEY or 'dev_secret_key_only_for_local_use'
            Config.DESTINATION_ENCRYPTION_KEY = Config.DESTINATION_ENCRYPTION_KEY or 'dev_encryption_key_only_for_local_use'

        if not os.path.exists(Config.UPLOAD_FOLDER):
            os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        if not os.path.exists(Config.LOG_PATH):
            os.makedirs(Config.LOG_PATH, exist_ok=True)
