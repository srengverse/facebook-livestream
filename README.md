# Facebook Live Streaming Platform

This project is a complete production-ready Facebook Live Streaming Platform built with Python (Flask), SQLite, and FFmpeg. It allows users to automatically create Facebook Live broadcasts, retrieve RTMPS stream URLs, and continuously stream MP4 videos.

## Features

*   **Seamless Streaming**: Continuous video looping using FFmpeg Concat Demuxer to prevent Facebook stream disconnections.
*   **Advanced Scheduling**: Plan your live broadcasts in advance with a built-in background scheduler.
*   **Branding & Overlays**: Real-time logo overlay support with customizable positions (Top-Left, Top-Right, etc.).
*   **Professional Dashboard**: Modern, responsive UI with real-time system monitoring and smooth transitions.
*   **Enterprise-Grade Security**: CSRF protection, secure password hashing, and strict input sanitization.
*   **Performance Optimized**: Background status monitoring, database WAL mode, and in-memory settings caching.
*   **Reliability**: Exponential backoff for stream restarts and automatic 8-hour session rotation for long-term streaming.
*   **Auto Recovery**: Automatic restart of FFmpeg if it crashes, with intelligent fault tolerance.
*   **System Logs**: Automated log pruning to save disk space while maintaining history.
*   **REST API**: Secure endpoints for status, stream control, settings, and video management.

## Tech Stack

**Backend**:
*   Python 3.12
*   Flask
*   Requests
*   Gunicorn
*   FFmpeg
*   psutil
*   python-dotenv

**Frontend**:
*   HTML5
*   TailwindCSS
*   Vanilla JavaScript
*   Lucide Icons

**Database**:
*   SQLite

## Project Structure

```
facebook-live/
├── app.py
├── config.py
├── database.py
├── facebook_api.py
├── stream.py
├── system_monitor.py
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── facebook-live.service
├── nginx.conf
├── README.md
├── templates/
│   └── index.html
├── static/
├── uploads/
└── logs/
```

## Installation Guide

See [INSTALLATION.md](INSTALLATION.md) for detailed installation instructions.

## Deployment Guide

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions.

## Configuration

Copy `.env.example` to `.env` and fill in your details:

```bash
cp .env.example .env
```

Edit `.env`:

```ini
PAGE_ACCESS_TOKEN=your_page_access_token_here
PAGE_ID=your_page_id_here
VIDEO_PATH=uploads/
STREAM_TITLE=My Live Stream
STREAM_DESCRIPTION=Streaming from my custom platform
SECRET_KEY=generate_a_random_secret_key_here
DATABASE_URL=sqlite:///database.db
PORT=5000
DEBUG=True
```

## Usage

1.  **Start the application** (after installation and configuration):
    ```bash
    python3 app.py
    ```
2.  **Access the web UI**: Open your browser and navigate to `http://localhost:5000`.
3.  **Configure Facebook Settings**: Go to the "Settings" tab, enter your Page Access Token and Page ID. The system will automatically verify the connection.
4.  **Upload Videos**: Go to the "Video Library" tab and upload your MP4 files.
5.  **Schedule or Start**: Use the "Streaming" tab for instant broadcasts or the "Schedules" tab to plan for later.
6.  **Branding**: Upload your logo in the "Settings" tab to add a watermark to your live stream.

## Testing
Run unit tests to ensure system integrity:
```bash
PYTHONPATH=. python3 tests/test_database.py
```

## API Endpoints

*   `/api/status`: Get system and stream status.
*   `/api/facebook` (GET/POST): Manage Facebook page settings.
*   `/api/videos` (GET/POST): List and upload videos.
*   `/api/videos/<int:video_id>` (DELETE): Delete a video.
*   `/api/start` (POST): Start the live stream.
*   `/api/stop` (POST): Stop the live stream.
*   `/api/logs`: Get application logs.

## Contributing

Feel free to fork the repository, open issues, and submit pull requests.

## License

This project is open-source and available under the MIT License.

---

**Manus AI**
