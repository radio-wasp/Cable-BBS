# Vintage Cable TV Bulletin Board (`cable-bulletin-hls`) 📺

A lightweight, self-contained Docker container that recreates a **1980s monochrome Cable TV Character Generator & Community Bulletin Board**. It pulls live RSS news feeds from **CBC News** and **CNN**, renders them in **pure greyscale** with authentic CRT scanlines, typewriter text reveal, and a continuous scrolling wire ticker, and outputs a live **HLS stream** (`.m3u8` + `.ts` segments) paired with live radio or vintage CRT audio.

Unlike browser-capture streamers, `cable-bulletin-hls` does **not** use Chromium or Puppeteer. Frames are rendered directly in 8-bit greyscale (`L` mode) using Python's Pillow library and piped straight into FFmpeg, keeping CPU and memory usage minimal for 24/7 operation on Unraid, Docker hosts, or home servers.

---

## Screen Layout & Visual Features

```text
+-------------------------------------------------------------------------+
| [CH 03]  CABLETEXT BULLETIN                      WED NOV 04 06:54:00 PM |
+-------------------------------------------------------------------------+
| [ CBC NEWS ] // TOP STORIES   [CBC-101]                   PAGE 01 OF 28 |
+-------------------------------------------------------------------------+
| +                                                                     + |
|   HEADLINE APPEARS HERE IN BOLD MONOSPACE TELETYPE                      |
|   UP TO THREE LINES HIGH                                                |
|   ===================================================================   |
|   SOURCE: CBC NEWS   //   FILED: NOV 04 18:30   //   REF: CBC-101       |
|                                                                         |
|   DISPATCH SUMMARY BODY TEXT TYPES ONTO THE SCREEN CHARACTER BY         |
|   CHARACTER WITH A BLINKING TERMINAL CURSOR AT THE END OF THE           |
|   BULLETIN DISPATCH █                                                   |
|                                                                         |
|   TELETYPE TERMINAL // CATV-03 WIRE SERVICE          [██████████░░░░]   |
| +                                                                     + |
+-------------------------------------------------------------------------+
| [ CBC / CNN WIRE ] /// [CBC] HEADLINE 1 /// [CNN] HEADLINE 2 /// ...    |
+-------------------------------------------------------------------------+
```

- **Pure Greyscale Broadcast Output**: Rendered natively in 8-bit greyscale (`gray` -> `yuv420p` monochrome H.264) for universal hardware decoding across browsers, Apple TV, Android TV, VLC, Jellyfin, and Dispatcharr.
- **Interleaved CBC & CNN Wire**: Automatically fetches, cleans, and alternates stories between **CBC News** (Top Stories, World, Canada) and **CNN** (Top Stories, World, Latest).
- **Periodic Wire Index Card (`WIRE INDEX`)**: Every `N` stories (default `6`), displays a 5-item tabular headline rundown summarizing upcoming dispatches.
- **Teletype Reveal & Blinking Cursor**: Each card rapidly types onto the screen over the first `1.6s` with a leading block cursor (`█`), then holds for reading while the terminal cursor blinks at the end of the dispatch.
- **Continuous Bottom Crawl**: Smoothly scrolls combined CBC and CNN headlines along the bottom of the screen.
- **Authentic CRT Processing**: Toggleable horizontal scanline attenuation, CRT bezel/corner vignette darkening, and subtle analog RF snow/grain shimmer.
- **Community Access Radio Audio**: Pair the visual bulletin board with any live Icecast/MP3/AAC radio stream (e.g., local FM radio), a subtle 60 Hz CRT transformer hum, or a silent audio track.

---

## Quick Start

### Option 1: Docker Compose (Recommended)

