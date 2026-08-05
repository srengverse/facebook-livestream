# Facebook Live Streaming Platform

A production-ready Flask/Python web app for creating Facebook Live broadcasts, managing MP4 videos, and streaming via FFmpeg.

## How to run

The app is configured to start automatically via the "Start application" workflow.

Manual start:
```bash
python3 app.py
```

The server listens on port 5000.

## Stack

- **Backend**: Python 3.12, Flask, gunicorn, psutil, python-dotenv, flask-cors
- **Streaming**: FFmpeg (system dependency via Nix)
- **Database**: SQLite (`database.db`)
- **Frontend**: HTML5, TailwindCSS, Vanilla JS, Lucide Icons

## Environment variables / secrets

All configuration is read from environment variables (set as Replit Secrets):

| Key | Description |
|---|---|
| `PAGE_ACCESS_TOKEN` | Facebook Page Access Token |
| `PAGE_ID` | Facebook Page ID |
| `SECRET_KEY` | Flask session secret key |
| `PORT` | Server port (default: 5000) |
| `VIDEO_PATH` | Upload directory (default: uploads/) |
| `STREAM_TITLE` | Default stream title |
| `STREAM_DESCRIPTION` | Default stream description |
| `DEBUG` | Enable Flask debug mode (True/False) |

Facebook credentials (`PAGE_ACCESS_TOKEN` and `PAGE_ID`) can also be entered directly through the app's **FB Settings** tab without restarting.

## Project structure

```
app.py              # Flask app & routes
config.py           # Config from env vars
database.py         # SQLite helpers
facebook_api.py     # Facebook Graph API integration
stream.py           # FFmpeg stream manager
system_monitor.py   # CPU/RAM/disk monitoring
templates/index.html  # Single-page admin dashboard
uploads/            # Uploaded MP4 files
logs/               # Application logs
```

## User preferences

- Keep the existing Flask/SQLite stack — do not migrate to another framework or database.
