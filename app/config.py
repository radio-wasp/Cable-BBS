import os


def _env_bool(name: str, default: bool = True) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


PORT = int(os.getenv("PORT", "8080"))
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# Admin Portal Authentication Defaults
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "cable10").strip()
SESSION_COOKIE_NAME = "cable_bulletin_session"

# Default Channel / Banner Branding (ASN Cable 10 reference layout)
CHANNEL_NUMBER = os.getenv("CHANNEL_NUMBER", "10")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "CABLE 10 BULLETIN")
STATION_ID = os.getenv("STATION_ID", "ASN CABLE 10")

# Default EPG / M3U Metadata (customizable in the Admin Portal EPG tab)
EPG_GROUP_TITLE = os.getenv("EPG_GROUP_TITLE", "Bulletin Boards")
EPG_PROGRAMME_TITLE = os.getenv("EPG_PROGRAMME_TITLE", "CABLE 10 BULLETIN")
EPG_PROGRAMME_SUBTITLE = os.getenv("EPG_PROGRAMME_SUBTITLE", "Community News & Information")
EPG_PROGRAMME_DESC = os.getenv(
    "EPG_PROGRAMME_DESC",
    "Continuous 24-hour vintage cable TV character generator bulletin board with custom RSS news feeds and background radio.",
)
EPG_CATEGORY = os.getenv("EPG_CATEGORY", "News")
EPG_SLOT_MINUTES = int(os.getenv("EPG_SLOT_MINUTES", "60"))

BANNER_LOGO = os.getenv("BANNER_LOGO", "ASN")
BANNER_LINE_1 = os.getenv("BANNER_LINE_1", "YOUR MAIN")
BANNER_LINE_2 = os.getenv("BANNER_LINE_2", "ATTRACTION")
BANNER_LINE_3 = os.getenv("BANNER_LINE_3", "CABLE 10")
SHOW_SOURCE_PREFIX = _env_bool("SHOW_SOURCE_PREFIX", False)

# Default Video / HLS Settings (can be changed live in the Admin Portal Resolution tab)
WIDTH = int(os.getenv("WIDTH", "1280"))
HEIGHT = int(os.getenv("HEIGHT", "720"))
FPS = int(os.getenv("FPS", "24"))
VIDEO_BITRATE = os.getenv("VIDEO_BITRATE", "2200k")
HLS_DIR = os.getenv("HLS_DIR", "/tmp/hls")
HLS_TIME = int(os.getenv("HLS_TIME", "2"))
HLS_LIST_SIZE = int(os.getenv("HLS_LIST_SIZE", "8"))

# Bulletin Board Timing
PAGE_DURATION = float(os.getenv("PAGE_DURATION", "12.0"))
TYPEWRITER_DURATION = float(os.getenv("TYPEWRITER_DURATION", "1.2"))

# Visual CRT Aesthetics
SCANLINES = _env_bool("SCANLINES", True)
CRT_NOISE = _env_bool("CRT_NOISE", True)
CRT_VIGNETTE = _env_bool("CRT_VIGNETTE", True)
TIME_FORMAT_12H = _env_bool("TIME_FORMAT_12H", True)

# Default Audio Settings (overridden by Admin Portal settings.json once saved)
# Supported AUDIO_MODE values: "stream" (radio), "subsonic" (Gonic/Subsonic library), "hum", "silent"
AUDIO_MODE = os.getenv("AUDIO_MODE", "stream").strip().lower()
AUDIO_STREAM_URL = os.getenv(
    "AUDIO_STREAM_URL",
    "https://chi-master3-entry1.leanstream-hd.com:2113/CKULFM",
).strip()

# Optional Subsonic / Gonic initial environment defaults
SUBSONIC_URL = os.getenv("SUBSONIC_URL", "").strip()
SUBSONIC_USER = os.getenv("SUBSONIC_USER", "").strip()
SUBSONIC_PASSWORD = os.getenv("SUBSONIC_PASSWORD", "").strip()
SUBSONIC_MODE = os.getenv("SUBSONIC_MODE", "random").strip().lower()
SUBSONIC_PLAYLIST_ID = os.getenv("SUBSONIC_PLAYLIST_ID", "").strip()
SUBSONIC_GENRE = os.getenv("SUBSONIC_GENRE", "").strip()

# RSS Refresh Settings
MAX_RSS_FEEDS = 5
REFRESH_INTERVAL_MINUTES = int(os.getenv("REFRESH_INTERVAL_MINUTES", "10"))
MAX_ITEMS_PER_FEED = int(os.getenv("MAX_ITEMS_PER_FEED", "12"))
