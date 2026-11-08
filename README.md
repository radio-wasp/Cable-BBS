# Vintage Cable TV Bulletin Board (`cable-bulletin-hls`) 📺

A lightweight, self-contained Docker container that recreates the iconic **ASN / Cable 10 (Atlantic Satellite Network)** vintage Cable TV Character Generator & Community Bulletin Board in **full colour**, outputting a live **HLS stream** (`.m3u8` + `.ts` segments) and **MPEG-TS stream** with live background radio.

All **RSS news feeds (up to 5)**, **radio station presets**, **stream resolution/framerate/bitrate profiles**, **on-screen banner graphics**, and **operator login credentials** are controlled directly through the built-in **Admin Portal** and persisted to `/app/data/settings.json`.

![Live Broadcast Output](screenshots/broadcast-output.png)

---

## Visual Tour & Screenshots

### 1. Live Broadcast Output vs. Original 2005 ASN / Cable 10 Reference

| Generated HLS Stream (`/hls/stream.m3u8` & `/preview.png`) | Original 2005 ASN / Cable 10 Broadcast Capture |
| :---: | :---: |
| ![Generated Broadcast Output](screenshots/broadcast-output.png) | ![Original 2005 ASN Reference](screenshots/reference-asn-2005.jpg) |

* **Top Band (Date & Clock Bar)**: Gunmetal-grey header (`#60605e`) with a 3D beveled lower border, displaying the Date on the left (`Thu Nov 5, 2026` format) and 12-hour Time on the right (`3:42 pm` format) in bold sans-serif with heavy drop shadows.
* **Middle Band (Bulletin Copy Field)**: Deep broadcast royal-blue field (`#0c3a80`) with CRT scanlines. Displays one concise 4-to-6 line **ALL-CAPS** news paragraph at a time in a wide **bold slab-serif typewriter font** (`CourierPrime-Bold` / `FreeMonoBold`) in pale ice-white (`#d6e2f6`) with the **first line indented by 3 spaces** and a deep navy drop shadow.
* **Bottom Band (ASN / Cable 10 Graphic Promo Banner)**: Rich violet-to-indigo background gradient (`#381070` -> `#180e40`) with a 3D perspective wireframe grid, faint angled `NEWS` watermark blocks, giant 3D extruded blue-chrome metallic block logo (`ASN`), stacked wide-tracked promo text (`YOUR MAIN` / `ATTRACTION` / `CABLE 10`), and subtle bottom-edge VHS chroma head-switching noise.

---

### 2. Operator Login Prompt (`http://<host>:8080/`)

Visiting the Admin Portal presents an operator authentication prompt before allowing changes to feeds, radio stations, resolution, or banners (default credentials: `admin` / `cable10`). IPTV and HLS playback endpoints (`/hls/stream.m3u8`, `/live.ts`, `/playlist.m3u`, `/epg.xml`) remain accessible to media players without requiring browser cookies.

![Operator Login Prompt](screenshots/login-prompt.png)

---

### 3. Admin Portal — RSS Feeds (Max 5) & Radio Station Tuner

<<<<<<< HEAD
- **Operator Login Prompt & Session Auth**:
  - Protects the Admin Portal and configuration APIs with an operator login prompt (default credentials: `admin` / `cable10`, configurable via `ADMIN_USERNAME` and `ADMIN_PASSWORD` or the **4. Login & Security** tab).
  - IPTV / HLS stream playback routes (`/hls/stream.m3u8`, `/live.ts`, `/playlist.m3u`, `/epg.xml`) remain accessible to media players and tuners without requiring browser cookies.
- **1. Custom RSS Feeds (Up to 5 Feeds) & Audio Source (Radio or Subsonic / Gonic)**:
  - Add, enable/disable, or delete up to **5 custom RSS or Atom feeds** directly from the web UI.
  - **Radio Station Presets**: Save multiple internet radio streams (MP3, AAC, Icecast, Leanstream, Shoutcast) as named presets and click **TUNE IN** to switch the live HLS audio stream on the fly.
  - **Subsonic / Gonic Music Library**: Connect to any Subsonic-compatible server (**Gonic**, **Navidrome**, **Airsonic**, **Subsonic**) to stream either **Random Library Shuffle** (with optional genre filter) or a **Specific Subsonic Playlist** continuously into the HLS stream, complete with a live `NOW PLAYING` display and **SKIP TRACK** button.
