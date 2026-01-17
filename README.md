# RunPod Serverless - YouTube Manifest Extractor

Extrait les URLs des fragments HLS pour télécharger vidéo et audio séparément depuis YouTube.

## Fonctionnalités

- Extraction des URLs de téléchargement vidéo (≤720p) et audio
- Support des cookies pour contourner la détection bot YouTube
- Déchiffrement du n-parameter via deno
- Déploiement automatique via GitHub Actions

## Build automatique (GitHub Actions)

Push sur `main` → GitHub Actions build et push vers `ghcr.io`

```bash
# Image disponible à:
ghcr.io/cyrille8000/runpod-ytdlp-manifest:latest
```

## Build manuel (optionnel)

```bash
docker build --platform linux/amd64 -t ghcr.io/cyrille8000/runpod-ytdlp-manifest:latest .
docker push ghcr.io/cyrille8000/runpod-ytdlp-manifest:latest
```

## Déploiement RunPod

1. Aller sur [RunPod Serverless](https://www.runpod.io/console/serverless)
2. Créer un nouveau endpoint
3. Image: `ghcr.io/cyrille8000/runpod-ytdlp-manifest:latest`
4. GPU: Non requis (CPU uniquement)

## API

### Endpoint

```
POST https://api.runpod.ai/v2/{endpoint_id}/run
Authorization: Bearer {api_key}
Content-Type: application/json
```

### Input

```json
{
    "input": {
        "url": "https://www.youtube.com/watch?v=VIDEO_ID",
        "max_video_height": 720,
        "cookies_url": "https://example.com/cookies.txt"
    }
}
```

| Paramètre | Type | Requis | Description |
|-----------|------|--------|-------------|
| `url` | string | Oui | URL YouTube |
| `max_video_height` | int | Non | Hauteur max vidéo (défaut: 720) |
| `cookies_url` | string | Non | URL publique vers fichier cookies Netscape |

### Output

```json
{
    "title": "Video Title",
    "duration": 1715,
    "thumbnail": "https://i.ytimg.com/vi/VIDEO_ID/maxresdefault.webp",
    "video_manifest": {
        "format_id": "95-11",
        "ext": "mp4",
        "resolution": "1280x720",
        "height": 720,
        "width": 1280,
        "fps": 30,
        "vcodec": "avc1.4D401F",
        "tbr": 1321.861,
        "fragment_count": 1,
        "fragments": [
            "https://manifest.googlevideo.com/api/manifest/hls_playlist/..."
        ]
    },
    "audio_manifest": {
        "format_id": "140-9",
        "ext": "m4a",
        "abr": 129.476,
        "acodec": "mp4a.40.2",
        "filesize": 27756910,
        "fragment_count": 1,
        "fragments": [
            "https://rr2---sn-xxx.googlevideo.com/videoplayback?..."
        ]
    }
}
```

### Vérifier le statut

```bash
curl https://api.runpod.ai/v2/{endpoint_id}/status/{job_id} \
  -H "Authorization: Bearer {api_key}"
```

## Exemple d'utilisation

```bash
# Lancer un job
curl -X POST "https://api.runpod.ai/v2/vrfyem3ikgynkd/run" \
  -H "Authorization: Bearer rpa_xxx" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "max_video_height": 720,
      "cookies_url": "https://files.example.com/cookies.txt"
    }
  }'

# Réponse
{"id":"abc123","status":"IN_QUEUE"}

# Vérifier le statut
curl "https://api.runpod.ai/v2/vrfyem3ikgynkd/status/abc123" \
  -H "Authorization: Bearer rpa_xxx"
```

## Cookies YouTube

Les cookies sont nécessaires pour contourner la détection bot de YouTube sur les IPs de datacenter.

### Exporter les cookies

1. Installer l'extension [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. Aller sur youtube.com et se connecter
3. Cliquer sur l'extension → "Export"
4. Uploader le fichier sur un stockage public (R2, S3, etc.)

### Format Netscape

```
# Netscape HTTP Cookie File
.youtube.com	TRUE	/	TRUE	1234567890	LOGIN_INFO	xxx
.youtube.com	TRUE	/	FALSE	1234567890	SID	xxx
...
```

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Client    │────▶│  RunPod Worker   │────▶│   YouTube   │
│             │     │                  │     │             │
│  - URL      │     │  - yt-dlp        │     │  - HLS URLs │
│  - Cookies  │     │  - deno          │     │  - Metadata │
└─────────────┘     └──────────────────┘     └─────────────┘
```

## Performances

| Métrique | Valeur |
|----------|--------|
| Cold start | ~3-5s |
| Extraction | ~2-3s |
| Total | ~5-8s |

## Coûts RunPod Serverless

- CPU uniquement: ~$0.00025/seconde
- Par requête (~5s): ~$0.00125
- 1000 requêtes: ~$1.25

## Test local

```bash
# Installer les dépendances
pip install runpod yt-dlp

# Installer deno
curl -fsSL https://deno.land/install.sh | sh

# Lancer en mode test
python handler.py --test_input test_input.json
```

## Fichiers

```
runpod-ytdlp-manifest/
├── handler.py              # Handler RunPod Serverless
├── Dockerfile              # Image Docker (Python 3.11 + yt-dlp + deno)
├── test_input.json         # Input de test
├── README.md               # Documentation
├── .gitignore
└── .github/
    └── workflows/
        └── docker-build.yml  # GitHub Actions CI/CD
```

## Limitations

- URLs YouTube uniquement (pas TikTok, Vimeo, etc.)
- Les URLs de fragments expirent après ~6 heures
- Cookies peuvent expirer ou être invalidés par YouTube
- Vidéo max 720p (configurable)

## Troubleshooting

### "Sign in to confirm you're not a bot"

Les cookies sont requis. Assurez-vous que:
1. `cookies_url` pointe vers un fichier valide
2. Les cookies ne sont pas expirés
3. Le compte YouTube n'est pas banni

### URLs de fragments qui ne fonctionnent pas

Les URLs expirent après ~6 heures. Relancer l'extraction si nécessaire.

### Timeout

Augmenter le timeout RunPod ou vérifier que la vidéo existe.
