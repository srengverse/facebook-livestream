# Deployment Guide

This guide provides instructions for deploying the Facebook Live Streaming Platform to various environments.

## Prerequisites

*   A server running Ubuntu (or a similar Linux distribution).
*   `git` installed on your server.
*   `docker` and `docker-compose` installed (for Docker deployments).
*   `nginx` installed (for reverse proxy setup).

## Deployment Options

### 1. Using Docker and Docker Compose (Recommended)

This is the recommended method for deployment as it encapsulates all dependencies and provides an isolated environment.

1.  **Clone the repository on your server**:
    ```bash
    git clone https://github.com/your-username/facebook-live.git
    cd facebook-live
    ```

2.  **Create `.env` file**:
    Copy the `.env.example` to `.env` and configure your Facebook API credentials and other settings as described in `INSTALLATION.md`.
    ```bash
    cp .env.example .env
    ```

3.  **Build and run with Docker Compose**:
    ```bash
    docker-compose up --build -d
    ```
    This will build the Docker image, create the `web` service, and run it in detached mode. The application will be accessible on port `5000` of your server.

4.  **Verify deployment**:
    Check if the containers are running:
    ```bash
    docker-compose ps
    ```
    You should see the `web` service listed as `Up`.

### 2. Using systemd (for bare-metal or VPS)

This method is suitable if you prefer to run the application directly on your server with `gunicorn` and manage it using `systemd`.

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-username/facebook-live.git
    cd facebook-live
    ```

2.  **Create and activate a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Python dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Install FFmpeg**:
    ```bash
    sudo apt update
    sudo apt install ffmpeg -y
    ```

5.  **Configure environment variables**:
    Create the `.env` file as described in `INSTALLATION.md`.
    ```bash
    cp .env.example .env
    ```

6.  **Setup systemd service**:
    Copy the provided `facebook-live.service` file to `/etc/systemd/system/`:
    ```bash
    sudo cp facebook-live.service /etc/systemd/system/
    ```
    Reload systemd, enable, and start the service:
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable facebook-live
    sudo systemctl start facebook-live
    ```

7.  **Check service status**:
    ```bash
    sudo systemctl status facebook-live
    ```

### 3. Nginx Reverse Proxy (Optional but Recommended)

For production deployments, it's highly recommended to use Nginx as a reverse proxy to handle SSL, serve static files, and manage traffic.

1.  **Install Nginx**:
    ```bash
    sudo apt update
    sudo apt install nginx -y
    ```

2.  **Configure Nginx**:
    Copy the provided `nginx.conf` to `/etc/nginx/sites-available/` and create a symlink to `sites-enabled`.
    **Remember to replace `your_domain.com` with your actual domain name in `nginx.conf`**.
    ```bash
    sudo cp nginx.conf /etc/nginx/sites-available/facebook-live
    sudo ln -s /etc/nginx/sites-available/facebook-live /etc/nginx/sites-enabled/
    sudo rm /etc/nginx/sites-enabled/default # Remove default Nginx config if it exists
    ```

3.  **Test Nginx configuration and restart**:
    ```bash
    sudo nginx -t
    sudo systemctl restart nginx
    ```

4.  **Configure Firewall (UFW)**:
    Allow HTTP and HTTPS traffic:
    ```bash
    sudo ufw allow 'Nginx Full'
    sudo ufw enable
    ```

## Troubleshooting Deployment

*   **Port Conflicts**: Ensure no other services are running on the same ports (e.g., 5000 for Flask/Gunicorn, 80/443 for Nginx).
*   **Permissions**: Verify that the user running the application (e.g., `ubuntu` for systemd, or the Docker user) has appropriate read/write permissions for the project directory, especially `uploads/` and `logs/`.
*   **Logs**: Check application logs (`/home/ubuntu/facebook-live/logs/` or Docker container logs) and systemd journal (`journalctl -u facebook-live.service`) for errors.
*   **Facebook API**: Ensure your server's IP address is whitelisted in your Facebook Developer App settings if you encounter API connection issues.

---

**Manus AI**