```yaml
services:
  cable-bulletin-hls:
    build: .
    image: cable-bulletin-hls:latest
    container_name: cable-bulletin-hls
    restart: unless-stopped
    ports:
      - "${PORT:-8080}:8080"
    environment:
      - PORT=8080
      - TZ=America/Halifax
      - CHANNEL_NUMBER=03
      - CHANNEL_NAME=CABLETEXT BULLETIN
      - STATION_ID=CATV-03 WIRE SERVICE
      - WIDTH=1280
      - HEIGHT=720
      - FPS=24
      - PAGE_DURATION=12
      - TYPEWRITER_DURATION=1.6
      - TICKER_SPEED=110
      - SCANLINES=true
      - CRT_NOISE=true
      - CRT_VIGNETTE=true
      - AUDIO_MODE=stream
      - AUDIO_STREAM_URL=https://chi-master3-entry1.leanstream-hd.com:2113/CKULFM
      - REFRESH_INTERVAL_MINUTES=10
```

Build and start the container:

```bash
docker compose up -d --build
```

Then open **`http://localhost:8080`** in your browser to view the live greyscale HLS monitor and active wire queue.

### Option 2: Docker CLI

```bash
# Build the image
docker build -t cable-bulletin-hls:latest .

# Run with a live background radio stream
docker run -d \
  --name cable-bulletin-hls \
  --restart unless-stopped \
  -p 8080:8080 \
  -e TZ=America/Halifax \
  -e CHANNEL_NUMBER=03 \
  -e CHANNEL_NAME="CABLETEXT BULLETIN" \
  -e AUDIO_MODE=stream \
  -e AUDIO_STREAM_URL="https://chi-master3-entry1.leanstream-hd.com:2113/CKULFM" \
  cable-bulletin-hls:latest
```

---

## Stream & API Endpoints

| Path | Format | Description |
| :--- | :--- | :--- |
| `/` | `text/html` | Retro greyscale Web UI with embedded `hls.js` player, frame monitor, and live dispatch queue |
| `/hls/stream.m3u8` | `application/vnd.apple.mpegurl` | **Primary HLS stream manifest** (`.m3u8`) |
| `/stream.m3u8` | `application/vnd.apple.mpegurl` | Root alias for `/hls/stream.m3u8` |
| `/hls/seg_XXXXX.ts` | `video/mp2t` | Individual HLS transport stream segments |
| `/live.ts` *(or `/stream`)* | `video/mp2t` | Continuous **MPEG-TS** HTTP stream (shares the same FFmpeg encode with zero extra CPU load) |
| `/playlist.m3u` | `audio/x-mpegurl` | Standard **#EXTM3U** playlist for IPTV clients |
| `/epg.xml` | `application/xml` | Standard **XMLTV EPG** program guide |
| `/preview.png` | `image/png` | Instant greyscale PNG snapshot of the current bulletin frame (also used as channel icon) |
| `/api/status` | `application/json` | JSON telemetry for encoder state, feed counts, and active headlines |
| `/api/refresh` | `application/json` | `POST` endpoint to trigger an immediate RSS feed refresh |
| `/health` | `application/json` | Container healthcheck endpoint |

---

## Dispatcharr / Jellyfin / Plex / VLC Setup

### Dispatcharr or Jellyfin Live TV
1. Add a new **M3U Tuner**:
   - **M3U URL**: `http://<server-ip>:8080/playlist.m3u`
   - *(Or point a custom stream directly to `http://<server-ip>:8080/hls/stream.m3u8` or `http://<server-ip>:8080/live.ts`)*
2. Add an **XMLTV Guide Provider**:
   - **XMLTV URL**: `http://<server-ip>:8080/epg.xml`

### VLC / MPV / Apple TV / IINA
Open Network Stream and enter:
```text
http://<server-ip>:8080/hls/stream.m3u8
```

---

## Audio Modes (`AUDIO_MODE`)

Many HLS and IPTV clients require an audio stream inside the `.ts` container. You can choose between three modes:

1. **`AUDIO_MODE=stream`**:
   Plays an external internet radio stream (Icecast, Shoutcast, MP3, AAC, HLS audio) defined in `AUDIO_STREAM_URL` with automatic reconnect enabled:
   ```yaml
   - AUDIO_MODE=stream
   - AUDIO_STREAM_URL=https://chi-master3-entry1.leanstream-hd.com:2113/CKULFM
   ```
2. **`AUDIO_MODE=hum`**:
   Generates a quiet, low-volume (`volume=0.015`) 60 Hz sine wave via FFmpeg `lavfi` to emulate an analog CRT / modulator hum.
