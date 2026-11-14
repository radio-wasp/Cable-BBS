import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from xml.sax.saxutils import escape

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import config
from app.renderer import renderer
from app.rss_fetcher import feed_manager
from app.settings_store import settings_store
from app.streamer import stream_manager
from app.subsonic import subsonic_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cable-bulletin.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Vintage Cable TV Bulletin Board (HLS)...")
    feed_manager.start()
    stream_manager.start()
    yield
    logger.info("Shutting down Vintage Cable TV Bulletin Board...")
    stream_manager.stop()
    feed_manager.stop()


app = FastAPI(
    title="Vintage Cable TV Bulletin Board (HLS)",
    description="ASN / Cable 10 style Character Generator with configurable RSS feeds, Radio Presets, Resolution & Admin Auth",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _get_base_url(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", f"localhost:{config.PORT}"))
    return f"{scheme}://{host}"


def require_admin(request: Request) -> str:
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    username = settings_store.verify_session_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return username


@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    base_url = _get_base_url(request)
    disp = settings_store.get_display()
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    authenticated_user = settings_store.verify_session_token(token)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "channel_number": disp.get("channel_number", config.CHANNEL_NUMBER),
            "channel_name": disp.get("channel_name", config.CHANNEL_NAME),
            "base_url": base_url,
            "hls_url": f"{base_url}/hls/stream.m3u8",
            "m3u_url": f"{base_url}/playlist.m3u",
            "epg_url": f"{base_url}/epg.xml",
            "ts_url": f"{base_url}/live.ts",
            "max_feeds": config.MAX_RSS_FEEDS,
            "is_authenticated": bool(authenticated_user),
            "authenticated_user": authenticated_user or "",
        },
    )


# =====================================================================
# PUBLIC STREAMING & IPTV ENDPOINTS (No Login Cookie Required for Tuners)
# =====================================================================

async def _wait_for_m3u8(timeout_sec: float = 8.0) -> str:
    m3u8_path = os.path.join(config.HLS_DIR, "stream.m3u8")
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        if os.path.exists(m3u8_path) and os.path.getsize(m3u8_path) > 0:
            return m3u8_path
        await asyncio.sleep(0.2)
    if not os.path.exists(m3u8_path):
        raise HTTPException(status_code=503, detail="HLS stream is warming up, please retry in a moment.")
    return m3u8_path


@app.get("/hls/stream.m3u8")
async def get_hls_manifest():
    m3u8_path = await _wait_for_m3u8()
    return FileResponse(
        m3u8_path,
        media_type="application/vnd.apple.mpegurl",
        headers=NO_CACHE_HEADERS,
    )


@app.get("/stream.m3u8")
async def get_root_hls_manifest():
    m3u8_path = await _wait_for_m3u8()
    with open(m3u8_path, "r", encoding="utf-8") as f:
        content = f.read()
    rewritten = "\n".join(
        f"/hls/{line}" if line.strip().endswith(".ts") and not line.strip().startswith("/") else line
        for line in content.splitlines()
    ) + "\n"
    return Response(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers=NO_CACHE_HEADERS,
    )


@app.get("/hls/{segment_name}")
async def get_hls_segment(segment_name: str):
    if not segment_name.endswith(".ts") or "/" in segment_name or ".." in segment_name:
        raise HTTPException(status_code=404, detail="Invalid segment")
    seg_path = os.path.join(config.HLS_DIR, segment_name)
    if not os.path.exists(seg_path):
        raise HTTPException(status_code=404, detail="Segment not found")
    return FileResponse(
        seg_path,
        media_type="video/mp2t",
        headers={"Cache-Control": "public, max-age=10"},
    )


@app.get("/live.ts")
@app.get("/stream")
async def get_live_mpegts():
    return StreamingResponse(
        stream_manager.iter_live_mpegts(),
        media_type="video/mp2t",
        headers=NO_CACHE_HEADERS,
    )


