import requests
import logging
import time
from urllib.parse import urljoin
from config import Config

class FacebookAPI:
    def __init__(self, db):
        self.db = db
        self.logger = logging.getLogger("FacebookAPI")
        self.version = Config.FACEBOOK_GRAPH_API_VERSION
        self.timeout = Config.FACEBOOK_API_TIMEOUT
        self.base_url = f"https://graph.facebook.com/{self.version}"

    def get_credentials(self):
        import os
        token = self.db.get_setting('PAGE_ACCESS_TOKEN') or os.getenv('PAGE_ACCESS_TOKEN')
        page_id = self.db.get_setting('PAGE_ID') or os.getenv('PAGE_ID')
        return token, page_id

    def _request(self, method, endpoint, params=None, data=None, retries=2, backoff=2):
        """Internal helper for robust HTTP requests to Graph API."""
        token, _ = self.get_credentials()
        if not token:
            return None, "Missing Facebook Page Access Token."

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # Ensure access_token is always included
        if params is None: params = {}
        params['access_token'] = token

        for attempt in range(retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    timeout=(5, self.timeout)  # (connect timeout, read timeout)
                )
                
                # Check for rate limiting or temporary server errors
                if response.status_code in [429, 500, 502, 503, 504] and attempt < retries:
                    time.sleep(backoff * (attempt + 1))
                    continue
                
                try:
                    result = response.json()
                except ValueError:
                    return None, f"Invalid JSON response from Facebook (HTTP {response.status_code})."

                if response.status_code == 200:
                    return result, None

                # Handle Graph API specific errors
                error = result.get('error', {})
                error_msg = error.get('message', 'Unknown Facebook API error')
                error_code = error.get('code')
                error_subcode = error.get('error_subcode')
                
                # Log specific error types without exposing token
                log_msg = f"FB API Error {error_code} ({error_subcode}): {error_msg}"
                self.logger.error(log_msg)
                
                # Categorize errors for better handling upstream
                if error_code in [102, 190] or error_subcode in [458, 459, 460, 463, 467]:
                    return None, f"AUTH_ERROR: {error_msg}"
                if error_code in [10, 200, 210, 298]:
                    return None, f"PERMISSION_ERROR: {error_msg}"
                
                return None, error_msg

            except requests.exceptions.Timeout:
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
                    continue
                return None, "Facebook API request timed out."
            except requests.exceptions.RequestException as e:
                return None, f"Facebook API connection error: {str(e)}"
        
        return None, "Maximum retries exceeded for Facebook API."

    def get_page_info(self):
        _, page_id = self.get_credentials()
        if not page_id:
            return None
        
        # Security: Validate page_id is alphanumeric
        if not str(page_id).isalnum():
            self.db.log('ERROR', "Security: Invalid Page ID format detected")
            return None

        result, error = self._request('GET', str(page_id), params={'fields': 'name,about,fan_count'})
        if error:
            self.db.log('ERROR', f"FB API Info Error: {error}")
            return None
        return result

    def create_live_video(self, title="Live Stream", description="Streaming from platform"):
        _, page_id = self.get_credentials()
        if not page_id:
            return None
        
        # Destructive operation: only 1 retry for safety
        data = {
            'title': title,
            'description': description,
            'status': 'LIVE_NOW'
        }
        
        result, error = self._request('POST', f"{page_id}/live_videos", data=data, retries=1)
        if error:
            self.db.log('ERROR', f"FB API Create Live Error: {error}")
            return None
        
        # Robust validation of response
        if not result or 'id' not in result or ('stream_url' not in result and 'secure_stream_url' not in result):
            self.db.log('ERROR', "FB API Create Live: Invalid response structure")
            return None
            
        return result

    def end_live_video(self, live_video_id):
        if not live_video_id:
            return False
        
        # Idempotent-ish: end_live_video=True
        data = {'end_live_video': True}
        
        result, error = self._request('POST', str(live_video_id), data=data, retries=1)
        
        if error:
            # If the video is already ended, Facebook might return an error.
            # We treat "already ended" or "not found" as a success for idempotency.
            if "already ended" in error.lower() or "not found" in error.lower():
                return True
            self.db.log('ERROR', f"FB API End Live Error: {error}")
            return False
            
        return True
