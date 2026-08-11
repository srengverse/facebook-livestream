import requests
import logging

class FacebookAPI:
    def __init__(self, db):
        self.db = db
        self.base_url = "https://graph.facebook.com/v19.0"
        self.logger = logging.getLogger("FacebookAPI")

    def get_credentials(self):
        import os
        token = self.db.get_setting('PAGE_ACCESS_TOKEN') or os.getenv('PAGE_ACCESS_TOKEN')
        page_id = self.db.get_setting('PAGE_ID') or os.getenv('PAGE_ID')
        return token, page_id

    def get_page_info(self):
        token, page_id = self.get_credentials()
        if not token or not page_id:
            return None
        
        # Security: Validate page_id is alphanumeric
        if not str(page_id).isalnum():
            self.db.log('ERROR', "Security: Invalid Page ID format detected")
            return None

        url = f"{self.base_url}/{page_id}"
        params = {
            'access_token': token,
            'fields': 'name,about,fan_count'
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            
            error_data = response.json().get('error', {})
            self.db.log('ERROR', f"FB API Info Error: {error_data.get('message', 'Unknown error')}")
            return None
        except (requests.exceptions.RequestException, ValueError) as e:
            self.db.log('ERROR', f"FB API Connection Error: {str(e)}")
            return None

    def create_live_video(self, title="Live Stream", description="Streaming from platform"):
        token, page_id = self.get_credentials()
        if not token or not page_id:
            return None
        
        url = f"{self.base_url}/{page_id}/live_videos"
        data = {
            'access_token': token,
            'title': title,
            'description': description,
            'status': 'LIVE_NOW'
        }
        
        try:
            response = requests.post(url, data=data, timeout=15)
            if response.status_code == 200:
                return response.json()
            
            # Log error but mask the token if it appears in response
            error_msg = response.text.replace(token, "REDACTED") if token else response.text
            self.db.log('ERROR', f"FB API Create Live Error: {error_msg}")
            return None
        except requests.exceptions.RequestException as e:
            self.db.log('ERROR', f"FB API Request Exception: {str(e)}")
            return None

    def end_live_video(self, live_video_id):
        token, _ = self.get_credentials()
        if not token or not live_video_id:
            return False
        
        url = f"{self.base_url}/{live_video_id}"
        data = {
            'access_token': token,
            'end_live_video': True
        }
        
        try:
            response = requests.post(url, data=data, timeout=10)
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            self.db.log('ERROR', f"FB API End Live Error: {str(e)}")
            return False
