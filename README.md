# Facebook Live Streaming Platform

This project is a complete production-ready Facebook Live Streaming Platform built with Python (Flask), SQLite, and FFmpeg. It allows users to automatically create Facebook Live broadcasts, retrieve RTMPS stream URLs, and continuously stream MP4 videos.

## Features

*   **Seamless Multi-platform Streaming**: A single FFmpeg encoder loops videos continuously and distributes the broadcast to Facebook, YouTube, and custom RTMP/RTMPS destinations without duplicate encoding.
*   **Advanced Scheduling**: Plan your live broadcasts in advance with a built-in background scheduler.
*   **Branding & Overlays**: Real-time logo overlay support with customizable positions (Top-Left, Top-Right, etc.).
*   **Professional Dashboard**: Modern, responsive UI with real-time system monitoring and smooth transitions.
*   **Protected Destinations**: YouTube and custom RTMP stream keys are encrypted at rest and never returned by the dashboard API or written to application logs.
*   **Enterprise-Grade Security**: CSRF protection, secure password hashing, strict input sanitization, and secure session-cookie defaults.
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
facebook-livestream/
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
# Use two different random values, each at least 32 characters long.
SECRET_KEY=replace_with_a_random_value
DESTINATION_ENCRYPTION_KEY=replace_with_a_second_random_value
# Set true only behind an HTTPS reverse proxy; keep false for direct HTTP development.
SESSION_COOKIE_SECURE=false
ADMIN_USERNAME=admin
ADMIN_PASSWORD=replace_with_a_secure_password_or_werkzeug_hash
PAGE_ACCESS_TOKEN=your_page_access_token_here
PAGE_ID=your_page_id_here
STREAM_TITLE=My Live Stream
STREAM_DESCRIPTION=Streaming from my custom platform
PORT=5000
DEBUG=False
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
6.  **Multi-platform destinations**: In **Settings → Multi-platform Destinations**, add YouTube using `rtmp://a.rtmp.youtube.com/live2` and its stream key, or add any valid custom `rtmp://`/`rtmps://` server URL and stream key. Facebook is always the primary destination; enabled extra destinations join the next broadcast automatically.
7.  **Branding**: Upload your logo in the "Settings" tab to add a watermark to your live stream.

### How the fan-out works

The platform encodes the video once as H.264/AAC, then sends the same encoded stream through FFmpeg's `tee` muxer. Each destination has an independent FIFO queue with automatic recovery; a failed external RTMP destination is ignored and retried without intentionally stopping the other outputs. Configure or edit destinations only while the broadcast is stopped, so the active session is deterministic.

> Stream keys are encrypted in the SQLite database using `DESTINATION_ENCRYPTION_KEY`. Keep that value unchanged after saving destinations; changing it prevents decryption of old keys and requires you to re-enter them. For public deployments, terminate TLS through Nginx or another HTTPS proxy and set `SESSION_COOKIE_SECURE=true`.

## Testing
Run unit tests to ensure system integrity:
```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## API Endpoints

*   `/api/status`: Get system and stream status.
*   `/api/facebook` (GET/POST): Manage Facebook page settings.
*   `/api/videos` (GET/POST): List and upload videos.
*   `/api/videos/<int:video_id>` (DELETE): Delete a video.
*   `/api/start` (POST): Start the live stream.
*   `/api/stop` (POST): Stop the live stream.
*   `/api/logs`: Get application logs.
*   `/api/destinations` (GET/POST): List or add encrypted YouTube/custom RTMP destinations.
*   `/api/destinations/<int:destination_id>` (PUT/DELETE): Enable, edit, or remove a destination while the stream is stopped.

## Contributing

Feel free to fork the repository, open issues, and submit pull requests.

## License

This project is open-source and available under the MIT License.

---

**Manus AI**
