# RunPod Serverless - YouTube Manifest Extractor

Extrait les URLs des fragments HLS pour télécharger vidéo et audio séparément.

## Build automatique (GitHub Actions)

Push sur `main` → GitHub Actions build et push vers `ghcr.io`

```bash
# Image disponible à:
ghcr.io/<ton-username>/runpod-ytdlp-manifest:latest
```

## Build manuel (optionnel)

```bash
docker build --platform linux/amd64 -t ghcr.io/<username>/runpod-ytdlp-manifest:latest .
docker push ghcr.io/<username>/runpod-ytdlp-manifest:latest
```

## Input

```json
{
    "input": {
        "url": "https://www.youtube.com/watch?v=...",
        "max_video_height": 720
    }
}
```

## Output

```json
{
    "title": "Video Title",
    "duration": 123,
    "thumbnail": "https://...",
    "video_manifest": {
        "format_id": "136",
        "ext": "mp4",
        "resolution": "1280x720",
        "height": 720,
        "fragment_count": 150,
        "fragments": [
            "https://rr1---sn-xxx.googlevideo.com/videoplayback?...",
            "https://rr1---sn-xxx.googlevideo.com/videoplayback?...",
            ...
        ]
    },
    "audio_manifest": {
        "format_id": "140",
        "ext": "m4a",
        "abr": 128,
        "fragment_count": 150,
        "fragments": [
            "https://rr1---sn-xxx.googlevideo.com/videoplayback?...",
            ...
        ]
    }
}
```

## Test local

```bash
# Installer les dépendances
pip install runpod yt-dlp

# Lancer en mode test
python handler.py --test_input test_input.json
```
