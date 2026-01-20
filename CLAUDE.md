# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube video/audio manifest URL extractor using yt-dlp. Part of a larger video dubbing platform - this microservice provides direct download URLs for video (≤720p) and audio streams.

**Deployment**: FastAPI server on Oracle Cloud ARM64 instance (always-on, port 8080)

## OCI Instance

| Spec | Value |
|------|-------|
| Shape | VM.Standard.A1.Flex |
| CPU | 4 OCPU ARM Ampere A1 |
| RAM | 24 GB |
| OS | Ubuntu 24.04 (ARM64) |
| Port | 8080 |

## Commands

### Deployment

```bash
# Copy files to OCI
scp -i ssh-key-2026-01-20.key handler_api.py Dockerfile.oci requirements.txt ubuntu@<IP>:~/

# SSH and build
ssh -i ssh-key-2026-01-20.key ubuntu@<IP>
sudo docker build -f Dockerfile.oci -t ytdlp-api .
sudo docker run -d -p 8080:8080 --name ytdlp-api --restart unless-stopped ytdlp-api

# Logs
sudo docker logs -f ytdlp-api
```

### Local Development

```bash
pip install -r requirements.txt
curl -fsSL https://deno.land/install.sh | sh
python handler_api.py
```

## Architecture

```
Client → POST /extract → FastAPI (async) → yt-dlp → YouTube
                              ↓
                    Returns: video_manifest, audio_manifest
                    (fragment URLs valid ~6 hours)
```

**Stateless**: No files stored on server (except cookies in /tmp).

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/stats` | Server statistics (active, total, failed) |
| POST | `/extract` | Extract video/audio manifests |
| POST | `/orchestrateur-gpu` | GPU orchestrator (TODO) |

### POST /extract

```json
{
    "url": "https://www.youtube.com/watch?v=...",
    "max_video_height": 720
}
```

## Concurrency Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| `MAX_CONCURRENT_EXTRACTIONS` | 60 | Max simultaneous yt-dlp processes |
| `EXTRACTION_TIMEOUT` | 120s | Timeout per extraction |
| `QUEUE_TIMEOUT` | 120s | Max wait in queue before 503 |

**Capacity**: ~1000 requests handled in ~2min 15s (7.5 req/sec throughput).

## Background Tasks

| Task | Interval | Description |
|------|----------|-------------|
| Cookies refresh | 1 hour | Downloads cookies from `files.dubbingspark.com` |
| yt-dlp update | 24 hours | Updates yt-dlp via pip |

## Files

| File | Description |
|------|-------------|
| `handler_api.py` | FastAPI server (main) |
| `Dockerfile.oci` | ARM64 Docker image |
| `requirements.txt` | Python dependencies |
| `handler.py` | RunPod handler (legacy) |
| `Dockerfile` | RunPod image (legacy) |

## Format Selection Priority

- Video: webm (VP9) > mp4 (H.264), DASH > direct URL > HLS
- Audio: m4a preferred, sorted by bitrate