@app.get("/playlist.m3u")
async def get_m3u_playlist(request: Request):
    base_url = _get_base_url(request)
    epg = settings_store.get_epg()
    chno = epg.get("channel_number", config.CHANNEL_NUMBER)
    name = epg.get("channel_name", config.CHANNEL_NAME)
    group = epg.get("group_title", config.EPG_GROUP_TITLE)
    ch_id = f"cable-bulletin-{chno}"
    m3u_content = (
        f'#EXTM3U url-tvg="{base_url}/epg.xml"\n'
        f'#EXTINF:-1 tvg-id="{ch_id}" tvg-chno="{chno}" tvg-name="{name}" '
        f'tvg-logo="{base_url}/preview.png" group-title="{group}",{name}\n'
        f"{base_url}/hls/stream.m3u8\n"
    )
    return Response(content=m3u_content, media_type="audio/x-mpegurl")


@app.get("/epg.xml")
async def get_epg_xml(request: Request):
    base_url = _get_base_url(request)
    epg = settings_store.get_epg()
    chno = epg.get("channel_number", config.CHANNEL_NUMBER)
    ch_name = epg.get("channel_name", config.CHANNEL_NAME)
    prog_title = epg.get("programme_title") or ch_name
    prog_subtitle = epg.get("programme_subtitle", "")
    base_desc = epg.get("programme_description", config.EPG_PROGRAMME_DESC)
    category = epg.get("programme_category") or "News"
    slot_mins = max(15, int(epg.get("slot_duration_minutes", 60)))

    desc_parts = [base_desc] if base_desc else []
    if epg.get("append_live_headlines"):
        playlist = feed_manager.get_playlist()
        headlines = [item.title for item in playlist if item.feed_id not in ("system", "empty")][:3]
        if headlines:
            desc_parts.append("Latest Headlines: " + " | ".join(headlines))
    if epg.get("append_active_radio"):
        audio = settings_store.get_active_audio()
        if audio.get("audio_mode") == "stream" and audio.get("active_radio_name"):
            desc_parts.append(f"Audio: {audio['active_radio_name']}")
        elif audio.get("audio_mode") == "subsonic":
            np = subsonic_client.get_now_playing()
            if np:
                desc_parts.append(f"Music: {np.get('artist')} - {np.get('title')}")
            elif audio.get("subsonic_playlist_name"):
                desc_parts.append(f"Music: {audio['subsonic_playlist_name']}")
            else:
                desc_parts.append("Music: Subsonic Library Shuffle")

    full_desc = " — ".join(desc_parts)

    ch_id = f"cable-bulletin-{chno}"
    now = datetime.now(timezone.utc)
    start_base = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<tv generator-info-name="CableBulletinHLS">',
        f'  <channel id="{escape(ch_id)}">',
        f'    <display-name>{escape(ch_name)}</display-name>',
        f'    <display-name>{escape(chno)}</display-name>',
        f'    <icon src="{escape(base_url)}/preview.png" />',
        '  </channel>',
    ]

    total_slots = max(4, int((26 * 60) // slot_mins))
    for i in range(total_slots):
        slot_start = start_base + timedelta(minutes=i * slot_mins)
        slot_end = slot_start + timedelta(minutes=slot_mins)
        s_str = slot_start.strftime("%Y%m%d%H%M%S +0000")
        e_str = slot_end.strftime("%Y%m%d%H%M%S +0000")
        lines.append(f'  <programme start="{s_str}" stop="{e_str}" channel="{escape(ch_id)}">')
        lines.append(f'    <title lang="en">{escape(prog_title)}</title>')
        if prog_subtitle:
            lines.append(f'    <sub-title lang="en">{escape(prog_subtitle)}</sub-title>')
        if full_desc:
            lines.append(f'    <desc lang="en">{escape(full_desc)}</desc>')
        if category:
            lines.append(f'    <category lang="en">{escape(category)}</category>')
        lines.append('  </programme>')

    lines.append("</tv>")
    return Response(content="\n".join(lines), media_type="application/xml")


@app.get("/preview.png")
async def get_preview_png():
    png_bytes = renderer.render_png_bytes()
    return Response(content=png_bytes, media_type="image/png", headers=NO_CACHE_HEADERS)


@app.get("/health")
async def health():
    return {"status": "ok", "hls_ready": stream_manager.is_ready()}


# =====================================================================
# AUTHENTICATION API
# =====================================================================

@app.get("/api/auth/status")
async def api_auth_status(request: Request):
    token = request.cookies.get(config.SESSION_COOKIE_NAME)
    username = settings_store.verify_session_token(token)
    return {"authenticated": bool(username), "username": username}


@app.post("/api/auth/login")
async def api_login(payload: Dict[str, Any] = Body(...)):
    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    if not settings_store.verify_credentials(username, password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = settings_store.create_session_token()
    resp = JSONResponse({"ok": True, "username": username.strip()})
    resp.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
        path="/",
    )
    return resp


@app.post("/api/auth/logout")
async def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(key=config.SESSION_COOKIE_NAME, path="/")
    return resp


@app.put("/api/auth/credentials")
async def api_update_credentials(
    payload: Dict[str, Any] = Body(...),
    _user: str = Depends(require_admin),
):
    current_password = str(payload.get("current_password", ""))
    new_username = str(payload.get("new_username", "")).strip()
    new_password = str(payload.get("new_password", ""))

    if not settings_store.verify_credentials(_user, current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    try:
        saved_user = settings_store.update_credentials(new_username, new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    new_token = settings_store.create_session_token()
    resp = JSONResponse({"ok": True, "username": saved_user})
    resp.set_cookie(
        key=config.SESSION_COOKIE_NAME,
        value=new_token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
        path="/",
    )
    return resp


# =====================================================================
# PROTECTED ADMIN PORTAL REST API
# =====================================================================

@app.get("/api/status")
async def api_status(_user: str = Depends(require_admin)):
    playlist = feed_manager.get_playlist()
    return {
        "stream": stream_manager.get_status(),
        "feeds": feed_manager.get_status(),
        "settings": settings_store.get_public_settings(),
        "active_audio": settings_store.get_active_audio(),
        "sample_headlines": [
            {
                "source": item.source,
                "wire_code": item.wire_code,
                "title": item.title,
                "broadcast_copy": item.broadcast_copy,
                "published": item.published,
            }
            for item in playlist
        ][:20],
    }


@app.post("/api/refresh")
async def api_refresh(_user: str = Depends(require_admin)):
    feed_status = await asyncio.to_thread(feed_manager.refresh_now)
    return {"ok": True, "feeds": feed_status}


# --- RSS Feeds Management (Up to 5 feeds) ---

@app.post("/api/feeds")
async def api_add_feed(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    try:
        new_feed = settings_store.add_rss_feed(
            name=str(payload.get("name", "")),
            url=str(payload.get("url", "")),
            enabled=bool(payload.get("enabled", True)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    feed_status = await asyncio.to_thread(feed_manager.refresh_now)
    return {"ok": True, "feed": new_feed, "feeds_status": feed_status}


@app.put("/api/feeds")
async def api_replace_feeds(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    feeds = payload.get("rss_feeds", [])
    if not isinstance(feeds, list):
        raise HTTPException(status_code=400, detail="rss_feeds must be a list")
    try:
        saved = settings_store.set_rss_feeds(feeds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    feed_status = await asyncio.to_thread(feed_manager.refresh_now)
    return {"ok": True, "rss_feeds": saved, "feeds_status": feed_status}


@app.patch("/api/feeds/{feed_id}")
async def api_toggle_feed(feed_id: str, payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    updated = settings_store.toggle_rss_feed(feed_id, bool(payload.get("enabled", True)))
    if not updated:
        raise HTTPException(status_code=404, detail="Feed not found")
    feed_status = await asyncio.to_thread(feed_manager.refresh_now)
    return {"ok": True, "feed": updated, "feeds_status": feed_status}


@app.delete("/api/feeds/{feed_id}")
async def api_delete_feed(feed_id: str, _user: str = Depends(require_admin)):
    removed = settings_store.delete_rss_feed(feed_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Feed not found")
    feed_status = await asyncio.to_thread(feed_manager.refresh_now)
    return {"ok": True, "feeds_status": feed_status}


# --- Radio Station Presets & Audio Control ---

@app.post("/api/radio/presets")
async def api_add_radio_preset(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    activate = bool(payload.get("activate", True))
    try:
        preset = settings_store.add_radio_preset(
            name=str(payload.get("name", "")),
            url=str(payload.get("url", "")),
            activate=activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if activate:
        stream_manager.restart_encoder()
    return {
        "ok": True,
        "preset": preset,
        "radio_presets": settings_store.get_radio_presets(),
        "active_audio": settings_store.get_active_audio(),
    }


@app.put("/api/radio/presets/{preset_id}")
async def api_update_radio_preset(preset_id: str, payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    try:
        updated = settings_store.update_radio_preset(
            preset_id=preset_id,
            name=str(payload.get("name", "")),
            url=str(payload.get("url", "")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="Preset not found")
    active = settings_store.get_active_audio()
    if active.get("active_radio_id") == preset_id and active.get("audio_mode") == "stream":
        stream_manager.restart_encoder()
    return {
        "ok": True,
        "preset": updated,
        "radio_presets": settings_store.get_radio_presets(),
        "active_audio": active,
    }


@app.delete("/api/radio/presets/{preset_id}")
async def api_delete_radio_preset(preset_id: str, _user: str = Depends(require_admin)):
    prev_active = settings_store.get_active_audio().get("active_radio_id")
    removed = settings_store.delete_radio_preset(preset_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Preset not found")
    if prev_active == preset_id:
        stream_manager.restart_encoder()
    return {
        "ok": True,
        "radio_presets": settings_store.get_radio_presets(),
        "active_audio": settings_store.get_active_audio(),
    }


@app.post("/api/radio/select")
async def api_select_radio(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    audio_mode = str(payload.get("audio_mode", "stream"))
    active_radio_id = payload.get("active_radio_id")
    try:
        active = settings_store.set_audio_selection(audio_mode, active_radio_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    stream_manager.restart_encoder()
    return {"ok": True, "active_audio": active}


<<<<<<< HEAD
# --- Subsonic / Gonic Music Library Control ---

@app.put("/api/subsonic/config")
async def api_update_subsonic(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    prev_mode = settings_store.get_active_audio().get("audio_mode")
    updated = settings_store.update_subsonic(payload)
    new_mode = settings_store.get_active_audio().get("audio_mode")
    subsonic_client.clear_queue_and_skip()
    if new_mode == "subsonic" and prev_mode != "subsonic":
        stream_manager.restart_encoder()
    return {
        "ok": True,
        "subsonic": updated,
        "active_audio": settings_store.get_active_audio(),
    }


@app.post("/api/subsonic/test")
async def api_test_subsonic(payload: Dict[str, Any] = Body(default={}), _user: str = Depends(require_admin)):
    # Merge any unsaved form fields over saved subsonic settings for testing
    cfg = settings_store.get_subsonic(include_password=True)
    for k in ("server_url", "username", "legacy_auth"):
        if k in payload and payload[k] is not None and payload[k] != "":
            cfg[k] = payload[k]
    if payload.get("password"):
        cfg["password"] = str(payload["password"])
    try:
        result = await asyncio.to_thread(subsonic_client.test_connection, cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@app.get("/api/subsonic/playlists")
async def api_get_subsonic_playlists(_user: str = Depends(require_admin)):
    try:
        playlists = await asyncio.to_thread(subsonic_client.get_playlists)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "playlists": playlists}


@app.post("/api/subsonic/skip")
async def api_skip_subsonic_track(_user: str = Depends(require_admin)):
    subsonic_client.skip_current_track()
    return {"ok": True}


=======
>>>>>>> 6060c7684f3f1c32df038d6ebceb421510686eda
# --- Video Resolution, FPS & Bitrate ---

@app.put("/api/video")
async def api_update_video(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    try:
        updated = settings_store.update_video(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    renderer.reconfigure(updated["width"], updated["height"])
    stream_manager.restart_encoder()
    return {"ok": True, "video": updated}


<<<<<<< HEAD
# --- EPG & M3U Guide Output Customization ---

@app.put("/api/epg")
async def api_update_epg(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    try:
        updated = settings_store.update_epg(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "epg": updated}


=======
>>>>>>> 6060c7684f3f1c32df038d6ebceb421510686eda
# --- Display & Banner Branding ---

@app.put("/api/display")
async def api_update_display(payload: Dict[str, Any] = Body(...), _user: str = Depends(require_admin)):
    prev_prefix = settings_store.get_display().get("show_source_prefix", False)
    updated = settings_store.update_display(payload)
    if updated.get("show_source_prefix", False) != prev_prefix:
        await asyncio.to_thread(feed_manager.refresh_now)
    return {"ok": True, "display": updated}