- **2. Resolution, Framerate & Bitrate Tab**:
  - Switch video resolution (`1920×1080`, `1280×720`, `960×540` Railway Saver, `854×480`, `640×480` 4:3 CRT, or custom dimensions), framerate (`10`–`30 fps`), and H.264 bitrate (`600k`–`3500k`) live without restarting the container.
  - Includes a built-in **Cloud & Bandwidth Estimator** showing hourly outbound traffic (`GB/hr`) and estimated Railway vCPU cost.
- **3. Banner & CRT Customizer**:
  - Edit the 3D Left Banner Logo (`ASN`), Right Banner Lines 1–3 (`YOUR MAIN`, `ATTRACTION`, `CABLE 10`), page hold duration, typewriter reveal speed, and CRT scanline/noise/vignette effects live.
- **4. EPG & M3U Guide Customizer**:
  - Customize what `/epg.xml` and `/playlist.m3u` output to IPTV clients (Channel Number, Channel Display Name, M3U `group-title`, Programme `<title>`, `<sub-title>`, `<desc>`, `<category>`, and guide block duration), plus optional toggles to dynamically append the latest 3 live RSS headlines and active radio station name into the EPG description.
- **Persistent Storage**:
  - All Admin Portal settings, feeds, radio presets, resolution profiles, and password hashes are saved to `/app/data/settings.json` (mounted to `./data` in `docker-compose.yml`).
=======
Manage up to **5 custom RSS or Atom feeds** (enable/disable, inspect story counts, or delete), copy your **HLS / M3U / EPG / MPEG-TS** stream URLs, and save multiple **Radio Station Presets** with one-click **TUNE IN** switching:

![Admin Portal Main View](screenshots/admin-portal.png)

---

### 4. Admin Portal — Resolution, Framerate & Cloud Cost Presets

Switch video resolution (`1920×1080`, `1280×720`, `960×540` Railway Saver, `854×480`, `640×480` 4:3 CRT, or custom dimensions), framerate (`10`–`30 fps`), and H.264 bitrate (`600k`–`3500k`) on the fly, complete with a live outbound bandwidth (`GB/hr`) and Railway vCPU estimator:

![Resolution and Encoding Tab](screenshots/resolution-tab.png)
>>>>>>> 6060c7684f3f1c32df038d6ebceb421510686eda

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
    volumes:
      - ./data:/app/data
    environment:
      - PORT=8080
      - DATA_DIR=/app/data
      - TZ=America/Halifax
      - ADMIN_USERNAME=admin
      - ADMIN_PASSWORD=cable10
      - CHANNEL_NUMBER=10
      - CHANNEL_NAME=CABLE 10 BULLETIN
      - BANNER_LOGO=ASN
      - BANNER_LINE_1=YOUR MAIN
      - BANNER_LINE_2=ATTRACTION
      - BANNER_LINE_3=CABLE 10
      - WIDTH=1280
      - HEIGHT=720
      - FPS=24
      - VIDEO_BITRATE=2200k
      - PAGE_DURATION=12
      - TYPEWRITER_DURATION=1.2
      - SCANLINES=true
      - CRT_NOISE=true
      - CRT_VIGNETTE=true
      - AUDIO_MODE=stream
      - AUDIO_STREAM_URL=https://chi-master3-entry1.leanstream-hd.com:2113/CKULFM
      - REFRESH_INTERVAL_MINUTES=10
```

Build and start:

```bash
docker compose up -d --build
```

Open **`http://localhost:8080`** and sign in (`admin` / `cable10`) to access the Admin Portal.

### Option 2: Docker CLI

```bash
docker build -t cable-bulletin-hls:latest .

docker run -d \
  --name cable-bulletin-hls \
  --restart unless-stopped \
  -p 8080:8080 \
  -v $(pwd)/data:/app/data \
  -e TZ=America/Halifax \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD=cable10 \
  cable-bulletin-hls:latest
```

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

## Stream & API Endpoints

