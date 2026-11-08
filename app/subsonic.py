import hashlib
import json
import logging
import os
import random
import secrets
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from app.settings_store import settings_store

logger = logging.getLogger("cable-bulletin.subsonic")

CLIENT_NAME = "CableBulletinHLS"
API_VERSION = "1.15.0"


class SubsonicClient:
    """
    Client for Subsonic-compatible servers (Gonic, Navidrome, Airsonic, Subsonic)
    plus a continuous PCM audio feeder that decodes tracks one after another
    into an unbroken 44.1kHz stereo s16le stream for FFmpeg.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: List[Dict[str, Any]] = []
        self._now_playing: Optional[Dict[str, Any]] = None
        self._current_decoder: Optional[subprocess.Popen] = None
        self._last_error: Optional[str] = None

    def _build_auth_params(self, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        if cfg is None:
            cfg = settings_store.get_subsonic(include_password=True)
        username = cfg.get("username", "").strip()
        password = cfg.get("password", "")
        params: Dict[str, str] = {
            "u": username,
            "v": API_VERSION,
            "c": CLIENT_NAME,
            "f": "json",
        }
        if cfg.get("legacy_auth"):
            params["p"] = password
        else:
            salt = secrets.token_hex(6)
            token = hashlib.md5((password + salt).encode("utf-8")).hexdigest()
            params["t"] = token
            params["s"] = salt
        return params

    def _build_url(
        self,
        endpoint: str,
        extra_params: Optional[Dict[str, Any]] = None,
        cfg: Optional[Dict[str, Any]] = None,
    ) -> str:
        if cfg is None:
            cfg = settings_store.get_subsonic(include_password=True)
        base = cfg.get("server_url", "").strip().rstrip("/")
        if not base:
            raise ValueError("Subsonic server URL is not configured.")
        params = self._build_auth_params(cfg)
        if extra_params:
            for k, v in extra_params.items():
                if v is not None and v != "":
                    params[k] = str(v)
        query = urllib.parse.urlencode(params)
        return f"{base}/rest/{endpoint}?{query}"

    def _request_json(
        self,
        endpoint: str,
        extra_params: Optional[Dict[str, Any]] = None,
        cfg: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint, extra_params=extra_params, cfg=cfg)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"{CLIENT_NAME}/2.1"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        sub_resp = data.get("subsonic-response", {})
        if sub_resp.get("status") != "ok":
            err = sub_resp.get("error", {})
            msg = err.get("message", "Unknown Subsonic error")
            raise RuntimeError(f"Subsonic error: {msg}")
        return sub_resp

    def test_connection(self, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Tests connection to Gonic/Subsonic via ping.view and fetches playlists."""
        sub_resp = self._request_json("ping.view", cfg=cfg)
        playlists = self.get_playlists(cfg=cfg)
        return {
            "ok": True,
            "server_version": sub_resp.get("version", API_VERSION),
            "server_type": sub_resp.get("type", "subsonic"),
            "playlists": playlists,
        }

    def get_playlists(self, cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        sub_resp = self._request_json("getPlaylists.view", cfg=cfg)
        container = sub_resp.get("playlists", {})
        raw_list = container.get("playlist", [])
        if isinstance(raw_list, dict):
            raw_list = [raw_list]
        result: List[Dict[str, Any]] = []
        for pl in raw_list:
            result.append({
                "id": str(pl.get("id", "")),
                "name": str(pl.get("name", "Untitled Playlist")),
                "song_count": int(pl.get("songCount", 0)),
                "duration": int(pl.get("duration", 0)),
            })
        return result

    def fetch_tracks_batch(self) -> List[Dict[str, Any]]:
        cfg = settings_store.get_subsonic(include_password=True)
        mode = cfg.get("mode", "random")
        playlist_id = cfg.get("playlist_id", "").strip()
        genre = cfg.get("genre_filter", "").strip()

        raw_songs: List[Dict[str, Any]] = []
        if mode == "playlist" and playlist_id:
            sub_resp = self._request_json("getPlaylist.view", {"id": playlist_id}, cfg=cfg)
            pl_obj = sub_resp.get("playlist", {})
            entries = pl_obj.get("entry", [])
            if isinstance(entries, dict):
                entries = [entries]
            raw_songs = list(entries)
            if cfg.get("shuffle_playlist", True):
                random.shuffle(raw_songs)
        else:
            extra = {"size": 40}
            if genre:
                extra["genre"] = genre
            sub_resp = self._request_json("getRandomSongs.view", extra, cfg=cfg)
            rnd_obj = sub_resp.get("randomSongs", {})
            songs = rnd_obj.get("song", [])
            if isinstance(songs, dict):
                songs = [songs]
            raw_songs = list(songs)

        tracks: List[Dict[str, Any]] = []
        for s in raw_songs:
            track_id = str(s.get("id", "")).strip()
            if not track_id:
                continue
            tracks.append({
                "id": track_id,
                "title": str(s.get("title", "Unknown Track")),
                "artist": str(s.get("artist", "Unknown Artist")),
                "album": str(s.get("album", "")),
                "duration": int(s.get("duration", 0)),
            })
        return tracks

    def get_stream_url(self, track_id: str) -> str:
        cfg = settings_store.get_subsonic(include_password=True)
        extra: Dict[str, Any] = {"id": track_id}
        fmt = cfg.get("transcode_format", "raw")
        if fmt and fmt != "raw":
            extra["format"] = fmt
        return self._build_url("stream.view", extra_params=extra, cfg=cfg)

    def clear_queue_and_skip(self) -> None:
        with self._lock:
            self._queue.clear()
        self.skip_current_track()

    def skip_current_track(self) -> None:
        with self._lock:
            proc = self._current_decoder
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

    def get_now_playing(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._now_playing) if self._now_playing else None

    def get_last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    def feed_pcm_pipe(self, write_fd: int, stop_event: threading.Event) -> None:
        """
        Continuously decodes tracks from the Subsonic queue into 44.1kHz stereo
        16-bit PCM ('s16le') and writes them to `write_fd`.
        """
        # 0.25s of stereo 16-bit 44.1kHz silence for fallback pacing
        silence_chunk = b"\x00" * (44100 * 4 // 4)

        try:
            with os.fdopen(write_fd, "wb", buffering=0) as out_pipe:
                while not stop_event.is_set():
                    track: Optional[Dict[str, Any]] = None
                    with self._lock:
                        if self._queue:
                            track = self._queue.pop(0)

                    if track is None:
                        try:
                            batch = self.fetch_tracks_batch()
                            with self._lock:
                                self._queue.extend(batch)
                                self._last_error = None if batch else "No songs returned from Subsonic server."
                                if self._queue:
                                    track = self._queue.pop(0)
                        except Exception as exc:
                            with self._lock:
                                self._last_error = str(exc)
                            logger.warning("Subsonic queue fetch error: %s", exc)

                    if track is None:
                        # Write silence for 1s while waiting to retry so main FFmpeg never blocks
                        for _ in range(4):
                            if stop_event.is_set():
                                break
                            out_pipe.write(silence_chunk)
                            time.sleep(0.25)
                        continue

                    try:
                        stream_url = self.get_stream_url(track["id"])
                    except Exception as exc:
                        with self._lock:
                            self._last_error = str(exc)
                        time.sleep(0.5)
                        continue

                    with self._lock:
                        self._now_playing = track
                    logger.info(
                        "Playing Subsonic track: %s - %s (%s)",
                        track.get("artist"),
                        track.get("title"),
                        track.get("album"),
                    )

                    cmd = [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-reconnect",
                        "1",
                        "-reconnect_streamed",
                        "1",
                        "-reconnect_delay_max",
                        "5",
                        "-i",
                        stream_url,
                        "-vn",
                        "-f",
                        "s16le",
                        "-acodec",
                        "pcm_s16le",
                        "-ar",
                        "44100",
                        "-ac",
                        "2",
                        "pipe:1",
                    ]

                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        bufsize=65536,
                    )
                    with self._lock:
                        self._current_decoder = proc

                    bytes_written = 0
                    try:
                        if proc.stdout:
                            while not stop_event.is_set():
                                chunk = proc.stdout.read(16384)
                                if not chunk:
                                    break
                                out_pipe.write(chunk)
                                bytes_written += len(chunk)
                    except (BrokenPipeError, OSError):
                        # Main FFmpeg encoder closed the pipe
                        break
                    finally:
                        with self._lock:
                            if self._current_decoder is proc:
                                self._current_decoder = None
                        try:
                            proc.terminate()
                            proc.wait(timeout=2)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass

                    # If the track failed immediately (0 bytes), output brief silence before next track
                    if bytes_written == 0 and not stop_event.is_set():
                        out_pipe.write(silence_chunk)
                        time.sleep(0.25)
        except (BrokenPipeError, OSError):
            pass
        except Exception as exc:
            logger.debug("Subsonic PCM feeder exited: %s", exc)
        finally:
            with self._lock:
                self._now_playing = None
                self._current_decoder = None


subsonic_client = SubsonicClient()
