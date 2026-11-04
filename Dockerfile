FROM python:3.11-slim

# Install FFmpeg, monospace broadcast fonts, CA certificates, and timezone data
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-liberation \
    ca-certificates \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /tmp/hls

EXPOSE 8080

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HLS_DIR=/tmp/hls

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