<<<<<<< HEAD
| Path | Description |
| :--- | :--- |
| `/` | **Admin Portal** & live full-colour HLS broadcast monitor |
| `/hls/stream.m3u8` | **Primary HLS stream manifest** (`.m3u8`) |
| `/stream.m3u8` | Root alias for `/hls/stream.m3u8` |
| `/live.ts` *(or `/stream`)* | Continuous **MPEG-TS** HTTP stream (`video/mp2t`) |
| `/playlist.m3u` | **M3U Playlist** for Dispatcharr, Jellyfin, Plex, TiviMate, or VLC |
| `/epg.xml` | **XMLTV EPG** guide data |
| `/preview.png` | Instant full-colour PNG snapshot of the current bulletin frame |
| `GET /api/status` | Full JSON status (encoder state, feed counts, saved settings, active headlines) |
| `POST /api/feeds` | Add a new RSS feed (`{name, url, enabled}`) — max 5 feeds |
| `PUT /api/feeds` | Replace the RSS feeds list (`{rss_feeds: [...]}`) — max 5 feeds |
| `PATCH /api/feeds/{id}` | Enable or disable an RSS feed (`{enabled}`) |
| `DELETE /api/feeds/{id}` | Delete an RSS feed |
| `POST /api/radio/presets` | Add a radio station preset (`{name, url, activate}`) |
| `PUT /api/radio/presets/{id}` | Update a radio station preset (`{name, url}`) |
| `POST /api/radio/select` | Switch active audio mode (`stream`, `subsonic`, `hum`, `silent`) or radio preset |
| `DELETE /api/radio/presets/{id}` | Delete a radio station preset |
| `PUT /api/subsonic/config` | Save Subsonic / Gonic server credentials, playback mode (`random` or `playlist`), playlist ID, and genre filter |
| `POST /api/subsonic/test` | Test Subsonic / Gonic connection (`/rest/ping.view`) and fetch available playlists |
| `GET /api/subsonic/playlists` | List playlists from the configured Subsonic / Gonic server |
| `POST /api/subsonic/skip` | Immediately skip to the next track in the Subsonic queue |
| `PUT /api/video` | Update resolution (`width`, `height`), `fps`, and `video_bitrate` and restart encoder |
| `PUT /api/display` | Update banner text and CRT display settings |
| `PUT /api/epg` | Update XMLTV EPG & M3U playlist metadata (`programme_title`, `programme_subtitle`, `programme_description`, `programme_category`, `group_title`, `slot_duration_minutes`, `append_live_headlines`, `append_active_radio`) |
| `POST /api/auth/login` | Authenticate operator (`{username, password}`) and set session cookie |
| `POST /api/auth/logout` | Clear operator session cookie |
| `PUT /api/auth/credentials` | Change admin username and password (`{current_password, new_username, new_password}`) |
| `POST /api/refresh` | Trigger an immediate RSS refresh across all enabled feeds |
| `GET /health` | Container healthcheck endpoint |
=======
| Path | Auth | Description |
| :--- | :---: | :--- |
| `/` | Login Gate | **Admin Portal** & live full-colour HLS broadcast monitor |
| `/hls/stream.m3u8` | Public | **Primary HLS stream manifest** (`.m3u8`) |
| `/stream.m3u8` | Public | Root alias for `/hls/stream.m3u8` |
| `/live.ts` *(or `/stream`)* | Public | Continuous **MPEG-TS** HTTP stream (`video/mp2t`) |
| `/playlist.m3u` | Public | **M3U Playlist** for Dispatcharr, Jellyfin, Plex, TiviMate, or VLC |
| `/epg.xml` | Public | **XMLTV EPG** guide data |
| `/preview.png` | Public | Instant full-colour PNG snapshot of the current bulletin frame |
| `GET /health` | Public | Container healthcheck endpoint |
| `POST /api/auth/login` | Public | Authenticate operator (`{username, password}`) and set session cookie |
| `POST /api/auth/logout` | Public | Clear operator session cookie |
| `GET /api/status` | Admin | Full JSON status (encoder state, feed counts, saved settings, active headlines) |
| `POST /api/feeds` | Admin | Add a new RSS feed (`{name, url, enabled}`) — max 5 feeds |
| `PATCH /api/feeds/{id}` | Admin | Enable or disable an RSS feed (`{enabled}`) |
| `DELETE /api/feeds/{id}` | Admin | Delete an RSS feed |
| `POST /api/radio/presets` | Admin | Add a radio station preset (`{name, url, activate}`) |
| `POST /api/radio/select` | Admin | Switch active radio preset or audio mode (`{audio_mode, active_radio_id}`) |
| `DELETE /api/radio/presets/{id}` | Admin | Delete a radio station preset |
| `PUT /api/video` | Admin | Update resolution (`width`, `height`), `fps`, and `video_bitrate` and restart encoder |
| `PUT /api/display` | Admin | Update banner text and CRT display settings |
| `PUT /api/auth/credentials` | Admin | Change admin username and password (`{current_password, new_username, new_password}`) |
| `POST /api/refresh` | Admin | Trigger an immediate RSS refresh across all enabled feeds |
>>>>>>> 6060c7684f3f1c32df038d6ebceb421510686eda

