FROM python:3.11-slim

# Install FFmpeg, slab-serif (Courier/FreeMono) & sans-serif broadcast fonts, CA certificates, and tzdata
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-courier-prime \
    fonts-freefont-ttf \
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

RUN mkdir -p /tmp/hls /app/data

EXPOSE 8080

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HLS_DIR=/tmp/hls \
    DATA_DIR=/app/data

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
