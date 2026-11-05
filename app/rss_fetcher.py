import html
import logging
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from app import config
from app.settings_store import settings_store

logger = logging.getLogger("cable-bulletin.rss")

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

UNICODE_MAP = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": " - ",
    "\u2026": "...",
    "\u00a0": " ",
    "\u2022": "*",
})


def clean_text(raw: Optional[str], max_chars: int = 520) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.translate(UNICODE_MAP)
    text = WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > max_chars:
        cut = text[: max_chars - 3].rsplit(" ", 1)[0]
        text = f"{cut}..."
    return text


def format_broadcast_copy(title: str, summary: str, source_name: str = "", show_prefix: bool = False) -> str:
    """
    Format an RSS item into a single concise 4-to-6 line broadcast wire paragraph
    matching the ASN Cable 10 character generator reference layout.
    """
    base = summary.strip() if summary and len(summary.strip()) >= 35 else title.strip()
    if not base:
        base = title.strip()

    max_len = 175
    if len(base) > max_len:
        chunk = base[:max_len]
        sent_end = max(chunk.rfind(". "), chunk.rfind("? "), chunk.rfind("! "))
        if sent_end >= 55:
            base = chunk[: sent_end + 1].strip()
        elif 30 <= len(title.strip()) <= max_len:
            base = title.strip()
        else:
            cut = chunk[: max_len - 3].rsplit(" ", 1)[0].rstrip(",;:-")
            base = f"{cut}..."

    base = base.upper()
    if base and base[-1] not in ".!?\"'":
        base += "."

    if show_prefix and source_name:
        base = f"[{source_name.upper()}] {base}"

    return base


def parse_pub_date(raw_date: Optional[str]) -> str:
    if not raw_date:
        return datetime.now().strftime("%b %d %H:%M").upper()
    try:
        dt = parsedate_to_datetime(raw_date.strip())
        local_dt = dt.astimezone()
        return local_dt.strftime("%b %d %H:%M").upper()
    except Exception:
        return raw_date.strip()[:16].upper()


@dataclass
class BulletinItem:
    feed_id: str
    source: str          # Feed display name
    title: str           # Original headline
    summary: str         # Cleaned description
    broadcast_copy: str  # Upper-case 4-6 line broadcast paragraph shown on screen
    published: str       # Formatted date/time string
    wire_code: str = ""


class RSSFeedManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._playlist: List[BulletinItem] = self._build_standby_playlist()
        self._feed_stats: List[Dict[str, Any]] = []
        self._last_updated: Optional[datetime] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _build_standby_playlist(self) -> List[BulletinItem]:
        now_str = datetime.now().strftime("%b %d %H:%M").upper()
        return [
            BulletinItem(
                feed_id="system",
                source="SYSTEM",
                title="CABLE BULLETIN BOARD INITIALIZING",
                summary="SYNCHRONIZING RSS FEEDS. ADD OR CONFIGURE UP TO 5 FEEDS IN THE ADMIN PORTAL.",
                broadcast_copy=(
                    "CABLE BULLETIN BOARD IS SYNCHRONIZING WITH CONFIGURED RSS "
                    "FEEDS. LIVE HEADLINES WILL APPEAR MOMENTARILY."
                ),
                published=now_str,
                wire_code="SYS-001",
            ),
        ]

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        self.refresh_now()
        interval_sec = max(60, config.REFRESH_INTERVAL_MINUTES * 60)
        while self._running:
            time.sleep(interval_sec)
            if not self._running:
                break
            self.refresh_now()

    def _fetch_single_feed(
        self, feed_cfg: Dict[str, Any], feed_num: int, show_prefix: bool
    ) -> tuple[List[BulletinItem], Optional[str]]:
        url = feed_cfg.get("url", "").strip()
        name = feed_cfg.get("name", f"Feed {feed_num}").strip()
        feed_id = feed_cfg.get("id", f"feed-{feed_num}")
        items: List[BulletinItem] = []

        if not url:
            return items, "Empty URL"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; CableBulletinHLS/1.0; +https://localhost)"
                ),
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw_bytes = resp.read()
        except Exception as exc:
            logger.warning("Failed to fetch RSS feed %s (%s): %s", name, url, exc)
            return items, str(exc)

        try:
            root = ET.fromstring(raw_bytes)
        except ET.ParseError as exc:
            logger.warning("Failed to parse XML from %s (%s): %s", name, url, exc)
            return items, f"XML parse error: {exc}"

        xml_items = root.findall(".//item")
        if not xml_items:
            xml_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        seen_titles = set()
        for idx, elem in enumerate(xml_items):
            title_el = elem.find("title")
            if title_el is None:
                title_el = elem.find("{http://www.w3.org/2005/Atom}title")
            title = clean_text(title_el.text if title_el is not None else "", max_chars=200)
            if not title:
                continue

            key = title.lower().strip()
            if key in seen_titles:
                continue
            seen_titles.add(key)

            desc_el = elem.find("description")
            if desc_el is None:
                desc_el = elem.find("{http://www.w3.org/2005/Atom}summary")
            if desc_el is None:
                desc_el = elem.find("{http://purl.org/rss/1.0/modules/content/}encoded")
            summary = clean_text(desc_el.text if desc_el is not None else "", max_chars=360)

            pub_el = elem.find("pubDate")
            if pub_el is None:
                pub_el = elem.find("{http://www.w3.org/2005/Atom}updated")
            if pub_el is None:
                pub_el = elem.find("{http://purl.org/dc/elements/1.1/}date")
            pub_str = parse_pub_date(pub_el.text if pub_el is not None else None)

            b_copy = format_broadcast_copy(title, summary, name, show_prefix=show_prefix)
            if not summary:
                summary = b_copy

            items.append(
                BulletinItem(
                    feed_id=feed_id,
                    source=name,
                    title=title,
                    summary=summary,
                    broadcast_copy=b_copy,
                    published=pub_str,
                    wire_code=f"F{feed_num}-{101 + len(items):03d}",
                )
            )
            if len(items) >= config.MAX_ITEMS_PER_FEED:
                break

        return items, None

    def refresh_now(self) -> dict:
        configured_feeds = settings_store.get_rss_feeds()
        disp = settings_store.get_display()
        show_prefix = bool(disp.get("show_source_prefix", False))

        logger.info("Refreshing %d configured RSS feeds...", len(configured_feeds))
        buckets: List[List[BulletinItem]] = []
        stats: List[Dict[str, Any]] = []

        for idx, feed_cfg in enumerate(configured_feeds[: config.MAX_RSS_FEEDS]):
            enabled = bool(feed_cfg.get("enabled", True))
            if not enabled:
                stats.append({
                    "id": feed_cfg.get("id"),
                    "name": feed_cfg.get("name"),
                    "url": feed_cfg.get("url"),
                    "enabled": False,
                    "item_count": 0,
                    "error": None,
                })
                continue

            items, err = self._fetch_single_feed(feed_cfg, idx + 1, show_prefix)
            if items:
                buckets.append(items)
            stats.append({
                "id": feed_cfg.get("id"),
                "name": feed_cfg.get("name"),
                "url": feed_cfg.get("url"),
                "enabled": True,
                "item_count": len(items),
                "error": err,
            })

        # Round-robin interleave stories across all active feeds
        interleaved: List[BulletinItem] = []
        seen_global = set()
        if buckets:
            max_len = max(len(b) for b in buckets)
            for i in range(max_len):
                for b in buckets:
                    if i < len(b):
                        candidate = b[i]
                        k = candidate.title.lower().strip()
                        if k not in seen_global:
                            seen_global.add(k)
                            interleaved.append(candidate)

        with self._lock:
            self._feed_stats = stats
            if interleaved:
                self._playlist = interleaved
            elif not configured_feeds:
                self._playlist = [
                    BulletinItem(
                        feed_id="empty",
                        source="NO FEEDS",
                        title="NO RSS FEEDS CONFIGURED",
                        summary="OPEN THE ADMIN PORTAL TO ADD UP TO 5 RSS FEEDS.",
                        broadcast_copy=(
                            "NO RSS FEEDS ARE CURRENTLY ENABLED. OPEN THE ADMIN "
                            "PORTAL TO ADD UP TO 5 CUSTOM RSS NEWS FEEDS."
                        ),
                        published=datetime.now().strftime("%b %d %H:%M").upper(),
                        wire_code="SYS-000",
                    )
                ]
            self._last_updated = datetime.now()

        logger.info("RSS refresh complete: %d total stories across %d feeds", len(interleaved), len(stats))
        return self.get_status()

    def get_playlist(self) -> List[BulletinItem]:
        with self._lock:
            return list(self._playlist)

    def get_status(self) -> dict:
        with self._lock:
            return {
                "total_pages": len(self._playlist),
                "max_feeds": config.MAX_RSS_FEEDS,
                "last_updated": (
                    self._last_updated.isoformat() if self._last_updated else None
                ),
                "feeds": list(self._feed_stats),
            }


feed_manager = RSSFeedManager()
