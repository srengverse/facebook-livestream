# Facebook Live Streaming Platform

This project is a complete production-ready Facebook Live Streaming Platform built with Python (Flask), SQLite, and FFmpeg. It allows users to automatically create Facebook Live broadcasts, retrieve RTMPS stream URLs, and continuously stream MP4 videos.

## Features

*   **Dashboard**: Real-time monitoring of CPU, RAM, Disk Usage, Network Speed, and Stream Status.
*   **Facebook Integration**: Configure Page Access Token and Page ID, verify connection, and automatically create/end live videos.
*   **Video Library**: Upload, delete, rename, preview, and manage MP4 video files.
*   **Streaming Control**: Start and stop live streams, loop videos, and view live FFmpeg logs.
*   **Auto Recovery**: Automatic restart of FFmpeg if it crashes, with a health check every 10 seconds.
*   **System Logs**: Store and view application event logs.
*   **REST API**: Endpoints for status, stream control, Facebook settings, video management, and logs.
*   **Modern UI**: Responsive admin dashboard with Dark Mode, Glassmorphism design, gradient cards, and animated buttons.

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
2.  **Access the web UI**: Open your browser and navigate to `http://localhost:5000` (or the configured port).
3.  **Configure Facebook Settings**: Go to the "FB Settings" tab, enter your Page Access Token and Page ID, and verify the connection.
4.  **Upload Videos**: Go to the "Video Library" tab and upload your MP4 files.
5.  **Start Streaming**: Go to the "Streaming" tab, select a video, and click "Start Broadcast".

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
