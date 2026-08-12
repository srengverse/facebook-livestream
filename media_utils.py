import subprocess
import json
import os
import shutil

def get_media_info(filepath):
    """Use ffprobe to get media information and validate the file."""
    try:
        cmd = [
            'ffprobe', 
            '-v', 'quiet', 
            '-print_format', 'json', 
            '-show_format', 
            '-show_streams', 
            filepath
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return None
        
        data = json.loads(result.stdout)
        if not data or 'format' not in data:
            return None
            
        # Basic validation: must have at least one video stream
        streams = data.get('streams', [])
        has_video = any(s.get('codec_type') == 'video' for s in streams)
        if not has_video:
            return None
            
        return data
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return None

def has_sufficient_space(directory, required_bytes):
    """Check if the disk has enough space for the upload."""
    try:
        total, used, free = shutil.disk_usage(directory)
        # Keep a 50MB buffer
        return free > (required_bytes + 50 * 1024 * 1024)
    except OSError:
        return False

def is_valid_video(filepath):
    """Perform a deep check of the video file."""
    info = get_media_info(filepath)
    if not info:
        return False, "Invalid or corrupted video file"
    
    # We could add more checks here (bitrate, resolution, etc.)
    return True, info
