import json
import logging
import os
import threading
import uuid
from typing import Any, Dict, List, Optional

from app import config

logger = logging.getLogger("cable-bulletin.settings")


def _default_settings() -> Dict[str, Any]:
    default_preset_id = "preset-ckulfm"
    presets = []
    if config.AUDIO_STREAM_URL:
        presets.append({
            "id": default_preset_id,
            "name": "CKUL-FM (Default Stream)",
            "url": config.AUDIO_STREAM_URL,
        })

    return {
        "rss_feeds": [
            {
                "id": "feed-1",
                "name": "CBC Top Stories",
                "url": "https://www.cbc.ca/webfeed/rss/rss-topstories",
                "enabled": True,
            },
            {
                "id": "feed-2",
                "name": "CNN Top Stories",
                "url": "http://rss.cnn.com/rss/cnn_topstories.rss",
                "enabled": True,
            },
        ],
        "radio_presets": presets,
        "active_radio_id": default_preset_id if presets else None,
        "audio_mode": config.AUDIO_MODE if config.AUDIO_MODE in ("stream", "hum", "silent") else "hum",
        "display": {
            "channel_number": config.CHANNEL_NUMBER,
            "channel_name": config.CHANNEL_NAME,
            "banner_logo": config.BANNER_LOGO,
            "banner_line_1": config.BANNER_LINE_1,
            "banner_line_2": config.BANNER_LINE_2,
            "banner_line_3": config.BANNER_LINE_3,
            "page_duration": config.PAGE_DURATION,
            "typewriter_duration": config.TYPEWRITER_DURATION,
            "show_source_prefix": config.SHOW_SOURCE_PREFIX,
            "scanlines": config.SCANLINES,
            "crt_noise": config.CRT_NOISE,
            "crt_vignette": config.CRT_VIGNETTE,
        },
    }


