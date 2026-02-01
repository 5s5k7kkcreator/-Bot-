import os
import re
import logging
from typing import Optional, List, Dict, Tuple
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY')

def get_youtube_service():
    if not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY is not set")
    return build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

def extract_playlist_id(url: str) -> Optional[str]:
    patterns = [
        r'[?&]list=([a-zA-Z0-9_-]+)',
        r'playlist\?list=([a-zA-Z0-9_-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    if re.match(r'^[a-zA-Z0-9_-]+$', url) and len(url) > 10:
        return url
    
    return None

def validate_playlist(playlist_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
    try:
        youtube = get_youtube_service()
        request = youtube.playlists().list(
            part='snippet',
            id=playlist_id
        )
        response = request.execute()
        
        if response.get('items'):
            title = response['items'][0]['snippet']['title']
            return True, title, None
        else:
            return False, None, "Playlist not found or is private"
            
    except HttpError as e:
        logger.error(f"YouTube API error: {e}")
        if e.resp.status == 403:
            return False, None, "API quota exceeded or access denied"
        elif e.resp.status == 404:
            return False, None, "Playlist not found"
        else:
            return False, None, f"API error: {e.resp.status}"
    except ValueError as e:
        return False, None, str(e)
    except Exception as e:
        logger.error(f"Error validating playlist: {e}")
        return False, None, f"Unexpected error: {str(e)}"

def get_playlist_videos(playlist_id: str, max_results: int = 50) -> Tuple[List[Dict], Optional[str]]:
    try:
        youtube = get_youtube_service()
        videos = []
        next_page_token = None
        position = 0
        
        while True:
            request = youtube.playlistItems().list(
                part='snippet,contentDetails',
                playlistId=playlist_id,
                maxResults=min(50, max_results - len(videos)),
                pageToken=next_page_token
            )
            response = request.execute()
            
            for item in response.get('items', []):
                snippet = item['snippet']
                video_id = snippet['resourceId']['videoId']
                
                videos.append({
                    'video_id': video_id,
                    'title': snippet.get('title', 'Unknown'),
                    'channel_name': snippet.get('videoOwnerChannelTitle', 'Unknown'),
                    'position': position,
                    'url': f'https://www.youtube.com/watch?v={video_id}'
                })
                position += 1
            
            next_page_token = response.get('nextPageToken')
            if not next_page_token or len(videos) >= max_results:
                break
        
        return videos, None
        
    except HttpError as e:
        logger.error(f"YouTube API error fetching videos: {e}")
        if e.resp.status == 403:
            return [], "API quota exceeded"
        elif e.resp.status == 404:
            return [], "Playlist not found"
        else:
            return [], f"API error: {e.resp.status}"
    except ValueError as e:
        return [], str(e)
    except Exception as e:
        logger.error(f"Error fetching playlist videos: {e}")
        return [], f"Unexpected error: {str(e)}"

def compare_videos(old_videos: List[Dict], new_videos: List[Dict]) -> Dict[str, List[Dict]]:
    changes = {
        'added': [],
        'removed': [],
        'title_changed': []
    }
    
    old_video_map = {v['video_id']: v for v in old_videos}
    new_video_map = {v['video_id']: v for v in new_videos}
    
    for video_id, video in new_video_map.items():
        if video_id not in old_video_map:
            changes['added'].append(video)
        elif video['title'] != old_video_map[video_id]['title']:
            changes['title_changed'].append({
                'video_id': video_id,
                'old_title': old_video_map[video_id]['title'],
                'new_title': video['title'],
                'channel_name': video['channel_name'],
                'url': video['url']
            })
    
    for video_id, video in old_video_map.items():
        if video_id not in new_video_map:
            changes['removed'].append(video)
    
    return changes
