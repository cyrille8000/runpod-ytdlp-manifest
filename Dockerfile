# RunPod Serverless - YouTube Manifest Extractor
# Extracts HLS fragment URLs for video (≤720p) and audio

FROM python:3.11-slim

WORKDIR /

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install deno (for yt-dlp n-parameter challenge)
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

# Verify deno installation
RUN deno --version

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    runpod \
    yt-dlp

# Verify yt-dlp installation
RUN yt-dlp --version

# Copy handler
COPY handler.py /handler.py

# Start serverless handler
CMD ["python3", "-u", "/handler.py"]