class SettingsStore:
    """
    Thread-safe persistent configuration store for the Admin Portal:
    - Up to 5 custom RSS feeds
    - Radio station presets + active station / audio mode
    - ASN Cable 10 banner & CRT display settings
    """

    def __init__(self, path: str = config.SETTINGS_FILE) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = _default_settings()
        self._load()

    def _load(self) -> None:
        with self._lock:
            try:
                if os.path.exists(self._path):
                    with open(self._path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        defaults = _default_settings()
                        defaults.update(loaded)
                        if "display" in loaded and isinstance(loaded["display"], dict):
                            disp = _default_settings()["display"]
                            disp.update(loaded["display"])
                            defaults["display"] = disp
                        # Enforce max 5 RSS feeds
                        defaults["rss_feeds"] = list(defaults.get("rss_feeds", []))[: config.MAX_RSS_FEEDS]
                        self._data = defaults
                        logger.info("Loaded settings from %s", self._path)
                        return
            except Exception as exc:
                logger.warning("Could not load settings from %s: %s", self._path, exc)
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        try:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp_path = f"{self._path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp_path, self._path)
        except Exception as exc:
            logger.warning("Could not persist settings to %s: %s", self._path, exc)

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def get_rss_feeds(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._data.get("rss_feeds", []))[: config.MAX_RSS_FEEDS]

    def set_rss_feeds(self, feeds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if len(feeds) > config.MAX_RSS_FEEDS:
            raise ValueError(f"Maximum of {config.MAX_RSS_FEEDS} RSS feeds allowed.")
        cleaned: List[Dict[str, Any]] = []
        for idx, item in enumerate(feeds):
            url = str(item.get("url", "")).strip()
            if not url:
                continue
            name = str(item.get("name", "")).strip() or f"Feed {idx + 1}"
            feed_id = str(item.get("id", "")).strip() or f"feed-{uuid.uuid4().hex[:8]}"
            enabled = bool(item.get("enabled", True))
            cleaned.append({
                "id": feed_id,
                "name": name[:40],
                "url": url,
                "enabled": enabled,
            })
        if len(cleaned) > config.MAX_RSS_FEEDS:
            raise ValueError(f"Maximum of {config.MAX_RSS_FEEDS} RSS feeds allowed.")
        with self._lock:
            self._data["rss_feeds"] = cleaned
            self._save_unlocked()
            return list(cleaned)

    def add_rss_feed(self, name: str, url: str, enabled: bool = True) -> Dict[str, Any]:
        url = url.strip()
        if not url:
            raise ValueError("RSS feed URL is required.")
        with self._lock:
            feeds = list(self._data.get("rss_feeds", []))
            if len(feeds) >= config.MAX_RSS_FEEDS:
                raise ValueError(f"Maximum of {config.MAX_RSS_FEEDS} RSS feeds reached. Remove one first.")
            new_feed = {
                "id": f"feed-{uuid.uuid4().hex[:8]}",
                "name": (name.strip() or f"Feed {len(feeds) + 1}")[:40],
                "url": url,
                "enabled": bool(enabled),
            }
            feeds.append(new_feed)
            self._data["rss_feeds"] = feeds
            self._save_unlocked()
            return new_feed

    def delete_rss_feed(self, feed_id: str) -> bool:
        with self._lock:
            feeds = list(self._data.get("rss_feeds", []))
            updated = [f for f in feeds if f.get("id") != feed_id]
            if len(updated) == len(feeds):
                return False
            self._data["rss_feeds"] = updated
            self._save_unlocked()
            return True

    def toggle_rss_feed(self, feed_id: str, enabled: bool) -> Optional[Dict[str, Any]]:
        with self._lock:
            for f in self._data.get("rss_feeds", []):
                if f.get("id") == feed_id:
                    f["enabled"] = bool(enabled)
                    self._save_unlocked()
                    return dict(f)
            return None

    # --- Radio Station Presets & Audio Mode ---

    def get_radio_presets(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._data.get("radio_presets", []))

    def add_radio_preset(self, name: str, url: str, activate: bool = False) -> Dict[str, Any]:
        url = url.strip()
        if not url:
            raise ValueError("Radio stream URL is required.")
        with self._lock:
            presets = list(self._data.get("radio_presets", []))
            preset = {
                "id": f"radio-{uuid.uuid4().hex[:8]}",
                "name": (name.strip() or f"Station {len(presets) + 1}")[:50],
                "url": url,
            }
            presets.append(preset)
            self._data["radio_presets"] = presets
            if activate or not self._data.get("active_radio_id"):
                self._data["active_radio_id"] = preset["id"]
                self._data["audio_mode"] = "stream"
            self._save_unlocked()
            return preset

    def update_radio_preset(self, preset_id: str, name: str, url: str) -> Optional[Dict[str, Any]]:
        url = url.strip()
        if not url:
            raise ValueError("Radio stream URL is required.")
        with self._lock:
            for p in self._data.get("radio_presets", []):
                if p.get("id") == preset_id:
                    p["name"] = (name.strip() or p["name"])[:50]
                    p["url"] = url
                    self._save_unlocked()
                    return dict(p)
            return None

    def delete_radio_preset(self, preset_id: str) -> bool:
        with self._lock:
            presets = list(self._data.get("radio_presets", []))
            updated = [p for p in presets if p.get("id") != preset_id]
            if len(updated) == len(presets):
                return False
            self._data["radio_presets"] = updated
            if self._data.get("active_radio_id") == preset_id:
                self._data["active_radio_id"] = updated[0]["id"] if updated else None
            self._save_unlocked()
            return True

    def set_audio_selection(self, audio_mode: str, active_radio_id: Optional[str] = None) -> Dict[str, Any]:
        mode = audio_mode.strip().lower()
        if mode not in ("stream", "hum", "silent"):
            raise ValueError("audio_mode must be 'stream', 'hum', or 'silent'")
        with self._lock:
            self._data["audio_mode"] = mode
            if active_radio_id is not None:
                self._data["active_radio_id"] = active_radio_id
            self._save_unlocked()
            return self.get_active_audio()

    def get_active_audio(self) -> Dict[str, Any]:
        with self._lock:
            mode = self._data.get("audio_mode", "hum")
            active_id = self._data.get("active_radio_id")
            presets = self._data.get("radio_presets", [])
            active_preset = next((p for p in presets if p.get("id") == active_id), None)
            if active_preset is None and presets:
                active_preset = presets[0]
            return {
                "audio_mode": mode,
                "active_radio_id": active_preset["id"] if active_preset else None,
                "active_radio_name": active_preset["name"] if active_preset else None,
                "active_radio_url": active_preset["url"] if active_preset else "",
            }

    # --- Display & Banner Settings ---

    def get_display(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data.get("display", {}))

    def update_display(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            disp = dict(self._data.get("display", {}))
            for key in ("channel_number", "channel_name", "banner_logo", "banner_line_1", "banner_line_2", "banner_line_3"):
                if key in updates and updates[key] is not None:
                    disp[key] = str(updates[key]).strip()[:32]
            for float_key in ("page_duration", "typewriter_duration"):
                if float_key in updates and updates[float_key] is not None:
                    disp[float_key] = max(0.0, float(updates[float_key]))
            for bool_key in ("show_source_prefix", "scanlines", "crt_noise", "crt_vignette"):
                if bool_key in updates and updates[bool_key] is not None:
                    disp[bool_key] = bool(updates[bool_key])
            self._data["display"] = disp
            self._save_unlocked()
            return dict(disp)


settings_store = SettingsStore()
