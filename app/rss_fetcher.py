import html
import logging
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List, Optional

from app import config

logger = logging.getLogger("cable-bulletin.rss")

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

# Normalize Unicode punctuation to clean vintage teletext/CG equivalents
UNICODE_MAP = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "--",
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
    source: str          # "CBC NEWS" or "CNN WIRE" or "WIRE INDEX"
    category: str        # e.g., "TOP STORIES", "WORLD", "CANADA"
    title: str           # Headline
    summary: str         # Body text
    published: str       # Formatted date/time string
    wire_code: str = ""  # e.g., "CBC-104" or "CNN-209"
    is_index: bool = False
    index_lines: List[str] = field(default_factory=list)


class RSSFeedManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cbc_items: List[BulletinItem] = []
        self._cnn_items: List[BulletinItem] = []
        self._playlist: List[BulletinItem] = self._build_standby_playlist()
        self._ticker_text: str = (
            "*** CATV-03 COMMUNITY WIRE SERVICE *** "
            "INITIALIZING CBC NEWS AND CNN SATELLITE RSS FEEDS ... PLEASE STAND BY ***"
        )
        self._last_updated: Optional[datetime] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _build_standby_playlist(self) -> List[BulletinItem]:
        now_str = datetime.now().strftime("%b %d %H:%M").upper()
        return [
            BulletinItem(
                source="CBC NEWS",
                category="SYSTEM NOTICE",
                title="CONNECTING TO CANADIAN BROADCASTING CORP. WIRE SERVICE",
                summary=(
                    "CABLETEXT TERMINAL IS SYNCHRONIZING WITH CBC RSS SATELLITE "
                    "FEEDS. LIVE HEADLINES AND DISPATCHES WILL APPEAR MOMENTARILY."
                ),
                published=now_str,
                wire_code="SYS-001",
            ),
            BulletinItem(
                source="CNN WIRE",
                category="SYSTEM NOTICE",
                title="CONNECTING TO CABLE NEWS NETWORK TELETYPE FEED",
                summary=(
                    "RECEIVING NATIONAL AND INTERNATIONAL WIRE BULLETINS FROM "
                    "CNN HEADQUARTERS. CONTINUOUS 24-HOUR COVERAGE."
                ),
                published=now_str,
                wire_code="SYS-002",
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
        # Fetch immediately on startup
        self.refresh_now()
        interval_sec = max(60, config.REFRESH_INTERVAL_MINUTES * 60)
        while self._running:
            time.sleep(interval_sec)
            if not self._running:
                break
            self.refresh_now()

    def _infer_category_from_url(self, url: str, default_cat: str) -> str:
        lower = url.lower()
        if "world" in lower:
            return "WORLD NEWS"
        if "canada" in lower:
            return "CANADA"
        if "politics" in lower:
            return "POLITICS"
        if "tech" in lower:
            return "TECHNOLOGY"
        if "business" in lower or "money" in lower:
            return "BUSINESS"
        if "latest" in lower:
            return "BREAKING / LATEST"
        return default_cat

    def _fetch_single_feed(self, url: str, source_label: str, prefix: str) -> List[BulletinItem]:
        items: List[BulletinItem] = []
        default_cat = self._infer_category_from_url(url, "TOP STORIES")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; CableBulletinHLS/1.0; "
                    "+https://localhost)"
                ),
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw_bytes = resp.read()
        except Exception as exc:
            logger.warning("Failed to fetch RSS feed %s: %s", url, exc)
            return items

        try:
            root = ET.fromstring(raw_bytes)
        except ET.ParseError as exc:
            logger.warning("Failed to parse XML from %s: %s", url, exc)
            return items

        # Find all <item> (RSS) or <entry> (Atom)
        xml_items = root.findall(".//item")
        if not xml_items:
            xml_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for idx, elem in enumerate(xml_items):
            title_el = elem.find("title")
            if title_el is None:
                title_el = elem.find("{http://www.w3.org/2005/Atom}title")
            title = clean_text(title_el.text if title_el is not None else "", max_chars=180)
            if not title:
                continue

            desc_el = elem.find("description")
            if desc_el is None:
                desc_el = elem.find("{http://www.w3.org/2005/Atom}summary")
            summary = clean_text(desc_el.text if desc_el is not None else "", max_chars=440)

            cat_el = elem.find("category")
            cat_text = clean_text(cat_el.text if cat_el is not None else "", max_chars=28).upper()
            if not cat_text or len(cat_text) > 24:
                cat_text = default_cat

            pub_el = elem.find("pubDate")
            if pub_el is None:
                pub_el = elem.find("{http://www.w3.org/2005/Atom}updated")
            pub_str = parse_pub_date(pub_el.text if pub_el is not None else None)

            # Some CNN RSS feeds omit description or repeat the headline
            if not summary or summary.lower() == title.lower():
                summary = (
                    f"DISPATCH VIA {source_label} ({cat_text}) -- "
                    f"WIRE TIMESTAMP {pub_str}. STAY TUNED TO CHANNEL {config.CHANNEL_NUMBER} "
                    f"FOR CONTINUOUS UPDATES FROM CBC AND CNN."
                )

            items.append(
                BulletinItem(
                    source=source_label,
                    category=cat_text,
                    title=title,
                    summary=summary,
                    published=pub_str,
                    wire_code=f"{prefix}-{101 + idx:03d}",
                )
            )

        return items

    def _dedupe_and_limit(self, items: List[BulletinItem], limit: int) -> List[BulletinItem]:
        seen = set()
        result: List[BulletinItem] = []
        for item in items:
            key = item.title.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
            if len(result) >= limit:
                break
        return result

    def refresh_now(self) -> dict:
        logger.info("Refreshing CBC and CNN RSS feeds...")
        cbc_collected: List[BulletinItem] = []
        for url in config.CBC_FEEDS:
            cbc_collected.extend(self._fetch_single_feed(url, "CBC NEWS", "CBC"))

        cnn_collected: List[BulletinItem] = []
        for url in config.CNN_FEEDS:
            cnn_collected.extend(self._fetch_single_feed(url, "CNN WIRE", "CNN"))

        cbc_final = self._dedupe_and_limit(cbc_collected, config.MAX_ITEMS_PER_SOURCE)
        cnn_final = self._dedupe_and_limit(cnn_collected, config.MAX_ITEMS_PER_SOURCE)

        # Re-number wire codes cleanly
        for i, item in enumerate(cbc_final):
            item.wire_code = f"CBC-{101 + i:03d}"
        for i, item in enumerate(cnn_final):
            item.wire_code = f"CNN-{201 + i:03d}"

        with self._lock:
            if cbc_final:
                self._cbc_items = cbc_final
            if cnn_final:
                self._cnn_items = cnn_final

            interleaved = self._build_interleaved_playlist(self._cbc_items, self._cnn_items)
            if interleaved:
                self._playlist = interleaved
                self._ticker_text = self._build_ticker_text(self._cbc_items, self._cnn_items)
                self._last_updated = datetime.now()

        logger.info(
            "RSS refresh complete: %d CBC items, %d CNN items, %d total pages",
            len(self._cbc_items),
            len(self._cnn_items),
            len(self._playlist),
        )
        return self.get_status()

    def _build_interleaved_playlist(
        self, cbc: List[BulletinItem], cnn: List[BulletinItem]
    ) -> List[BulletinItem]:
        if not cbc and not cnn:
            return []

        raw_cards: List[BulletinItem] = []
        max_len = max(len(cbc), len(cnn))
        for i in range(max_len):
            if i < len(cbc):
                raw_cards.append(cbc[i])
            if i < len(cnn):
                raw_cards.append(cnn[i])

        # Insert periodic WIRE INDEX summary cards every N stories
        playlist: List[BulletinItem] = []
        every = max(0, config.INDEX_CARD_EVERY)
        for idx, card in enumerate(raw_cards):
            if every > 0 and idx > 0 and idx % every == 0:
                upcoming = raw_cards[idx : idx + 5]
                if not upcoming:
                    upcoming = raw_cards[:5]
                lines = [
                    f"[{u.source[:3]}] {u.title[:66] + ('...' if len(u.title) > 66 else '')}"
                    for u in upcoming
                ]
                playlist.append(
                    BulletinItem(
                        source="WIRE INDEX",
                        category="HEADLINE SUMMARY",
                        title="UPCOMING ON THE CBC / CNN NEWS WIRE",
                        summary="",
                        published=datetime.now().strftime("%b %d %H:%M").upper(),
                        wire_code=f"IDX-{idx // every:02d}",
                        is_index=True,
                        index_lines=lines,
                    )
                )
            playlist.append(card)

        return playlist

    def _build_ticker_text(
        self, cbc: List[BulletinItem], cnn: List[BulletinItem]
    ) -> str:
        segments: List[str] = [
            f"*** {config.STATION_ID} -- CONTINUOUS CBC & CNN TELETYPE DISPATCH ***"
        ]
        max_len = max(len(cbc), len(cnn))
        for i in range(min(max_len, 12)):
            if i < len(cbc):
                segments.append(f"[CBC] {cbc[i].title.upper()}")
            if i < len(cnn):
                segments.append(f"[CNN] {cnn[i].title.upper()}")
        return "   ///   ".join(segments) + "   ///   "

    def get_playlist(self) -> List[BulletinItem]:
        with self._lock:
            return list(self._playlist)

    def get_ticker_text(self) -> str:
        with self._lock:
            return self._ticker_text

    def get_status(self) -> dict:
        with self._lock:
            return {
                "cbc_count": len(self._cbc_items),
                "cnn_count": len(self._cnn_items),
                "total_pages": len(self._playlist),
                "last_updated": (
                    self._last_updated.isoformat() if self._last_updated else None
                ),
                "cbc_feeds": config.CBC_FEEDS,
                "cnn_feeds": config.CNN_FEEDS,
            }


feed_manager = RSSFeedManager()
