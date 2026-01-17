"""
RunPod Serverless Handler - YouTube Manifest Extractor

Takes a YouTube URL and returns:
- Video manifest (fragments URLs for ≤720p)
- Audio manifest (fragments URLs for best audio)

Uses yt-dlp installed via pip with deno for n-parameter challenge.
Supports cookies via URL parameter to bypass bot detection.
"""

import runpod
import subprocess
import json
import os
import sys
import urllib.request

# Cookies file path (downloaded at runtime)
COOKIES_PATH = '/tmp/cookies.txt'


def download_cookies(cookies_url: str) -> str:
    """
    Download cookies file from URL to /tmp/cookies.txt.
    Returns path to cookies file or None if failed.
    """
    if not cookies_url:
        return None

    print(f"[Cookies] Downloading from: {cookies_url[:50]}...")

    try:
        urllib.request.urlretrieve(cookies_url, COOKIES_PATH)

        # Verify file was downloaded
        if os.path.exists(COOKIES_PATH):
            size = os.path.getsize(COOKIES_PATH)
            print(f"[Cookies] Downloaded: {size} bytes")
            return COOKIES_PATH
        else:
            print("[Cookies] Download failed: file not created")
            return None
    except Exception as e:
        print(f"[Cookies] Download error: {e}")
        return None


def get_video_info(url: str, cookies_path: str = None) -> dict:
    """
    Extract video info with all format details using yt-dlp.
    Returns the full JSON info from yt-dlp.
    """
    cmd = [
        'yt-dlp',
        '--dump-json',
        '--no-download',
        '--remote-components', 'ejs:github',  # deno for n-parameter
    ]

    # Add cookies if available
    if cookies_path and os.path.exists(cookies_path):
        cmd.extend(['--cookies', cookies_path])
        print(f"[yt-dlp] Using cookies: {cookies_path}")

    cmd.append(url)

    print(f"[yt-dlp] Extracting info: {url}")
    print(f"[yt-dlp] Command: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        raise Exception(f"yt-dlp error: {result.stderr[-1000:]}")

    # Parse JSON output
    info = json.loads(result.stdout)
    return info


def select_best_video_format(formats: list, max_height: int = 720) -> dict:
    """
    Select the best video format with height ≤ max_height.
    Prefers formats with both video codec and highest resolution.
    """
    video_formats = [
        f for f in formats
        if f.get('vcodec') != 'none'
        and f.get('height') is not None
        and f.get('height') <= max_height
    ]

    if not video_formats:
        raise Exception(f"No video format found with height ≤ {max_height}")

    # Sort by height (descending), then by tbr (total bitrate, descending)
    video_formats.sort(
        key=lambda f: (f.get('height', 0), f.get('tbr', 0) or 0),
        reverse=True
    )

    return video_formats[0]


def select_best_audio_format(formats: list) -> dict:
    """
    Select the best audio-only format.
    Prefers m4a/aac for compatibility.
    """
    audio_formats = [
        f for f in formats
        if f.get('vcodec') == 'none'
        and f.get('acodec') != 'none'
    ]

    if not audio_formats:
        raise Exception("No audio-only format found")

    # Prefer m4a, then sort by abr (audio bitrate)
    def audio_score(f):
        ext_score = 1 if f.get('ext') == 'm4a' else 0
        abr = f.get('abr', 0) or 0
        return (ext_score, abr)

    audio_formats.sort(key=audio_score, reverse=True)

    return audio_formats[0]


def extract_fragment_urls(format_info: dict) -> list:
    """
    Extract fragment URLs from a format.
    Works with HLS and DASH formats.
    """
    fragments = format_info.get('fragments', [])

    if fragments:
        # HLS/DASH with fragments
        return [f.get('url') or f.get('path') for f in fragments if f.get('url') or f.get('path')]

    # Single URL (progressive format)
    url = format_info.get('url')
    if url:
        return [url]

    return []


def create_manifest(format_info: dict, fragments: list) -> dict:
    """
    Create a manifest dict with format info and fragment URLs.
    """
    return {
        'format_id': format_info.get('format_id'),
        'ext': format_info.get('ext'),
        'resolution': f"{format_info.get('width', '?')}x{format_info.get('height', '?')}",
        'height': format_info.get('height'),
        'width': format_info.get('width'),
        'fps': format_info.get('fps'),
        'vcodec': format_info.get('vcodec'),
        'acodec': format_info.get('acodec'),
        'tbr': format_info.get('tbr'),
        'abr': format_info.get('abr'),
        'filesize': format_info.get('filesize') or format_info.get('filesize_approx'),
        'fragment_count': len(fragments),
        'fragments': fragments,
        # Direct URL if available (for progressive formats)
        'url': format_info.get('url') if not fragments else None,
    }


def handler(event):
    """
    RunPod Serverless handler.

    Input:
        {
            "url": "https://www.youtube.com/watch?v=...",
            "max_video_height": 720  # optional, default 720
        }

    Output:
        {
            "title": "Video Title",
            "duration": 123,
            "video_manifest": { ... },
            "audio_manifest": { ... }
        }
    """
    try:
        input_data = event.get('input', {})
        url = input_data.get('url')
        max_height = input_data.get('max_video_height', 720)
        cookies_url = input_data.get('cookies_url')  # Optional: URL to cookies file

        if not url:
            return {'error': 'Missing required parameter: url'}

        print(f"[Handler] Processing URL: {url}")
        print(f"[Handler] Max video height: {max_height}")
        print(f"[Handler] Cookies URL: {'provided' if cookies_url else 'none'}")

        # Download cookies if URL provided
        cookies_path = None
        if cookies_url:
            cookies_path = download_cookies(cookies_url)

        # Check yt-dlp version
        version_result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        print(f"[yt-dlp] Version: {version_result.stdout.strip()}")

        # Check deno
        deno_result = subprocess.run(['which', 'deno'], capture_output=True, text=True)
        print(f"[deno] Path: {deno_result.stdout.strip() or 'NOT FOUND'}")

        # Extract video info
        info = get_video_info(url, cookies_path)

        title = info.get('title', 'Unknown')
        duration = info.get('duration', 0)
        formats = info.get('formats', [])

        print(f"[Handler] Title: {title}")
        print(f"[Handler] Duration: {duration}s")
        print(f"[Handler] Formats available: {len(formats)}")

        # Select best video format (≤720p)
        video_format = select_best_video_format(formats, max_height)
        print(f"[Handler] Selected video: {video_format.get('format_id')} - {video_format.get('height')}p")

        # Select best audio format
        audio_format = select_best_audio_format(formats)
        print(f"[Handler] Selected audio: {audio_format.get('format_id')} - {audio_format.get('ext')}")

        # Extract fragment URLs
        video_fragments = extract_fragment_urls(video_format)
        audio_fragments = extract_fragment_urls(audio_format)

        print(f"[Handler] Video fragments: {len(video_fragments)}")
        print(f"[Handler] Audio fragments: {len(audio_fragments)}")

        # Create manifests
        video_manifest = create_manifest(video_format, video_fragments)
        audio_manifest = create_manifest(audio_format, audio_fragments)

        return {
            'title': title,
            'duration': duration,
            'thumbnail': info.get('thumbnail'),
            'video_manifest': video_manifest,
            'audio_manifest': audio_manifest,
        }

    except Exception as e:
        print(f"[Handler] Error: {e}")
        return {'error': str(e)}


# Start RunPod Serverless
if __name__ == '__main__':
    runpod.serverless.start({'handler': handler})
