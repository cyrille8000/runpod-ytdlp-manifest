"""
OCI Docker - YouTube Manifest Extractor API

FastAPI server that extracts YouTube video/audio manifest URLs.
Replaces RunPod serverless handler for always-on OCI deployment.

Endpoints:
- POST /extract - Extract video/audio manifests from YouTube URL
- POST /orchestrateur-gpu - GPU orchestrator (TODO)
- GET /health - Health check
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from typing import Optional
import subprocess
import json
import os
import time
import urllib.request
import uvicorn
import asyncio

# Cookies configuration
COOKIES_URL = "https://files.dubbingspark.com/config/youtube_cookies.txt"
COOKIES_PATH = '/tmp/cookies.txt'
COOKIES_REFRESH_INTERVAL = 3600  # 1 hour in seconds
YTDLP_UPDATE_INTERVAL = 86400  # 24 hours in seconds

# Concurrency configuration (optimized for 4 OCPU / 24GB RAM)
MAX_CONCURRENT_EXTRACTIONS = 80  # Max simultaneous yt-dlp processes
EXTRACTION_TIMEOUT = 120  # Timeout per extraction (seconds)
QUEUE_TIMEOUT = 180  # Max wait time in queue (3 minutes)

# Semaphore to limit concurrent extractions
extraction_semaphore: asyncio.Semaphore = None

# Lock for thread-safe stats updates
stats_lock: asyncio.Lock = None

# Stats for monitoring (protected by stats_lock)
class Stats:
    active_extractions: int = 0
    total_extractions: int = 0
    failed_extractions: int = 0
    queue_full_rejections: int = 0
    peak_concurrent: int = 0  # Max simultaneous extractions seen
    total_extraction_time: float = 0.0  # Sum of all extraction times
    waiting_in_queue: int = 0  # Requests waiting for a slot

stats = Stats()


async def update_ytdlp_task():
    """Background task: update yt-dlp once per day."""
    while True:
        # Wait 24h before first update (yt-dlp is fresh from Docker build)
        await asyncio.sleep(YTDLP_UPDATE_INTERVAL)

        try:
            print("[yt-dlp] Updating via pip...")
            result = subprocess.run(
                ['pip', 'install', '--upgrade', 'yt-dlp'],
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                # Get new version
                version_result = subprocess.run(
                    ['yt-dlp', '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                print(f"[yt-dlp] Updated to version: {version_result.stdout.strip()}")
            else:
                print(f"[yt-dlp] Update failed: {result.stderr[-500:]}")

        except Exception as e:
            print(f"[yt-dlp] Update error: {e}")


async def download_cookies_task():
    """Background task: download cookies every hour."""
    while True:
        try:
            print(f"[Cookies] Downloading from {COOKIES_URL}...")

            # Create request without cache
            req = urllib.request.Request(COOKIES_URL, headers={
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'User-Agent': 'Mozilla/5.0'
            })

            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read()

            with open(COOKIES_PATH, 'wb') as f:
                f.write(content)

            size = os.path.getsize(COOKIES_PATH)
            print(f"[Cookies] Downloaded: {size} bytes")

        except Exception as e:
            print(f"[Cookies] Download error: {e}")

        # Wait 1 hour before next download
        await asyncio.sleep(COOKIES_REFRESH_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    global extraction_semaphore, stats_lock

    # Initialize semaphore and lock for concurrency control
    extraction_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
    stats_lock = asyncio.Lock()
    print(f"[Startup] Semaphore initialized: max {MAX_CONCURRENT_EXTRACTIONS} concurrent extractions")

    # Startup: launch background tasks
    print("[Startup] Starting background tasks...")
    cookies_task = asyncio.create_task(download_cookies_task())
    ytdlp_task = asyncio.create_task(update_ytdlp_task())

    # Wait a bit for first cookie download
    await asyncio.sleep(2)

    yield

    # Shutdown: cancel background tasks
    cookies_task.cancel()
    ytdlp_task.cancel()
    print("[Shutdown] Background tasks stopped")


app = FastAPI(
    title="YouTube Manifest Extractor",
    description="Extracts HLS fragment URLs for video and audio from YouTube",
    version="1.0.0",
    lifespan=lifespan
)


# --- Pydantic Models ---

class ExtractRequest(BaseModel):
    url: str
    max_video_height: int = 720


class ManifestInfo(BaseModel):
    format_id: Optional[str]
    ext: Optional[str]
    resolution: Optional[str]
    height: Optional[int]
    width: Optional[int]
    fps: Optional[float]
    vcodec: Optional[str]
    acodec: Optional[str]
    tbr: Optional[float]
    abr: Optional[float]
    filesize: Optional[int]
    fragment_count: int
    fragments: list[str]
    url: Optional[str]


class ExtractResponse(BaseModel):
    title: str
    duration: int
    thumbnail: Optional[str]
    video_manifest: ManifestInfo
    audio_manifest: ManifestInfo


class HealthResponse(BaseModel):
    status: str
    yt_dlp_version: str
    deno_available: bool


# --- Core Functions ---

async def get_video_info(url: str, cookies_path: str = None) -> dict:
    """Extract video info with all format details using yt-dlp (async)."""
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

    # Async subprocess - non-blocking
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=EXTRACTION_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()  # Clean up zombie process
        raise Exception(f"yt-dlp timeout after {EXTRACTION_TIMEOUT}s")

    if proc.returncode != 0:
        raise Exception(f"yt-dlp error: {stderr.decode()[-1000:]}")

    info = json.loads(stdout.decode())
    return info


def select_best_video_format(formats: list, max_height: int = 720) -> dict:
    """Select the best video format with height <= max_height."""
    video_formats = [
        f for f in formats
        if f.get('vcodec') != 'none'
        and f.get('acodec') == 'none'
        and f.get('height') is not None
        and f.get('height') <= max_height
    ]

    if not video_formats:
        video_formats = [
            f for f in formats
            if f.get('vcodec') != 'none'
            and f.get('height') is not None
            and f.get('height') <= max_height
        ]

    if not video_formats:
        raise Exception(f"No video format found with height <= {max_height}")

    def format_score(f):
        height = f.get('height', 0)
        tbr = f.get('tbr', 0) or 0
        ext = f.get('ext', '')

        fragments = f.get('fragments', [])
        has_direct_fragments = len(fragments) > 1 or (
            len(fragments) == 1 and
            fragments[0].get('url', '').startswith('https://') and
            'manifest' not in fragments[0].get('url', '').lower()
        )

        url = f.get('url', '')
        is_hls = 'manifest' in url.lower() or url.endswith('.m3u8')

        if has_direct_fragments:
            url_score = 3
        elif url and not is_hls:
            url_score = 2
        else:
            url_score = 1

        if ext == 'webm':
            ext_score = 2
        elif ext == 'mp4':
            ext_score = 1
        else:
            ext_score = 0

        return (url_score, ext_score, height, tbr)

    video_formats.sort(key=format_score, reverse=True)
    return video_formats[0]


def select_best_audio_format(formats: list) -> dict:
    """Select the best audio-only format."""
    audio_formats = [
        f for f in formats
        if f.get('vcodec') == 'none'
        and f.get('acodec') != 'none'
    ]

    if not audio_formats:
        raise Exception("No audio-only format found")

    def audio_score(f):
        ext_score = 1 if f.get('ext') == 'm4a' else 0
        abr = f.get('abr', 0) or 0
        return (ext_score, abr)

    audio_formats.sort(key=audio_score, reverse=True)
    return audio_formats[0]


def _fetch_hls_segments_sync(manifest_url: str) -> list:
    """Sync helper for fetching HLS manifest (runs in thread pool)."""
    req = urllib.request.Request(manifest_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        content = response.read().decode('utf-8')

    segments = []
    base_url = manifest_url.rsplit('/', 1)[0] + '/'

    for line in content.split('\n'):
        line = line.strip()
        if line and not line.startswith('#'):
            if line.startswith('http'):
                segments.append(line)
            else:
                segments.append(base_url + line)

    return segments


async def fetch_hls_segments(manifest_url: str) -> list:
    """Fetch HLS manifest and extract segment URLs (async, non-blocking)."""
    print(f"[HLS] Fetching manifest: {manifest_url[:80]}...")

    try:
        segments = await asyncio.to_thread(_fetch_hls_segments_sync, manifest_url)
        print(f"[HLS] Found {len(segments)} segments")
        return segments

    except Exception as e:
        print(f"[HLS] Error fetching manifest: {e}")
        return []


async def extract_fragment_urls(format_info: dict, fetch_hls: bool = True) -> list:
    """Extract fragment URLs from a format (async)."""
    fragments = format_info.get('fragments', [])

    if fragments:
        urls = []
        for f in fragments:
            url = f.get('url') or f.get('path')
            if url:
                urls.append(url)

        if len(urls) == 1 and fetch_hls:
            url = urls[0]
            if 'manifest' in url.lower() or '.m3u8' in url.lower():
                hls_segments = await fetch_hls_segments(url)
                if hls_segments:
                    return hls_segments

        return urls

    url = format_info.get('url')
    if url:
        if fetch_hls and ('manifest' in url.lower() or '.m3u8' in url.lower()):
            hls_segments = await fetch_hls_segments(url)
            if hls_segments:
                return hls_segments
        return [url]

    return []


def create_manifest(format_info: dict, fragments: list) -> dict:
    """Create a manifest dict with format info and fragment URLs."""
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
        'url': format_info.get('url') if not fragments else None,
    }


# --- API Endpoints ---

@app.post("/orchestrateur-gpu")
async def orchestrateur_gpu(request: dict):
    """
    Orchestrateur GPU endpoint.
    TODO: Implémenter la logique GPU.
    """
    print(f"[Orchestrateur-GPU] Received request: {request}")
    return {"status": "received", "message": "Orchestrateur GPU - À implémenter"}


@app.get("/stats")
async def get_stats():
    """Server statistics for monitoring."""
    successful = stats.total_extractions - stats.failed_extractions
    avg_time = stats.total_extraction_time / max(successful, 1)
    return {
        "active_extractions": stats.active_extractions,
        "waiting_in_queue": stats.waiting_in_queue,
        "max_concurrent": MAX_CONCURRENT_EXTRACTIONS,
        "peak_concurrent": stats.peak_concurrent,
        "total_extractions": stats.total_extractions,
        "failed_extractions": stats.failed_extractions,
        "queue_full_rejections": stats.queue_full_rejections,
        "success_rate": round(
            successful / max(stats.total_extractions, 1) * 100, 2
        ),
        "avg_extraction_time_seconds": round(avg_time, 2),
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    # Check yt-dlp
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True, timeout=5)
        yt_dlp_version = result.stdout.strip() if result.returncode == 0 else "error"
    except Exception:
        yt_dlp_version = "not found"

    # Check deno
    try:
        result = subprocess.run(['which', 'deno'], capture_output=True, text=True, timeout=5)
        deno_available = result.returncode == 0
    except Exception:
        deno_available = False

    return HealthResponse(
        status="ok",
        yt_dlp_version=yt_dlp_version,
        deno_available=deno_available
    )


@app.post("/extract", response_model=ExtractResponse)
async def extract_manifests(request: ExtractRequest):
    """
    Extract video and audio manifests from YouTube URL.

    Returns fragment URLs for downloading video (<=720p) and audio separately.
    Concurrency is limited to MAX_CONCURRENT_EXTRACTIONS simultaneous requests.
    """
    # Track queue waiting
    async with stats_lock:
        stats.waiting_in_queue += 1

    # Try to acquire semaphore with timeout (don't wait forever)
    try:
        await asyncio.wait_for(
            extraction_semaphore.acquire(),
            timeout=QUEUE_TIMEOUT
        )
    except asyncio.TimeoutError:
        async with stats_lock:
            stats.waiting_in_queue -= 1
            stats.queue_full_rejections += 1
        print(f"[API] Server overloaded - rejected request (active: {stats.active_extractions})")
        raise HTTPException(
            status_code=503,
            detail=f"Server overloaded. {stats.active_extractions} extractions in progress. Retry later."
        )

    # Track stats - got a slot
    start_time = time.time()
    async with stats_lock:
        stats.waiting_in_queue -= 1
        stats.active_extractions += 1
        stats.total_extractions += 1
        if stats.active_extractions > stats.peak_concurrent:
            stats.peak_concurrent = stats.active_extractions

    try:
        print(f"[API] Processing URL: {request.url} (active: {stats.active_extractions}/{MAX_CONCURRENT_EXTRACTIONS})")
        print(f"[API] Max video height: {request.max_video_height}")

        # Extract video info (uses centrally managed cookies)
        info = await get_video_info(request.url, COOKIES_PATH)

        title = info.get('title', 'Unknown')
        duration = info.get('duration', 0)
        formats = info.get('formats', [])

        print(f"[API] Title: {title}")
        print(f"[API] Duration: {duration}s")
        print(f"[API] Formats available: {len(formats)}")

        # Select best formats
        video_format = select_best_video_format(formats, request.max_video_height)
        audio_format = select_best_audio_format(formats)

        print(f"[API] Selected video: {video_format.get('format_id')} - {video_format.get('height')}p")
        print(f"[API] Selected audio: {audio_format.get('format_id')} - {audio_format.get('ext')}")

        # Extract fragment URLs (run in parallel)
        video_fragments, audio_fragments = await asyncio.gather(
            extract_fragment_urls(video_format),
            extract_fragment_urls(audio_format)
        )

        print(f"[API] Video fragments: {len(video_fragments)}")
        print(f"[API] Audio fragments: {len(audio_fragments)}")

        # Create manifests
        video_manifest = create_manifest(video_format, video_fragments)
        audio_manifest = create_manifest(audio_format, audio_fragments)

        return ExtractResponse(
            title=title,
            duration=duration,
            thumbnail=info.get('thumbnail'),
            video_manifest=ManifestInfo(**video_manifest),
            audio_manifest=ManifestInfo(**audio_manifest),
        )

    except HTTPException:
        raise
    except Exception as e:
        async with stats_lock:
            stats.failed_extractions += 1
        print(f"[API] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Always release semaphore and update stats
        extraction_time = time.time() - start_time
        async with stats_lock:
            stats.active_extractions -= 1
            stats.total_extraction_time += extraction_time
        extraction_semaphore.release()


# --- Main ---

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8080)
