# Installation Guide

This guide will walk you through the steps to set up and run the Facebook Live Streaming Platform locally.

## Prerequisites

Before you begin, ensure you have the following installed:

*   **Python 3.12+**: Download from [python.org](https://www.python.org/downloads/).
*   **pip**: Python package installer (usually comes with Python).
*   **FFmpeg**: A complete, cross-platform solution to record, convert and stream audio and video. Download from [ffmpeg.org](https://ffmpeg.org/download.html) or install via your system's package manager (e.g., `sudo apt install ffmpeg` on Ubuntu).
*   **Git**: For cloning the repository.

## Steps

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/srengverse/facebook-livestream.git
    cd facebook-livestream
    ```

2.  **Create and activate a virtual environment** (recommended):
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Python dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure environment variables**:
    Copy the example environment file and populate it with your Facebook Page details.
    ```bash
    cp .env.example .env
    ```
    Open the `.env` file and fill in the following:
    ```ini
    # Generate independent values with: python3 -c "import secrets; print(secrets.token_urlsafe(48))"
    SECRET_KEY=replace_with_a_random_value_at_least_32_characters_long
    DESTINATION_ENCRYPTION_KEY=replace_with_a_second_random_value_at_least_32_characters_long
    PAGE_ACCESS_TOKEN=your_page_access_token_here
    PAGE_ID=your_page_id_here
    STREAM_TITLE=My Live Stream
    STREAM_DESCRIPTION=Streaming from my custom platform
    PORT=5000
    DEBUG=False
    ```
    *   **`PAGE_ACCESS_TOKEN`**: Obtain this from your Facebook Developer App. It needs to be a Page Access Token with `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `pages_read_user_content`, `publish_video`, `live_video_broadcasts` permissions.
    *   **`PAGE_ID`**: The ID of your Facebook Page.
    *   **`SECRET_KEY`**: A Flask secret key for session management. Generate a long, random string.
    *   **`DESTINATION_ENCRYPTION_KEY`**: An independent, stable key used to encrypt third-party RTMP stream keys in SQLite. Do not change it after adding destinations, unless you plan to re-enter all destination keys.

5.  **Run the application**:
    ```bash
    python3 app.py
    ```
    The application will start on `http://localhost:5000` (or the port you specified in `.env`).

6.  **Access the UI**: Open your web browser and navigate to the address. Go to the **Settings** tab to verify your Facebook connection.

7.  **Add extra outputs (optional)**: In **Settings → Multi-platform Destinations**, add YouTube with `rtmp://a.rtmp.youtube.com/live2` and its stream key, or supply any valid custom `rtmp://`/`rtmps://` server URL and stream key. Add or change destinations only while the broadcast is stopped.

## Troubleshooting

*   **FFmpeg not found**: Ensure FFmpeg is correctly installed and accessible in your system's PATH.
*   **Facebook API errors**: Double-check your `PAGE_ACCESS_TOKEN` and `PAGE_ID`. Ensure the token has the necessary permissions.
*   **Port in use**: If port 5000 is already in use, change the `PORT` variable in your `.env` file.
