import io
import logging
import math
import os
import random
import textwrap
import time
from datetime import datetime
from typing import List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFont

from app import config
from app.rss_fetcher import BulletinItem, feed_manager

logger = logging.getLogger("cable-bulletin.renderer")

# Candidate monospace fonts across Debian/Ubuntu Docker images & macOS
FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/Library/Fonts/Courier New Bold.ttf",
]

FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/Library/Fonts/Courier New.ttf",
]


def _load_font(candidates: List[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


class BulletinRenderer:
    """
    Renders 8-bit greyscale ('L' mode) frames emulating a vintage 1980s
    cable TV character generator bulletin board with CBC & CNN RSS feeds.
    """

    def __init__(self, width: int = config.WIDTH, height: int = config.HEIGHT) -> None:
        self.width = width
        self.height = height
        self.scale = height / 720.0

        # Load scaled monospace fonts
        self.font_header = _load_font(FONT_CANDIDATES_BOLD, int(26 * self.scale))
        self.font_sub = _load_font(FONT_CANDIDATES_BOLD, int(20 * self.scale))
        self.font_title = _load_font(FONT_CANDIDATES_BOLD, int(33 * self.scale))
        self.font_body = _load_font(FONT_CANDIDATES_REGULAR, int(25 * self.scale))
        self.font_index = _load_font(FONT_CANDIDATES_BOLD, int(23 * self.scale))
        self.font_meta = _load_font(FONT_CANDIDATES_BOLD, int(18 * self.scale))
        self.font_ticker = _load_font(FONT_CANDIDATES_BOLD, int(24 * self.scale))

        # Pre-rendered static background template (CRT bezel, boxes, header chrome)
        self._bg_template = self._build_bg_template()

        # Pre-rendered scanline + vignette multiplicative mask
        self._crt_mask = self._build_crt_mask()

        # Pre-rendered ring buffer of subtle RF static grain overlays
        self._noise_frames = self._build_noise_frames(count=8)
        self._noise_idx = 0

        # Cached scrolling ticker strip image
        self._cached_ticker_str: str = ""
        self._ticker_strip: Optional[Image.Image] = None
        self._ticker_strip_width: int = 1

        self._start_time = time.monotonic()

    def _s(self, val: int) -> int:
        return int(round(val * self.scale))

    def _build_bg_template(self) -> Image.Image:
        """Create the static greyscale character-generator chrome layer."""
        W, H = self.width, self.height
        img = Image.new("L", (W, H), color=10)
        draw = ImageDraw.Draw(img)

        m_x = self._s(36)
        m_y = self._s(26)

        # Outer CRT phosphor surface
        draw.rectangle([m_x, m_y, W - m_x, H - m_y], fill=22, outline=95, width=2)

        # Top header bar (bright greyscale banner)
        hdr_top = m_y + self._s(8)
        hdr_bot = hdr_top + self._s(48)
        draw.rectangle([m_x + self._s(8), hdr_top, W - m_x - self._s(8), hdr_bot], fill=215)

        # Channel number badge inside header bar (dark block on left)
        ch_box_right = m_x + self._s(138)
        draw.rectangle(
            [m_x + self._s(14), hdr_top + self._s(6), ch_box_right, hdr_bot - self._s(6)],
            fill=20,
        )
        ch_label = f"CH {config.CHANNEL_NUMBER}"
        draw.text(
            (m_x + self._s(28), hdr_top + self._s(10)),
            ch_label,
            fill=240,
            font=self.font_header,
        )

        # Channel / Station Title
        draw.text(
            (ch_box_right + self._s(18), hdr_top + self._s(10)),
            config.CHANNEL_NAME.upper(),
            fill=18,
            font=self.font_header,
        )

        # Sub-header bar (wire source & page status bar)
        sub_top = hdr_bot + self._s(8)
        sub_bot = sub_top + self._s(38)
        draw.rectangle(
            [m_x + self._s(8), sub_top, W - m_x - self._s(8), sub_bot],
            fill=48,
            outline=130,
            width=1,
        )

        # Main Bulletin Card Frame (double-line retro border)
        card_top = sub_bot + self._s(12)
        card_bot = H - m_y - self._s(76)
        card_left = m_x + self._s(8)
        card_right = W - m_x - self._s(8)

        draw.rectangle([card_left, card_top, card_right, card_bot], fill=16, outline=185, width=2)
        draw.rectangle(
            [
                card_left + self._s(6),
                card_top + self._s(6),
                card_right - self._s(6),
                card_bot - self._s(6),
            ],
            outline=95,
            width=1,
        )

        # Corner registration ticks inside card
        tick = self._s(12)
        for cx, cy in [
            (card_left + self._s(12), card_top + self._s(12)),
            (card_right - self._s(12), card_top + self._s(12)),
            (card_left + self._s(12), card_bot - self._s(12)),
            (card_right - self._s(12), card_bot - self._s(12)),
        ]:
            draw.line([(cx - 4, cy), (cx + 4, cy)], fill=170, width=1)
            draw.line([(cx, cy - 4), (cx, cy + 4)], fill=170, width=1)

        # Bottom Ticker Bar
        tkr_top = card_bot + self._s(10)
        tkr_bot = H - m_y - self._s(8)
        draw.rectangle(
            [card_left, tkr_top, card_right, tkr_bot],
            fill=32,
            outline=155,
            width=2,
        )

        return img

    def _build_crt_mask(self) -> Image.Image:
        """Build a multiplicative mask with horizontal CRT scanlines and corner vignette."""
        W, H = self.width, self.height
        mask = Image.new("L", (W, H), color=255)
        pixels = mask.load()

        cx, cy = W / 2.0, H / 2.0
        max_dist = math.hypot(cx, cy)

        for y in range(H):
            # Alternating horizontal scanline attenuation
            scan_factor = 0.84 if (config.SCANLINES and (y % 2 == 1)) else 1.0
            dy = (y - cy) / cy
            for x in range(W):
                if config.CRT_VIGNETTE:
                    dx = (x - cx) / cx
                    # Smooth super-elliptical CRT corner darkening
                    r2 = (dx * dx * 0.55) + (dy * dy * 0.55)
                    vig = max(0.55, 1.0 - (r2 * r2 * 0.65))
                else:
                    vig = 1.0
                val = int(255 * scan_factor * vig)
                pixels[x, y] = max(0, min(255, val))

        return mask

    def _build_noise_frames(self, count: int = 8) -> List[Image.Image]:
        """Pre-generate subtle low-amplitude RF static grain overlays."""
        W, H = self.width, self.height
        # Generate at 1/2 resolution and scale up slightly for authentic analog grain look
        nw, nh = max(1, W // 2), max(1, H // 2)
        frames: List[Image.Image] = []
        rng = random.Random(1984)
        for _ in range(count):
            buf = bytearray(nw * nh)
            for i in range(nw * nh):
                # Small snow specks
                r = rng.randint(0, 100)
                if r > 97:
                    buf[i] = rng.randint(14, 28)
                elif r > 80:
                    buf[i] = rng.randint(4, 10)
                else:
                    buf[i] = 0
            small = Image.frombytes("L", (nw, nh), bytes(buf))
            frames.append(small.resize((W, H), Image.NEAREST))
        return frames

    def _ensure_ticker_strip(self, ticker_text: str) -> None:
        if ticker_text == self._cached_ticker_str and self._ticker_strip is not None:
            return
        self._cached_ticker_str = ticker_text
        # Measure text width
        dummy = Image.new("L", (16, 16))
        ddraw = ImageDraw.Draw(dummy)
        bbox = ddraw.textbbox((0, 0), ticker_text, font=self.font_ticker)
        text_w = max(400, bbox[2] - bbox[0])
        strip_h = self._s(42)

        # Create a strip containing 2 copies so window slicing wraps seamlessly
        strip = Image.new("L", (text_w * 2, strip_h), color=32)
        sdraw = ImageDraw.Draw(strip)
        y_off = self._s(7)
        sdraw.text((0, y_off), ticker_text, fill=232, font=self.font_ticker)
        sdraw.text((text_w, y_off), ticker_text, fill=232, font=self.font_ticker)

        self._ticker_strip = strip
        self._ticker_strip_width = text_w

    def render_frame(self, now_mono: Optional[float] = None) -> Image.Image:
        """Render a single greyscale ('L') video frame for the current timestamp."""
        if now_mono is None:
            now_mono = time.monotonic()
        elapsed = max(0.0, now_mono - self._start_time)

        W, H = self.width, self.height
        m_x = self._s(36)
        m_y = self._s(26)

        frame = self._bg_template.copy()
        draw = ImageDraw.Draw(frame)

        # 1. Live Clock & Date in Top Header Bar
        now_dt = datetime.now()
        blink_colon = ":" if int(elapsed * 2) % 2 == 0 else " "
        if config.TIME_FORMAT_12H:
            time_str = now_dt.strftime(f"%a %b %d  %I{blink_colon}%M{blink_colon}%S %p").upper()
        else:
            time_str = now_dt.strftime(f"%a %b %d  %H{blink_colon}%M{blink_colon}%S").upper()

        hdr_top = m_y + self._s(8)
        clock_bbox = draw.textbbox((0, 0), time_str, font=self.font_header)
        clock_w = clock_bbox[2] - clock_bbox[0]
        draw.text(
            (W - m_x - self._s(22) - clock_w, hdr_top + self._s(10)),
            time_str,
            fill=16,
            font=self.font_header,
        )

        # 2. Determine Active Bulletin Card
        playlist = feed_manager.get_playlist()
        total_pages = max(1, len(playlist))
        page_dur = max(4.0, config.PAGE_DURATION)
        page_idx = int(elapsed // page_dur) % total_pages
        page_elapsed = elapsed % page_dur
        item: BulletinItem = playlist[page_idx]

        # 3. Sub-header Bar (Source Badge, Category, Page Number)
        hdr_bot = hdr_top + self._s(48)
        sub_top = hdr_bot + self._s(8)
        sub_bot = sub_top + self._s(38)

        # Source pill on left of sub-header
        src_label = f" {item.source} "
        src_bbox = draw.textbbox((0, 0), src_label, font=self.font_sub)
        src_w = (src_bbox[2] - src_bbox[0]) + self._s(16)
        # Differentiate CBC vs CNN in greyscale via high-contrast vs medium-contrast badge
        badge_fill = 235 if "CBC" in item.source else (195 if "CNN" in item.source else 245)
        draw.rectangle(
            [m_x + self._s(14), sub_top + self._s(5), m_x + self._s(14) + src_w, sub_bot - self._s(5)],
            fill=badge_fill,
        )
        draw.text(
            (m_x + self._s(22), sub_top + self._s(7)),
            src_label,
            fill=15,
            font=self.font_sub,
        )

        # Category & Wire Code
        cat_str = f"// {item.category}   [{item.wire_code}]"
        draw.text(
            (m_x + self._s(26) + src_w, sub_top + self._s(7)),
            cat_str,
            fill=225,
            font=self.font_sub,
        )

        # Page Counter on Right
        page_str = f"PAGE {page_idx + 1:02d} OF {total_pages:02d}"
        p_bbox = draw.textbbox((0, 0), page_str, font=self.font_sub)
        p_w = p_bbox[2] - p_bbox[0]
        draw.text(
            (W - m_x - self._s(22) - p_w, sub_top + self._s(7)),
            page_str,
            fill=235,
            font=self.font_sub,
        )

        # 4. Main Bulletin Card Content
        card_top = sub_bot + self._s(12)
        card_bot = H - m_y - self._s(76)
        card_left = m_x + self._s(8)
        card_right = W - m_x - self._s(8)

        inner_left = card_left + self._s(34)
        inner_right = card_right - self._s(34)

        if item.is_index:
            self._draw_index_card(
                draw, item, inner_left, inner_right, card_top, card_bot, page_elapsed, page_dur
            )
        else:
            self._draw_story_card(
                draw, item, inner_left, inner_right, card_top, card_bot, page_elapsed, page_dur
            )

        # 5. Bottom Scrolling News Ticker
        tkr_top = card_bot + self._s(10)
        tkr_bot = H - m_y - self._s(8)

        # Left "WIRE" label block in ticker
        lbl_text = " CBC / CNN WIRE "
        lbl_bbox = draw.textbbox((0, 0), lbl_text, font=self.font_sub)
        lbl_w = (lbl_bbox[2] - lbl_bbox[0]) + self._s(16)

        # Paste scrolling ticker slice first
        ticker_text = feed_manager.get_ticker_text()
        self._ensure_ticker_strip(ticker_text)
        if self._ticker_strip is not None:
            scroll_x = int(elapsed * config.TICKER_SPEED) % self._ticker_strip_width
            avail_w = max(10, (card_right - self._s(6)) - (card_left + lbl_w + self._s(10)))
            crop_right = min(scroll_x + avail_w, self._ticker_strip.width)
            cropped = self._ticker_strip.crop((scroll_x, 0, crop_right, self._ticker_strip.height))
            frame.paste(cropped, (card_left + lbl_w + self._s(8), tkr_top + self._s(4)))

        # Draw the left ticker badge over the left edge so text scrolls cleanly underneath it
        draw.rectangle(
            [card_left + self._s(4), tkr_top + self._s(4), card_left + lbl_w + self._s(4), tkr_bot - self._s(4)],
            fill=215,
        )
        draw.text(
            (card_left + self._s(12), tkr_top + self._s(11)),
            lbl_text,
            fill=15,
            font=self.font_sub,
        )

        # 6. Apply CRT Scanlines & Corner Vignette
        if config.SCANLINES or config.CRT_VIGNETTE:
            frame = ImageChops.multiply(frame, self._crt_mask)

        # 7. Apply Subtle Analog RF Grain Shimmer
        if config.CRT_NOISE and self._noise_frames:
            noise = self._noise_frames[self._noise_idx % len(self._noise_frames)]
            self._noise_idx += 1
            frame = ImageChops.add(frame, noise)

        return frame

    def _draw_story_card(
        self,
        draw: ImageDraw.ImageDraw,
        item: BulletinItem,
        left: int,
        right: int,
        top: int,
        bottom: int,
        page_elapsed: float,
        page_dur: float,
    ) -> None:
        # Typewriter character reveal ratio (0.0 -> 1.0 during TYPEWRITER_DURATION)
        tw_dur = max(0.1, config.TYPEWRITER_DURATION)
        reveal = min(1.0, page_elapsed / tw_dur)

        # Wrap headline (approx 48 chars at 1280px)
        headline_text = item.title.upper()
        title_lines = textwrap.wrap(headline_text, width=46)[:3]

        # Wrap summary body (approx 64 chars at 1280px)
        body_text = item.summary.upper()
        body_lines = textwrap.wrap(body_text, width=62)[:6]

        total_chars = sum(len(line) for line in title_lines) + sum(len(line) for line in body_lines)
        chars_to_show = int(math.ceil(total_chars * reveal))

        # Draw Headline
        y = top + self._s(26)
        title_line_h = self._s(42)
        rem = chars_to_show
        cursor_drawn = False

        for line in title_lines:
            if rem <= 0:
                break
            visible = line[:rem]
            rem -= len(line)
            if rem <= 0 and reveal < 1.0 and not cursor_drawn:
                visible += "█"
                cursor_drawn = True
            draw.text((left, y), visible, fill=245, font=self.font_title)
            y += title_line_h

        # Divider bar below headline
        div_y = top + self._s(164)
        draw.line([(left, div_y), (right, div_y)], fill=135, width=2)
        draw.line([(left, div_y + self._s(4)), (right, div_y + self._s(4))], fill=65, width=1)

        # Metadata banner between headline and body
        meta_y = div_y + self._s(12)
        meta_str = f"SOURCE: {item.source}   //   FILED: {item.published}   //   REF: {item.wire_code}"
        draw.text((left, meta_y), meta_str, fill=165, font=self.font_meta)

        # Draw Body Paragraphs
        body_y = meta_y + self._s(36)
        body_line_h = self._s(35)

        for idx, line in enumerate(body_lines):
            if rem <= 0:
                break
            visible = line[:rem]
            rem -= len(line)
            is_last_line = idx == len(body_lines) - 1
            if rem <= 0 and reveal < 1.0 and not cursor_drawn:
                visible += "█"
                cursor_drawn = True
            elif reveal >= 1.0 and is_last_line:
                # Blinking terminal block cursor at end of dispatch
                cursor_char = " █" if int(page_elapsed * 2.5) % 2 == 0 else " _"
                visible += cursor_char
            draw.text((left, body_y), visible, fill=215, font=self.font_body)
            body_y += body_line_h

        # Footer bar inside card: Station ID + Page Hold Progress Bar
        foot_y = bottom - self._s(36)
        draw.text(
            (left, foot_y),
            f"TELETYPE TERMINAL // {config.STATION_ID}",
            fill=130,
            font=self.font_meta,
        )

        # Segmented progress bar on bottom-right of card
        prog_ratio = min(1.0, max(0.0, page_elapsed / page_dur))
        bar_w = self._s(200)
        bar_h = self._s(14)
        bar_x = right - bar_w
        bar_y = foot_y + self._s(3)
        draw.rectangle([bar_x, bar_y, right, bar_y + bar_h], fill=28, outline=140, width=1)
        fill_w = int((bar_w - 4) * prog_ratio)
        if fill_w > 0:
            draw.rectangle(
                [bar_x + 2, bar_y + 2, bar_x + 2 + fill_w, bar_y + bar_h - 2],
                fill=200,
            )

    def _draw_index_card(
        self,
        draw: ImageDraw.ImageDraw,
        item: BulletinItem,
        left: int,
        right: int,
        top: int,
        bottom: int,
        page_elapsed: float,
        page_dur: float,
    ) -> None:
        y = top + self._s(24)
        draw.text(
            (left, y),
            "CBC NEWS & CNN WIRE // HEADLINE RUNDOWN",
            fill=245,
            font=self.font_title,
        )
        y += self._s(48)
        draw.line([(left, y), (right, y)], fill=160, width=2)
        y += self._s(16)

        row_h = self._s(52)
        for idx, line in enumerate(item.index_lines[:5]):
            row_top = y + idx * row_h
            row_bot = row_top + row_h - self._s(8)
            bg_val = 36 if idx % 2 == 0 else 24
            draw.rectangle([left, row_top, right, row_bot], fill=bg_val, outline=85, width=1)
            draw.text(
                (left + self._s(14), row_top + self._s(10)),
                line.upper(),
                fill=230,
                font=self.font_index,
            )

        foot_y = bottom - self._s(36)
        draw.text(
            (left, foot_y),
            f"CONTINUOUS 24-HOUR BULLETIN SERVICE // {config.STATION_ID}",
            fill=140,
            font=self.font_meta,
        )

    def render_png_bytes(self) -> bytes:
        img = self.render_frame()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


renderer = BulletinRenderer()
