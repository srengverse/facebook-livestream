import requests

class FacebookAPI:
    def __init__(self, db):
        self.db = db
        self.base_url = "https://graph.facebook.com/v19.0"

    def get_credentials(self):
        token = self.db.get_setting('PAGE_ACCESS_TOKEN')
        page_id = self.db.get_setting('PAGE_ID')
        return token, page_id

    def get_page_info(self):
        token, page_id = self.get_credentials()
        if not token or not page_id:
            return None
        
        url = f"{self.base_url}/{page_id}?access_token={token}&fields=name,about,fan_count"
        try:
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            self.db.log('ERROR', f"FB API Error: {str(e)}")
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
            'status': 'LIVE_NOW' # or 'UNPUBLISHED' then go live
        }
        
        try:
            response = requests.post(url, data=data)
            if response.status_code == 200:
                return response.json()
            self.db.log('ERROR', f"FB API Create Live Error: {response.text}")
            return None
        except Exception as e:
            self.db.log('ERROR', f"FB API Error: {str(e)}")
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
            response = requests.post(url, data=data)
            return response.status_code == 200
        except Exception as e:
            self.db.log('ERROR', f"FB API End Live Error: {str(e)}")
            return False
