import os


def _env_bool(name: str, default: bool = True) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


PORT = int(os.getenv("PORT", "8080"))

# Channel / Station Branding
CHANNEL_NUMBER = os.getenv("CHANNEL_NUMBER", "03")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "CABLETEXT BULLETIN")
STATION_ID = os.getenv("STATION_ID", "CATV-03 WIRE SERVICE")

# Video / HLS Settings
WIDTH = int(os.getenv("WIDTH", "1280"))
HEIGHT = int(os.getenv("HEIGHT", "720"))
FPS = int(os.getenv("FPS", "24"))
VIDEO_BITRATE = os.getenv("VIDEO_BITRATE", "2200k")
HLS_DIR = os.getenv("HLS_DIR", "/tmp/hls")
HLS_TIME = int(os.getenv("HLS_TIME", "2"))
HLS_LIST_SIZE = int(os.getenv("HLS_LIST_SIZE", "8"))

# Bulletin Board Timing & Behavior
PAGE_DURATION = float(os.getenv("PAGE_DURATION", "12.0"))
TYPEWRITER_DURATION = float(os.getenv("TYPEWRITER_DURATION", "1.6"))
TICKER_SPEED = float(os.getenv("TICKER_SPEED", "110.0"))  # pixels per second
INDEX_CARD_EVERY = int(os.getenv("INDEX_CARD_EVERY", "6"))  # show headline index every N stories

# Visual CRT / Greyscale Aesthetics
SCANLINES = _env_bool("SCANLINES", True)
CRT_NOISE = _env_bool("CRT_NOISE", True)
CRT_VIGNETTE = _env_bool("CRT_VIGNETTE", True)
TIME_FORMAT_12H = _env_bool("TIME_FORMAT_12H", True)

# Audio Settings: "hum" (vintage 60Hz analog hum/static), "silent" (mute AAC), or "stream" (radio URL)
AUDIO_MODE = os.getenv("AUDIO_MODE", "hum").strip().lower()
AUDIO_STREAM_URL = os.getenv("AUDIO_STREAM_URL", "").strip()

# RSS Feed Settings
REFRESH_INTERVAL_MINUTES = int(os.getenv("REFRESH_INTERVAL_MINUTES", "10"))
MAX_ITEMS_PER_SOURCE = int(os.getenv("MAX_ITEMS_PER_SOURCE", "15"))

DEFAULT_CBC_FEEDS = [
    "https://www.cbc.ca/webfeed/rss/rss-topstories",
    "https://www.cbc.ca/webfeed/rss/rss-world",
    "https://www.cbc.ca/webfeed/rss/rss-canada",
]

DEFAULT_CNN_FEEDS = [
    "http://rss.cnn.com/rss/cnn_topstories.rss",
    "http://rss.cnn.com/rss/cnn_world.rss",
    "http://rss.cnn.com/rss/cnn_latest.rss",
]

CBC_FEEDS = [
    u.strip()
    for u in os.getenv("CBC_FEEDS", ",".join(DEFAULT_CBC_FEEDS)).split(",")
    if u.strip()
]

CNN_FEEDS = [
    u.strip()
    for u in os.getenv("CNN_FEEDS", ",".join(DEFAULT_CNN_FEEDS)).split(",")
    if u.strip()
]