---

## Environment Variables (Initial Defaults)

Environment variables seed the initial defaults when `/app/data/settings.json` is first created. Once saved via the Admin Portal, changes in `/app/data/settings.json` take precedence:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8080` | HTTP server & Admin Portal port |
| `DATA_DIR` | `/app/data` | Directory where `settings.json` is persisted |
| `ADMIN_USERNAME` | `admin` | Initial Admin Portal login username |
| `ADMIN_PASSWORD` | `cable10` | Initial Admin Portal login password |
| `TZ` | `UTC` | Local timezone for the top broadcast clock (e.g. `America/Halifax`) |
| `CHANNEL_NUMBER` | `10` | Channel number used in M3U/EPG metadata |
| `CHANNEL_NAME` | `CABLE 10 BULLETIN` | Channel name used in M3U/EPG metadata and portal header |
| `BANNER_LOGO` | `ASN` | Initial 3D metallic logo on the left of the bottom banner |
| `BANNER_LINE_1` | `YOUR MAIN` | Initial right-side banner line 1 |
| `BANNER_LINE_2` | `ATTRACTION` | Initial right-side banner line 2 |
| `BANNER_LINE_3` | `CABLE 10` | Initial right-side banner line 3 |
| `SHOW_SOURCE_PREFIX` | `false` | Prefix story text with `[FEED NAME]` |
| `WIDTH` | `1280` | Initial output video width |
| `HEIGHT` | `720` | Initial output video height |
| `FPS` | `24` | Initial video frame rate |
| `VIDEO_BITRATE` | `2200k` | Initial target H.264 bitrate |
| `PAGE_DURATION` | `12` | Default seconds per bulletin story |
| `TYPEWRITER_DURATION` | `1.2` | Default seconds for typewriter reveal (`0` for instant page flips) |
| `SCANLINES` | `true` | Enable horizontal CRT scanlines |
| `CRT_NOISE` | `true` | Enable subtle analog RF grain & bottom VHS chroma shimmer |
| `CRT_VIGNETTE` | `true` | Enable CRT corner vignette darkening |
| `AUDIO_MODE` | `stream` | Initial audio mode (`stream` for radio, `subsonic` for Gonic/Subsonic, `hum`, or `silent`) |
| `AUDIO_STREAM_URL` | `https://...CKULFM` | Initial radio preset URL |
| `SUBSONIC_URL` | *(empty)* | Optional initial Subsonic / Gonic server URL (e.g. `http://192.168.1.50:4747`) |
| `SUBSONIC_USER` | *(empty)* | Optional initial Subsonic / Gonic username |
| `SUBSONIC_PASSWORD` | *(empty)* | Optional initial Subsonic / Gonic password |
| `REFRESH_INTERVAL_MINUTES` | `10` | Background RSS refresh interval in minutes |

---

## Project Structure

```text
cable-bulletin-hls/
├── Dockerfile               # Python 3.11-slim + FFmpeg + CourierPrime/FreeMono/Liberation fonts
├── docker-compose.yml       # Docker Compose configuration with ./data volume
├── requirements.txt         # FastAPI, Uvicorn, Jinja2, Pillow
├── README.md                # Documentation with screenshots
├── screenshots/             # PNG/SVG/JPG screenshots of broadcast output, Admin Portal, and tabs
│   ├── broadcast-output.png
│   ├── admin-portal.png
│   ├── resolution-tab.png
│   ├── login-prompt.png
│   └── reference-asn-2005.jpg
└── app/
    ├── config.py            # Environment variable defaults
    ├── settings_store.py    # Persistent JSON store (/app/data/settings.json) & PBKDF2 session auth
    ├── rss_fetcher.py       # Multi-feed RSS/Atom parser (up to 5 feeds) & broadcast wire formatter
    ├── subsonic.py          # Subsonic / Gonic API client & continuous 44.1kHz stereo PCM audio feeder
    ├── renderer.py          # 24-bit RGB ASN / Cable 10 3-band CRT frame renderer (Pillow)
    ├── streamer.py          # FFmpeg HLS (.m3u8 + .ts) & MPEG-TS encoder with live res/radio switching
    ├── main.py              # FastAPI server, Admin Portal REST API, auth routes, and HLS/M3U/EPG routes
    └── templates/
        └── index.html       # Admin Portal Web UI with login prompt, live HLS monitor & 4 settings tabs
```
