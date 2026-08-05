import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    PAGE_ACCESS_TOKEN = os.getenv('PAGE_ACCESS_TOKEN')
    PAGE_ID = os.getenv('PAGE_ID')
    VIDEO_PATH = os.getenv('VIDEO_PATH', 'uploads/')
    STREAM_TITLE = os.getenv('STREAM_TITLE', 'My Live Stream')
    STREAM_DESCRIPTION = os.getenv('STREAM_DESCRIPTION', 'Streaming from my custom platform')
    SECRET_KEY = os.getenv('SECRET_KEY', 'default_secret_key')
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///database.db')
    PORT = int(os.getenv('PORT', 5000))
    DEBUG = os.getenv('DEBUG', 'True') == 'True'
    LOG_PATH = os.getenv('LOG_PATH', 'logs/')
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads/')

    @staticmethod
    def init_app(app):
        if not os.path.exists(Config.UPLOAD_FOLDER):
            os.makedirs(Config.UPLOAD_FOLDER)
        if not os.path.exists(Config.LOG_PATH):
            os.makedirs(Config.LOG_PATH)
