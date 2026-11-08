import io
import logging
import math
import os
import random
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from app import config
from app.rss_fetcher import BulletinItem, feed_manager
from app.settings_store import settings_store

logger = logging.getLogger("cable-bulletin.renderer")

ColorRGB = Tuple[int, int, int]

# Slab-serif bold monospace fonts (for the middle news bulletin text, matching ASN reference)
SLAB_MONO_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/courier-prime/CourierPrime-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/Library/Fonts/Courier New Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]

# Bold sans-serif fonts (for the top Date/Time bar and bottom ASN / Cable 10 banner)
SANS_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _load_font(candidates: List[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, max(8, size))
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_indented_story(text: str, width: int = 29, indent_spaces: int = 3, max_lines: int = 6) -> List[str]:
    """
    Wraps uppercase story text with the first line indented by `indent_spaces` spaces,
    matching the ASN Cable 10 character generator layout:
       PRIME MINISTER PAUL MARTIN
    TOLD HIS CAUCUS THAT HE'S
    PROUD OF WHAT THE LIBERAL
    GOVERNMENT HAS ACCOMPLISHED IN
    THE LAST 17 MONTHS.
    """
    words = text.strip().split()
    if not words:
        return []

    lines: List[str] = []
    current = " " * indent_spaces
    first_line = True

    for word in words:
        limit = width
        if len(current.strip()) == 0:
            current = (" " * indent_spaces if first_line else "") + word
        elif len(current) + 1 + len(word) <= limit:
            current += " " + word
        else:
            lines.append(current)
            first_line = False
            if len(lines) >= max_lines:
                break
            current = word

    if len(lines) < max_lines and current.strip():
        lines.append(current)

    return lines[:max_lines]


class BulletinRenderer:
    """
    Renders 24-bit RGB colour frames replicating the vintage
    ASN / Cable 10 3-band character generator layout with dynamic resolution scaling.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._start_time = time.monotonic()
        v = settings_store.get_video()
        self._init_dimensions(v["width"], v["height"])

    def _init_dimensions(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.scale_x = width / 1280.0
        self.scale_y = height / 720.0
        self.scale = min(self.scale_x, self.scale_y)

        # Band Y-coordinates (matching the reference photo's proportions)
        self.top_bar_h = self._sy(112)      # ~15.5% height
        self.bot_banner_y = self._sy(520)   # ~72.2% height (middle band is 112..520)

        # Fonts scaled proportionally
        self.font_clock = _load_font(SANS_BOLD_CANDIDATES, self._s(42))
        self.font_story = _load_font(SLAB_MONO_BOLD_CANDIDATES, self._s(44))
        self.font_watermark = _load_font(SANS_BOLD_CANDIDATES, self._s(34))
        self.font_logo = _load_font(SANS_BOLD_CANDIDATES, self._s(156))
        self.font_promo_main = _load_font(SANS_BOLD_CANDIDATES, self._s(46))
        self.font_promo_sub = _load_font(SANS_BOLD_CANDIDATES, self._s(31))

        self._cached_banner_key: Optional[Tuple[str, str, str, str, int, int]] = None
        self._bg_template: Image.Image = Image.new("RGB", (self.width, self.height), color=(12, 58, 128))

        self._scanline_mask = self._build_mask(scanlines=True, vignette=True)
        self._scanline_only_mask = self._build_mask(scanlines=True, vignette=False)
        self._vignette_only_mask = self._build_mask(scanlines=False, vignette=True)

        self._noise_frames = self._build_noise_frames(count=8)
        self._noise_idx = 0

    def reconfigure(self, width: int, height: int) -> None:
        with self._lock:
            if width != self.width or height != self.height:
                logger.info("Reconfiguring BulletinRenderer resolution to %dx%d", width, height)
                self._init_dimensions(width, height)

    def _s(self, val: float) -> int:
        return max(1, int(round(val * self.scale)))

    def _sx(self, val: float) -> int:
        return int(round(val * self.scale_x))

    def _sy(self, val: float) -> int:
        return int(round(val * self.scale_y))

    def _draw_wide_text_with_shadow(
        self,
        target: Image.Image,
        pos: Tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        fill: ColorRGB = (225, 232, 248),
        shadow_fill: ColorRGB = (8, 18, 42),
        shadow_offset: Tuple[int, int] = (3, 3),
        stretch_x: float = 1.12,
        letter_spacing: int = 0,
    ) -> int:
        if not text:
            return 0

        dummy = ImageDraw.Draw(target)
        if letter_spacing > 0:
            total_w = 0
            max_h = self._s(60)
            for ch in text:
                bb = dummy.textbbox((0, 0), ch, font=font)
                total_w += (bb[2] - bb[0]) + letter_spacing
                max_h = max(max_h, bb[3] - bb[1] + self._s(20))
        else:
            bb = dummy.textbbox((0, 0), text, font=font)
            total_w = max(1, bb[2] - bb[0] + self._s(16))
            max_h = max(1, bb[3] - bb[1] + self._s(24))

        pad = self._s(12)
        layer_w = total_w + pad * 2
        layer_h = max_h + pad * 2

        txt_mask = Image.new("L", (layer_w, layer_h), color=0)
        mdraw = ImageDraw.Draw(txt_mask)

        if letter_spacing > 0:
            cx = pad
            for ch in text:
                mdraw.text((cx, pad), ch, fill=255, font=font)
                bb = mdraw.textbbox((0, 0), ch, font=font)
                cx += (bb[2] - bb[0]) + letter_spacing
        else:
            mdraw.text((pad, pad), text, fill=255, font=font)

        if abs(stretch_x - 1.0) > 0.01:
            stretched_w = max(1, int(round(layer_w * stretch_x)))
            txt_mask = txt_mask.resize((stretched_w, layer_h), Image.BILINEAR)

        x, y = pos
        sx, sy = shadow_offset
        target.paste(shadow_fill, (x - pad + sx, y - pad + sy), txt_mask)
        target.paste(fill, (x - pad, y - pad), txt_mask)

        return int(round(total_w * stretch_x))

    def _build_3d_metallic_logo(self, logo_text: str) -> Tuple[Image.Image, Image.Image]:
        W_box = self._s(560)
        H_box = self._s(190)

        face_mask = Image.new("L", (W_box, H_box), color=0)
        fdraw = ImageDraw.Draw(face_mask)
        fdraw.text((self._s(36), self._s(10)), logo_text, fill=255, font=self.font_logo)

        shear = 0.16
        face_mask = face_mask.transform(
            (W_box, H_box),
            Image.AFFINE,
            (1.0, shear, -self._s(18), 0.0, 1.0, 0.0),
            resample=Image.BICUBIC,
        )

        canvas = Image.new("RGB", (W_box, H_box), color=(0, 0, 0))
        alpha = Image.new("L", (W_box, H_box), color=0)

        depth = max(3, self._s(14))
        for d in range(depth, 0, -1):
            ox = -int(d * 0.6)
            oy = int(d * 0.85)
            shifted = ImageChops.offset(face_mask, ox, oy)
            sdraw = ImageDraw.Draw(shifted)
            if ox < 0:
                sdraw.rectangle([W_box + ox, 0, W_box, H_box], fill=0)
            if oy > 0:
                sdraw.rectangle([0, 0, W_box, oy], fill=0)
            ratio = (depth - d) / float(max(1, depth))
            extrude_color = (
                int(14 + ratio * 24),
                int(18 + ratio * 30),
                int(72 + ratio * 75),
            )
            canvas.paste(extrude_color, (0, 0), shifted)
            alpha = ImageChops.lighter(alpha, shifted)

        r_shadow = ImageChops.offset(face_mask, self._s(8), self._s(8)).filter(ImageFilter.GaussianBlur(max(1, self._s(3))))
        canvas.paste((10, 6, 28), (0, 0), r_shadow)
        alpha = ImageChops.lighter(alpha, r_shadow)

        grad = Image.new("RGB", (W_box, H_box), color=(110, 130, 235))
        gdraw = ImageDraw.Draw(grad)
        top_y = self._s(18)
        bot_y = self._s(165)
        span = max(1, bot_y - top_y)
        for y in range(H_box):
            t = max(0.0, min(1.0, (y - top_y) / float(span)))
            if t < 0.38:
                u = t / 0.38
                r = int(125 + u * 112)
                g = int(142 + u * 98)
                b = int(235 + u * 20)
            elif t < 0.56:
                u = (t - 0.38) / 0.18
                r = int(237 - u * 132)
                g = int(240 - u * 122)
                b = int(255 - u * 15)
            else:
                u = (t - 0.56) / 0.44
                r = int(105 - u * 55)
                g = int(118 - u * 52)
                b = int(240 - u * 35)
            gdraw.line(
                [(0, y), (W_box, y)],
                fill=(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))),
            )

        eroded = face_mask.filter(ImageFilter.MinFilter(3))
        edge_bevel = ImageChops.subtract(face_mask, eroded)

        canvas.paste(grad, (0, 0), face_mask)
        canvas.paste((235, 240, 255), (0, 0), edge_bevel)
        alpha = ImageChops.lighter(alpha, face_mask)

        return canvas, alpha

    def _build_bg_template(
        self, banner_logo: str, line1: str, line2: str, line3: str
    ) -> Image.Image:
        W, H = self.width, self.height
        img = Image.new("RGB", (W, H), color=(12, 58, 128))
        draw = ImageDraw.Draw(img)

        # --- 1. TOP BAND (Warm gunmetal grey bar with 3D bevel) ---
        draw.rectangle([0, 0, W, self.top_bar_h - self._sy(6)], fill=(96, 96, 94))
        draw.rectangle(
            [0, self.top_bar_h - self._sy(6), W, self.top_bar_h - self._sy(3)],
            fill=(74, 74, 72),
        )
        draw.rectangle(
            [0, self.top_bar_h - self._sy(3), W, self.top_bar_h],
            fill=(36, 38, 42),
        )
        draw.line([(0, self.top_bar_h), (W, self.top_bar_h)], fill=(90, 122, 168), width=1)

        # --- 2. MIDDLE BAND (Classic ASN Character Generator Royal Blue) ---
        draw.rectangle([0, self.top_bar_h + 1, W, self.bot_banner_y - 1], fill=(12, 58, 128))

        # --- 3. BOTTOM BAND (ASN Purple/Indigo Graphic Promo Banner) ---
        by = self.bot_banner_y
        bh = max(1, H - by)

        for y in range(by, H):
            rel = (y - by) / float(bh)
            r = int(56 - rel * 32)
            g = int(16 - rel * 8)
            b = int(112 - rel * 48)
            draw.line([(0, y), (W, y)], fill=(max(12, r), max(6, g), max(38, b)))

        glow = Image.new("RGB", (W, bh), color=(0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        gdraw.ellipse(
            [self._sx(40), -self._sy(35), self._sx(690), bh + self._sy(40)],
            fill=(68, 18, 105),
        )
        gdraw.ellipse(
            [self._sx(600), self._sy(5), self._sx(1200), bh + self._sy(35)],
            fill=(16, 22, 65),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(max(2, self._s(28))))
        img.paste(ImageChops.add(img.crop((0, by, W, H)), glow), (0, by))
        draw = ImageDraw.Draw(img)

        wm_layer = Image.new("RGB", (W, bh), color=(0, 0, 0))
        wdraw = ImageDraw.Draw(wm_layer)
        for wx in range(-self._sx(40), self._sx(700), max(20, self._sx(170))):
            for wy in range(-self._sy(10), bh, max(12, self._sy(52))):
                wdraw.rectangle(
                    [wx, wy, wx + self._s(135), wy + self._s(36)],
                    outline=(32, 24, 58),
                    width=max(1, self._s(2)),
                )
                wdraw.text(
                    (wx + self._s(10), wy + self._s(2)),
                    "NEWS",
                    fill=(36, 28, 66),
                    font=self.font_watermark,
                )
        wm_layer = wm_layer.rotate(8, resample=Image.BILINEAR, expand=False)
        img.paste(ImageChops.add(img.crop((0, by, W, H)), wm_layer), (0, by))
        draw = ImageDraw.Draw(img)

        vanish_x = self._sx(520)
        vanish_y = by - self._sy(90)
        grid_color = (76, 72, 126)
        for gx in range(-self._sx(200), W + self._sx(500), max(20, self._sx(95))):
            draw.line([(vanish_x, vanish_y), (gx, H)], fill=grid_color, width=max(1, self._s(2)))
        for step in (0.18, 0.36, 0.56, 0.78, 0.94):
            gy = int(by + step * bh)
            draw.line([(0, gy), (W, gy)], fill=(66, 62, 114), width=max(1, self._s(2)))

        draw.line([(0, by), (W, by)], fill=(8, 22, 58), width=2)
        draw.line([(0, by + 2), (W, by + 2)], fill=(115, 148, 205), width=2)
        draw.line([(0, by + 4), (W, by + 4)], fill=(38, 28, 82), width=1)

        if banner_logo:
            logo_img, logo_mask = self._build_3d_metallic_logo(banner_logo)
            img.paste(logo_img, (self._sx(165), by + self._sy(8)), logo_mask)

        right_center_x = self._sx(905)
        promo_fill = (232, 232, 242)
        promo_shadow = (10, 6, 24)

        if line1:
            w1 = self._measure_stretched(line1, self.font_promo_main, stretch_x=1.18, spacing=self._s(2))
            self._draw_wide_text_with_shadow(
                img,
                (right_center_x - w1 // 2, by + self._sy(24)),
                line1.upper(),
                self.font_promo_main,
                fill=promo_fill,
                shadow_fill=promo_shadow,
                shadow_offset=(self._s(5), self._s(5)),
                stretch_x=1.18,
                letter_spacing=self._s(2),
            )
        if line2:
            w2 = self._measure_stretched(line2, self.font_promo_main, stretch_x=1.18, spacing=self._s(2))
            self._draw_wide_text_with_shadow(
                img,
                (right_center_x - w2 // 2, by + self._sy(80)),
                line2.upper(),
                self.font_promo_main,
                fill=promo_fill,
                shadow_fill=promo_shadow,
                shadow_offset=(self._s(5), self._s(5)),
                stretch_x=1.18,
                letter_spacing=self._s(2),
            )
        if line3:
            w3 = self._measure_stretched(line3, self.font_promo_sub, stretch_x=1.25, spacing=self._s(6))
            self._draw_wide_text_with_shadow(
                img,
                (right_center_x - w3 // 2, by + self._sy(138)),
                line3.upper(),
                self.font_promo_sub,
                fill=(218, 220, 235),
                shadow_fill=promo_shadow,
                shadow_offset=(self._s(4), self._s(4)),
                stretch_x=1.25,
                letter_spacing=self._s(6),
            )

        return img

    def _measure_stretched(
        self, text: str, font: ImageFont.FreeTypeFont, stretch_x: float = 1.15, spacing: int = 0
    ) -> int:
        dummy = Image.new("L", (16, 16))
        ddraw = ImageDraw.Draw(dummy)
        if spacing > 0:
            w = sum(
                (ddraw.textbbox((0, 0), ch, font=font)[2] - ddraw.textbbox((0, 0), ch, font=font)[0]) + spacing
                for ch in text
            )
        else:
            bb = ddraw.textbbox((0, 0), text, font=font)
            w = bb[2] - bb[0]
        return int(round(w * stretch_x))

    def _build_mask(self, scanlines: bool, vignette: bool) -> Image.Image:
        W, H = self.width, self.height
        mask_l = Image.new("L", (W, H), color=255)
        pixels = mask_l.load()
        cx, cy = W / 2.0, H / 2.0

        for y in range(H):
            scan_factor = 0.89 if (scanlines and (y % 2 == 1)) else 1.0
            dy = (y - cy) / cy
            for x in range(W):
                if vignette:
                    dx = (x - cx) / cx
                    r2 = (dx * dx * 0.45) + (dy * dy * 0.45)
                    vig = max(0.70, 1.0 - (r2 * r2 * 0.45))
                else:
                    vig = 1.0
                pixels[x, y] = max(0, min(255, int(255 * scan_factor * vig)))
        return Image.merge("RGB", (mask_l, mask_l, mask_l))

    def _build_noise_frames(self, count: int = 8) -> List[Image.Image]:
        W, H = self.width, self.height
        nw, nh = max(1, W // 2), max(1, H // 2)
        frames: List[Image.Image] = []
        rng = random.Random(2005)
        for _ in range(count):
            buf = bytearray(nw * nh)
            for i in range(nw * nh):
                r = rng.randint(0, 100)
                if r > 97:
                    buf[i] = rng.randint(8, 16)
                elif r > 84:
                    buf[i] = rng.randint(2, 6)
                else:
                    buf[i] = 0
            small_l = Image.frombytes("L", (nw, nh), bytes(buf)).resize((W, H), Image.NEAREST)
            rgb_noise = Image.merge("RGB", (small_l, small_l, small_l))
            sdraw = ImageDraw.Draw(rgb_noise)
            for by in range(max(0, H - self._sy(5)), H):
                seg_x = rng.randint(0, W // 3)
                seg_w = rng.randint(W // 4, W - seg_x)
                chroma_tint = rng.choice([
                    (55, 18, 65),
                    (20, 50, 70),
                    (45, 45, 55),
                ])
                sdraw.line([(seg_x, by), (seg_x + seg_w, by)], fill=chroma_tint, width=1)
            frames.append(rgb_noise)
        return frames

    def _ensure_bg_template(self, disp: Dict[str, Any]) -> None:
        key = (
            str(disp.get("banner_logo", config.BANNER_LOGO)),
            str(disp.get("banner_line_1", config.BANNER_LINE_1)),
            str(disp.get("banner_line_2", config.BANNER_LINE_2)),
            str(disp.get("banner_line_3", config.BANNER_LINE_3)),
            self.width,
            self.height,
        )
        if key != self._cached_banner_key:
            self._bg_template = self._build_bg_template(key[0], key[1], key[2], key[3])
            self._cached_banner_key = key

    def render_frame(self, now_mono: Optional[float] = None) -> Image.Image:
        """Render a single 24-bit RGB colour video frame."""
        with self._lock:
            v = settings_store.get_video()
            if v["width"] != self.width or v["height"] != self.height:
                self._init_dimensions(v["width"], v["height"])

            if now_mono is None:
                now_mono = time.monotonic()
            elapsed = max(0.0, now_mono - self._start_time)

            disp = settings_store.get_display()
            self._ensure_bg_template(disp)

            W, H = self.width, self.height
            frame = self._bg_template.copy()

            # --- 1. TOP BAR: Date on Left ("Tue Nov 29, 2005"), Time on Right ("0:08 am") ---
            now_dt = datetime.now()
            date_str = f"{now_dt.strftime('%a %b')} {now_dt.day}, {now_dt.year}"
            hour_12 = now_dt.hour % 12 or 12
            ampm = "am" if now_dt.hour < 12 else "pm"
            time_str = f"{hour_12}:{now_dt.strftime('%M')} {ampm}"

            top_y = self._sy(30)
            clock_fill = (232, 232, 236)
            clock_shadow = (16, 16, 18)

            self._draw_wide_text_with_shadow(
                frame,
                (self._sx(96), top_y),
                date_str,
                self.font_clock,
                fill=clock_fill,
                shadow_fill=clock_shadow,
                shadow_offset=(self._s(4), self._s(4)),
                stretch_x=1.10,
            )

            time_w = self._measure_stretched(time_str, self.font_clock, stretch_x=1.10)
            self._draw_wide_text_with_shadow(
                frame,
                (W - self._sx(96) - time_w, top_y),
                time_str,
                self.font_clock,
                fill=clock_fill,
                shadow_fill=clock_shadow,
                shadow_offset=(self._s(4), self._s(4)),
                stretch_x=1.10,
            )

            # --- 2. MIDDLE BAND: Indented All-Caps Slab-Serif Bulletin Copy ---
            playlist = feed_manager.get_playlist()
            total_pages = max(1, len(playlist))
            page_dur = max(4.0, float(disp.get("page_duration", config.PAGE_DURATION)))
            page_idx = int(elapsed // page_dur) % total_pages
            page_elapsed = elapsed % page_dur
            item: BulletinItem = playlist[page_idx]

            lines = _wrap_indented_story(item.broadcast_copy, width=29, indent_spaces=3, max_lines=6)

            tw_dur = float(disp.get("typewriter_duration", config.TYPEWRITER_DURATION))
            if tw_dur > 0.05:
                reveal = min(1.0, page_elapsed / tw_dur)
            else:
                reveal = 1.0

            total_chars = sum(len(ln) for ln in lines)
            chars_to_show = int(math.ceil(total_chars * reveal))

            story_x = self._sx(62)
            story_y = self.top_bar_h + self._sy(26)
            line_h = self._sy(58)

            story_fill = (214, 226, 246)
            story_shadow = (5, 20, 54)

            rem = chars_to_show
            for ln in lines:
                if rem <= 0:
                    break
                visible = ln[:rem]
                rem -= len(ln)
                self._draw_wide_text_with_shadow(
                    frame,
                    (story_x, story_y),
                    visible,
                    self.font_story,
                    fill=story_fill,
                    shadow_fill=story_shadow,
                    shadow_offset=(self._s(4), self._s(4)),
                    stretch_x=1.12,
                )
                story_y += line_h

            # --- 3. CRT Scanlines, Vignette & Analog Noise ---
            use_scan = bool(disp.get("scanlines", config.SCANLINES))
            use_vig = bool(disp.get("crt_vignette", config.CRT_VIGNETTE))
            use_noise = bool(disp.get("crt_noise", config.CRT_NOISE))

            if use_scan and use_vig:
                frame = ImageChops.multiply(frame, self._scanline_mask)
            elif use_scan:
                frame = ImageChops.multiply(frame, self._scanline_only_mask)
            elif use_vig:
                frame = ImageChops.multiply(frame, self._vignette_only_mask)

            if use_noise and self._noise_frames:
                noise = self._noise_frames[self._noise_idx % len(self._noise_frames)]
                self._noise_idx += 1
                frame = ImageChops.add(frame, noise)

            return frame

    def render_png_bytes(self) -> bytes:
        img = self.render_frame()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


renderer = BulletinRenderer()
