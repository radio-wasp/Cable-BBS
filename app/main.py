import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import config
from app.renderer import renderer
from app.rss_fetcher import feed_manager
from app.streamer import stream_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cable-bulletin.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Vintage Cable TV Bulletin Board (CBC & CNN -> Greyscale HLS)...")
    feed_manager.start()
    stream_manager.start()
    yield
    logger.info("Shutting down Vintage Cable TV Bulletin Board...")
    stream_manager.stop()
    feed_manager.stop()


app = FastAPI(
    title="Vintage Cable TV Bulletin Board (HLS)",
    description="Greyscale 1980s Cable TV Character Generator pulling CBC & CNN RSS feeds into an HLS stream",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS so external HLS players (hls.js, web players, IPTV frontends) can fetch .m3u8 and .ts segments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "POST", "OPTIONS"],
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


@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    base_url = _get_base_url(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "channel_number": config.CHANNEL_NUMBER,
            "channel_name": config.CHANNEL_NAME,
            "station_id": config.STATION_ID,
            "base_url": base_url,
            "hls_url": f"{base_url}/hls/stream.m3u8",
            "m3u_url": f"{base_url}/playlist.m3u",
            "epg_url": f"{base_url}/epg.xml",
            "ts_url": f"{base_url}/live.ts",
            "status": stream_manager.get_status(),
            "feed_status": feed_manager.get_status(),
        },
    )


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
    """Root alias for /hls/stream.m3u8 with segment paths rewritten to /hls/seg_*.ts."""
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
    """Continuous MPEG-TS live stream endpoint for IPTV tuners."""
    return StreamingResponse(
        stream_manager.iter_live_mpegts(),
        media_type="video/mp2t",
        headers=NO_CACHE_HEADERS,
    )


@app.get("/playlist.m3u")
async def get_m3u_playlist(request: Request):
    """Standard M3U IPTV playlist pointing to the HLS stream."""
    base_url = _get_base_url(request)
    ch_id = f"cable-bulletin-{config.CHANNEL_NUMBER}"
    m3u_content = (
        "#EXTM3U url-tvg=\"{base}/epg.xml\"\n"
        "#EXTINF:-1 tvg-id=\"{ch_id}\" tvg-chno=\"{chno}\" tvg-name=\"{name}\" "
        "tvg-logo=\"{base}/preview.png\" group-title=\"News & Bulletin Boards\",{name}\n"
        "{base}/hls/stream.m3u8\n"
    ).format(
        base=base_url,
        ch_id=ch_id,
        chno=config.CHANNEL_NUMBER,
        name=config.CHANNEL_NAME,
    )
    return Response(content=m3u_content, media_type="audio/x-mpegurl")


@app.get("/epg.xml")
async def get_epg_xml(request: Request):
    """Standard XMLTV EPG guide for IPTV / Dispatcharr / Jellyfin integration."""
    base_url = _get_base_url(request)
    ch_id = f"cable-bulletin-{config.CHANNEL_NUMBER}"
    now = datetime.now(timezone.utc)
    start_base = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<tv generator-info-name="CableBulletinHLS">',
        f'  <channel id="{escape(ch_id)}">',
        f'    <display-name>{escape(config.CHANNEL_NAME)}</display-name>',
        f'    <display-name>{escape(config.CHANNEL_NUMBER)}</display-name>',
        f'    <icon src="{escape(base_url)}/preview.png" />',
        '  </channel>',
    ]

    # Generate 24 one-hour blocks so EPG guides are always populated
    for h in range(26):
        slot_start = start_base + timedelta(hours=h)
        slot_end = slot_start + timedelta(hours=1)
        s_str = slot_start.strftime("%Y%m%d%H%M%S +0000")
        e_str = slot_end.strftime("%Y%m%d%H%M%S +0000")
        lines.extend([
            f'  <programme start="{s_str}" stop="{e_str}" channel="{escape(ch_id)}">',
            f'    <title lang="en">{escape(config.CHANNEL_NAME)} - CBC &amp; CNN Wire</title>',
            '    <desc lang="en">Continuous 24-hour vintage greyscale cable TV character generator '
            'displaying live headlines and dispatches from CBC News and CNN RSS feeds.</desc>',
            '    <category lang="en">News</category>',
            '  </programme>',
        ])

    lines.append("</tv>")
    return Response(content="\n".join(lines), media_type="application/xml")


@app.get("/preview.png")
async def get_preview_png():
    """Render and return an instant greyscale PNG snapshot of the current bulletin frame."""
    png_bytes = renderer.render_png_bytes()
    return Response(content=png_bytes, media_type="image/png", headers=NO_CACHE_HEADERS)


@app.get("/api/status")
async def api_status():
    playlist = feed_manager.get_playlist()
    return {
        "stream": stream_manager.get_status(),
        "feeds": feed_manager.get_status(),
        "sample_headlines": [
            {
                "source": item.source,
                "category": item.category,
                "wire_code": item.wire_code,
                "title": item.title,
                "summary": item.summary,
                "published": item.published,
            }
            for item in playlist
            if not item.is_index
        ][:16],
    }


@app.post("/api/refresh")
async def api_refresh():
    feed_status = await asyncio.to_thread(feed_manager.refresh_now)
    return {"ok": True, "feeds": feed_status}


@app.get("/health")
async def health():
    return {"status": "ok", "hls_ready": stream_manager.is_ready()}