3. **`AUDIO_MODE=silent`**:
   Generates a zero-volume stereo AAC track (`anullsrc`).

---

## Environment Variables Reference

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8080` | HTTP server port inside the container |
| `TZ` | `UTC` | Local timezone for the broadcast clock (e.g. `America/Halifax`, `America/Toronto`) |
| `CHANNEL_NUMBER` | `03` | Channel badge displayed in the top-left header (`CH 03`) |
| `CHANNEL_NAME` | `CABLETEXT BULLETIN` | Main broadcast header banner title |
| `STATION_ID` | `CATV-03 WIRE SERVICE` | Station identifier shown in the card footer and scrolling ticker |
| `WIDTH` | `1280` | Output video width in pixels |
| `HEIGHT` | `720` | Output video height in pixels (fonts and borders scale automatically) |
| `FPS` | `24` | Video frame rate |
| `VIDEO_BITRATE` | `2200k` | Target H.264 video bitrate |
| `HLS_TIME` | `2` | Target duration (seconds) of each `.ts` HLS segment |
| `HLS_LIST_SIZE` | `8` | Number of segments kept in the rolling `.m3u8` manifest |
| `PAGE_DURATION` | `12` | Seconds each news bulletin card remains on screen |
| `TYPEWRITER_DURATION` | `1.6` | Seconds to teletype the headline and body onto the card |
| `TICKER_SPEED` | `110` | Bottom news ticker scroll speed in pixels per second |
| `INDEX_CARD_EVERY` | `6` | Insert a `WIRE INDEX` 5-headline summary card every `N` stories (`0` to disable) |
| `SCANLINES` | `true` | Enable horizontal CRT scanlines |
| `CRT_NOISE` | `true` | Enable subtle analog RF static grain shimmer |
| `CRT_VIGNETTE` | `true` | Enable CRT corner darkening vignette |
| `TIME_FORMAT_12H` | `true` | `true` for 12-hour AM/PM clock; `false` for 24-hour clock |
| `AUDIO_MODE` | `hum` | `stream`, `hum`, or `silent` |
| `AUDIO_STREAM_URL` | *(empty)* | Audio stream URL when `AUDIO_MODE=stream` |
| `REFRESH_INTERVAL_MINUTES` | `10` | Interval in minutes between background CBC & CNN RSS fetches |
| `MAX_ITEMS_PER_SOURCE` | `15` | Maximum deduplicated stories kept per news organization |
| `CBC_FEEDS` | *(Top, World, Canada)* | Comma-separated list of CBC RSS URLs |
| `CNN_FEEDS` | *(Top, World, Latest)* | Comma-separated list of CNN RSS URLs |

### Default RSS Feeds

If `CBC_FEEDS` and `CNN_FEEDS` are not overridden, the container pulls from:
- **CBC**:
  - `https://www.cbc.ca/webfeed/rss/rss-topstories`
  - `https://www.cbc.ca/webfeed/rss/rss-world`
  - `https://www.cbc.ca/webfeed/rss/rss-canada`
- **CNN**:
  - `http://rss.cnn.com/rss/cnn_topstories.rss`
  - `http://rss.cnn.com/rss/cnn_world.rss`
  - `http://rss.cnn.com/rss/cnn_latest.rss`

---

## Project Structure

```text
cable-bulletin-hls/
├── Dockerfile               # Python 3.11-slim + FFmpeg + DejaVu/Liberation monospace fonts
├── docker-compose.yml       # Docker Compose configuration
├── requirements.txt         # FastAPI, Uvicorn, Jinja2, Pillow
├── README.md                # Documentation
└── app/
    ├── config.py            # Environment variable configuration
    ├── rss_fetcher.py       # CBC & CNN RSS parser, HTML sanitizer, and playlist interleaver
    ├── renderer.py          # 8-bit greyscale CRT character-generator frame renderer (Pillow)
    ├── streamer.py          # FFmpeg HLS (.m3u8 + .ts) and MPEG-TS background encoder manager
    ├── main.py              # FastAPI HTTP server, HLS/M3U/EPG routes, and status API
    └── templates/
        └── index.html       # Retro greyscale Web UI with live hls.js monitor
```
