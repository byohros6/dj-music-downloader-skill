#!/usr/bin/env python3
"""Universal cross-platform (Windows & macOS) DJ music extractor, downloader, tagger & auditor."""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REQUIRED_PACKAGES = {
    "yt_dlp": "yt-dlp",
    "mutagen": "mutagen",
    "requests": "requests",
}

JUNK_TITLE_RE = re.compile(
    r"\s*[\(\[](?:official\s*(?:music\s*)?video|lyrics?\s*video|free\s*download|"
    r"official\s*audio|audio\s*only|visualizer|hd|4k)[\)\]]",
    re.IGNORECASE,
)
DOUBLE_EXT_RE = re.compile(r"\.(mp3|m4a)\.(mpeg|mp4)$", re.IGNORECASE)
SPOTIFY_URL_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z-]+/)?(playlist|album|track)/([A-Za-z0-9]+)"
)
APPLE_URL_RE = re.compile(
    r"music\.apple\.com/([a-z]{2})/(album|playlist|song)/[^/]+/([A-Za-z0-9.\-]+)"
)
MIX_KEYWORDS = (
    "extended",
    "club",
    "radio",
    "remix",
    "rework",
    "edit",
    "vip",
    "dub",
    "instrumental",
    "acoustic",
    "live",
    "bootleg",
)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_API_LOCK = threading.Lock()
_LAST_API_CALL = 0.0


def find_ffmpeg_exe() -> str | None:
    """Locate a usable ffmpeg binary on Windows, macOS, or Linux."""
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    candidates: list[Path] = [
        Path.home() / ".spotdl" / "ffmpeg.exe",
        Path.home() / ".spotdl" / "ffmpeg",
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
    ]
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            candidates.append(
                Path(local_app) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
            )
    for path in candidates:
        if path.is_file():
            return str(path)

    if importlib.util.find_spec("imageio_ffmpeg") is not None:
        try:
            import imageio_ffmpeg  # type: ignore

            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and Path(exe).is_file():
                return exe
        except Exception:
            pass
    return None


def cmd_doctor(install: bool) -> int:
    """Verify (and optionally install) Python packages and ffmpeg."""
    missing = [
        pip_name
        for mod_name, pip_name in REQUIRED_PACKAGES.items()
        if importlib.util.find_spec(mod_name) is None
    ]
    ffmpeg_exe = find_ffmpeg_exe()
    need_ffmpeg_pkg = ffmpeg_exe is None and (
        importlib.util.find_spec("imageio_ffmpeg") is None
    )

    if install and (missing or need_ffmpeg_pkg):
        to_install = list(missing)
        if need_ffmpeg_pkg:
            to_install.append("imageio-ffmpeg")
        print(f"Installing missing dependencies: {', '.join(to_install)}")
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", *to_install]
        )
        if res.returncode != 0:
            print("pip install failed. Please install dependencies manually.")
            return 1
        missing = [
            pip_name
            for mod_name, pip_name in REQUIRED_PACKAGES.items()
            if importlib.util.find_spec(mod_name) is None
        ]
        ffmpeg_exe = find_ffmpeg_exe()

    print(f"Python: {sys.executable}")
    print(f"Missing packages: {missing if missing else 'none'}")
    print(f"ffmpeg: {ffmpeg_exe or 'NOT FOUND'}")

    if missing or not ffmpeg_exe:
        extras = ["imageio-ffmpeg"] if not ffmpeg_exe else []
        pkg_cmd = " ".join([*missing, *extras])
        print(f"Run with --install, or manually: {sys.executable} -m pip install {pkg_cmd}")
        return 1
    print("Environment ready.")
    return 0


def pace_api(min_interval: float = 0.15) -> None:
    global _LAST_API_CALL
    with _API_LOCK:
        elapsed = time.monotonic() - _LAST_API_CALL
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _LAST_API_CALL = time.monotonic()


def norm_tokens(text: str) -> set[str]:
    """Normalize text to ASCII lowercase tokens for reliable metadata matching."""
    ascii_text = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return {t for t in re.findall(r"[a-z0-9]+", ascii_text) if len(t) > 1}


def fmt_dur(seconds: int | float | None) -> str:
    if not seconds:
        return "?:??"
    sec = round(float(seconds))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def sanitize_filename(name: str) -> str:
    """Normalize Unicode to NFC and strip Windows/macOS/FAT32 unsafe chars."""
    normalized = unicodedata.normalize("NFC", name)
    cleaned = re.sub(r'[\\/*?:"<>|]', "", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "track"


def clean_title(title: str) -> str:
    """Remove video/upload noise while preserving mix/remix descriptors."""
    cleaned = JUNK_TITLE_RE.sub("", title)
    return re.sub(r"\s+", " ", cleaned).strip()


def inspect_image_size(img_bytes: bytes) -> tuple[int, int] | None:
    """Read (width, height) from PNG or JPEG bytes without requiring Pillow."""
    if len(img_bytes) < 24:
        return None
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", img_bytes[16:24])
        return int(w), int(h)
    if img_bytes[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(img_bytes):
            if img_bytes[i] != 0xFF:
                i += 1
                continue
            marker = img_bytes[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                h, w = struct.unpack(">HH", img_bytes[i + 5 : i + 9])
                return int(w), int(h)
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
            else:
                seg_len = struct.unpack(">H", img_bytes[i + 2 : i + 4])[0]
                i += 2 + seg_len
    if importlib.util.find_spec("PIL") is not None:
        try:
            from PIL import Image  # type: ignore

            with Image.open(io.BytesIO(img_bytes)) as im:
                return im.size
        except Exception:
            pass
    return None


def prepare_cover_art(img_bytes: bytes | None, source_label: str) -> tuple[bytes | None, str]:
    """Validate image resolution/aspect ratio and center-crop non-square art if Pillow exists."""
    if not img_bytes or len(img_bytes) < 4096:
        return None, "missing"

    dims = inspect_image_size(img_bytes)
    if dims is None:
        return img_bytes, f"{source_label} (unknown dims)"

    w, h = dims
    if min(w, h) < 250:
        return None, f"rejected tiny {w}x{h}"

    ratio = w / max(h, 1)
    if not (0.9 <= ratio <= 1.1):
        if importlib.util.find_spec("PIL") is not None:
            try:
                from PIL import Image  # type: ignore

                with Image.open(io.BytesIO(img_bytes)) as im:
                    side = min(im.size)
                    left = (im.size[0] - side) // 2
                    top = (im.size[1] - side) // 2
                    cropped = im.crop((left, top, left + side, top + side)).convert("RGB")
                    buf = io.BytesIO()
                    cropped.save(buf, format="JPEG", quality=92)
                    return buf.getvalue(), f"{source_label} {side}x{side} cropped"
            except Exception:
                pass
        return img_bytes, f"{source_label} {w}x{h} WARN non-square"

    return img_bytes, f"{source_label} {w}x{h}"


def _score_meta_hit(
    req_artist: str,
    req_title: str,
    target_dur: int | None,
    hit_artist: str,
    hit_title: str,
    hit_dur: int | None,
) -> float:
    """Score metadata candidate so wrong songs/remixes are rejected."""
    ra, rt = norm_tokens(req_artist), norm_tokens(req_title)
    ha, ht = norm_tokens(hit_artist), norm_tokens(hit_title)
    if not rt or not ht:
        return -1.0

    title_overlap = len(rt & ht) / len(rt)
    artist_overlap = (len(ra & ha) / len(ra)) if ra else 0.5
    if title_overlap < 0.5 or artist_overlap < 0.34:
        return -1.0

    score = (title_overlap * 2.0) + (artist_overlap * 2.0)

    for kw in MIX_KEYWORDS:
        in_req = kw in rt
        in_hit = kw in ht
        if in_req and in_hit:
            score += 0.6
        elif in_req != in_hit:
            score -= 0.7

    if target_dur and hit_dur:
        diff = abs(hit_dur - target_dur)
        if diff <= 5:
            score += 1.5
        elif diff <= 15:
            score += 0.5
        elif diff > 45:
            return -1.0

    return score


def _artist_queries(artist: str) -> list[str]:
    """Return full artist string followed by primary artist fallback if multi-artist."""
    primary = re.split(r"[,&]|\b(?:feat\.?|ft\.?|x)\b", artist, flags=re.IGNORECASE)[0].strip()
    return [artist] if (not primary or primary == artist) else [artist, primary]


def fetch_deezer_meta(artist: str, title: str, target_dur: int | None = None) -> dict[str, Any]:
    import requests

    for query_artist in _artist_queries(artist):
        pace_api()
        try:
            resp = requests.get(
                "https://api.deezer.com/search",
                params={"q": f"{query_artist} {title}", "limit": 5},
                timeout=6,
            )
            if resp.status_code != 200:
                continue
            best: tuple[float, dict[str, Any]] = (-1.0, {})
            for hit in resp.json().get("data") or []:
                h_artist = (hit.get("artist") or {}).get("name", "")
                h_title = hit.get("title", "")
                h_dur = hit.get("duration")
                sc = _score_meta_hit(query_artist, title, target_dur, h_artist, h_title, h_dur)
                if sc > best[0]:
                    album = hit.get("album") or {}
                    best = (
                        sc,
                        {
                            "album": album.get("title"),
                            "art_url": album.get("cover_xl") or album.get("cover_big"),
                            "score": sc,
                        },
                    )
            if best[0] >= 1.8:
                return best[1]
        except Exception:
            continue
    return {}


def fetch_itunes_meta(artist: str, title: str, target_dur: int | None = None) -> dict[str, Any]:
    import requests

    for query_artist in _artist_queries(artist):
        pace_api()
        try:
            resp = requests.get(
                "https://itunes.apple.com/search",
                params={"term": f"{query_artist} {title}", "entity": "song", "limit": 5},
                headers={"User-Agent": USER_AGENT},
                timeout=6,
            )
            if resp.status_code != 200:
                continue
            best: tuple[float, dict[str, Any]] = (-1.0, {})
            for hit in resp.json().get("results") or []:
                h_artist = hit.get("artistName", "")
                h_title = hit.get("trackName", "")
                dur_ms = hit.get("trackTimeMillis") or 0
                h_dur = round(dur_ms / 1000) if dur_ms else None
                sc = _score_meta_hit(query_artist, title, target_dur, h_artist, h_title, h_dur)
                if sc > best[0]:
                    art = hit.get("artworkUrl100", "").replace("100x100bb", "1000x1000bb")
                    rel = hit.get("releaseDate", "")
                    best = (
                        sc,
                        {
                            "album": hit.get("collectionName"),
                            "genre": hit.get("primaryGenreName"),
                            "year": rel[:4] if len(rel) >= 4 else None,
                            "art_url": art or None,
                            "score": sc,
                        },
                    )
            if best[0] >= 1.8:
                return best[1]
        except Exception:
            continue
    return {}


def download_bytes(url: str) -> bytes | None:
    import requests

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception:
        pass
    return None


def transcode_to_mp3(ffmpeg_exe: str, src: Path, dst: Path) -> None:
    """Convert any audio container to DJ-safe 320 kbps 44.1 kHz stereo MP3."""
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(src),
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "320k",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(dst),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not dst.is_file():
        raise RuntimeError(f"ffmpeg failed ({res.returncode}): {res.stderr[-300:]}")


def embed_id3v23(
    mp3_path: Path,
    artist: str,
    title: str,
    album: str | None,
    genre: str | None,
    year: str | None,
    art_bytes: bytes | None,
) -> None:
    from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1
    from mutagen.mp3 import MP3

    audio = MP3(str(mp3_path), ID3=ID3)
    try:
        audio.add_tags()
    except Exception:
        pass
    if audio.tags is None:
        audio.tags = ID3()

    for frame in ("TIT2", "TPE1", "TALB", "TCON", "TDRC", "APIC"):
        audio.tags.delall(frame)

    audio.tags.add(TIT2(encoding=3, text=title))
    audio.tags.add(TPE1(encoding=3, text=artist))
    if album:
        audio.tags.add(TALB(encoding=3, text=album))
    if genre:
        audio.tags.add(TCON(encoding=3, text=genre))
    if year:
        audio.tags.add(TDRC(encoding=3, text=str(year)))
    if art_bytes:
        mime = "image/png" if art_bytes.startswith(b"\x89PNG") else "image/jpeg"
        audio.tags.add(
            APIC(encoding=3, mime=mime, type=3, desc="Cover", data=art_bytes)
        )
    audio.save(v2_version=3)


def _extract_spotify(url: str) -> tuple[str, list[dict[str, Any]]]:
    import requests

    match = SPOTIFY_URL_RE.search(url)
    if not match:
        raise ValueError("Invalid Spotify URL.")
    kind, entity_id = match.group(1), match.group(2)
    resp = requests.get(
        f"https://open.spotify.com/embed/{kind}/{entity_id}",
        headers={"User-Agent": USER_AGENT},
        timeout=12,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Spotify HTTP {resp.status_code} (playlist may be private).")
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        resp.text,
    )
    if not m:
        raise RuntimeError("Spotify embed data missing (playlist may be private).")
    data = json.loads(m.group(1))
    entity = (
        data.get("props", {})
        .get("pageProps", {})
        .get("state", {})
        .get("data", {})
        .get("entity", {})
    )
    name = entity.get("name") or entity.get("title") or entity_id
    raw_tracks = entity.get("trackList") or ([] if kind != "track" else [entity])
    tracks = []
    for item in raw_tracks:
        title = (item.get("title") or item.get("name") or "").replace("\u00a0", " ").strip()
        artist = (item.get("subtitle") or "").replace("\u00a0", " ").strip()
        if not artist and isinstance(item.get("artists"), list):
            artist = ", ".join(
                (a.get("name") or "").strip()
                for a in item["artists"]
                if isinstance(a, dict) and a.get("name")
            )
        dur_ms = item.get("duration") or 0
        if title and artist:
            entry: dict[str, Any] = {"artist": artist, "title": title}
            if dur_ms > 0:
                entry["duration_sec"] = round(dur_ms / 1000)
            tracks.append(entry)
    if kind == "playlist" and len(tracks) == 100:
        print("Warning: Spotify embed caps playlists at 100 tracks.")
    return name, tracks


def _extract_apple_music(url: str) -> tuple[str, list[dict[str, Any]]]:
    import requests

    match = APPLE_URL_RE.search(url)
    if match:
        country, kind, apple_id = match.group(1), match.group(2), match.group(3)
        if kind in ("album", "song") and apple_id.isdigit():
            resp = requests.get(
                "https://itunes.apple.com/lookup",
                params={"id": apple_id, "country": country, "entity": "song"},
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )
            if resp.status_code == 200:
                results = resp.json().get("results") or []
                col_name = next(
                    (r.get("collectionName") for r in results if r.get("collectionName")),
                    apple_id,
                )
                tracks = []
                for r in results:
                    if r.get("wrapperType") != "track":
                        continue
                    tracks.append(
                        {
                            "artist": r.get("artistName", ""),
                            "title": r.get("trackName", ""),
                            "album": r.get("collectionName"),
                            "genre": r.get("primaryGenreName"),
                            "year": (r.get("releaseDate") or "")[:4] or None,
                            "duration_sec": round((r.get("trackTimeMillis") or 0) / 1000)
                            or None,
                        }
                    )
                tracks = [
                    {k: v for k, v in t.items() if v is not None}
                    for t in tracks
                    if t["artist"] and t["title"]
                ]
                if tracks:
                    return col_name, tracks

    return _extract_jsonld_page(url)


def _extract_jsonld_page(url: str) -> tuple[str, list[dict[str, Any]]]:
    """Parse Schema.org JSON-LD MusicPlaylist / MusicAlbum / MusicRecording."""
    import requests

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=12)
    if resp.status_code != 200:
        raise RuntimeError(f"Page returned HTTP {resp.status_code}")
    scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        resp.text,
        re.DOTALL | re.IGNORECASE,
    )
    tracks: list[dict[str, Any]] = []
    name = "Extracted Playlist"
    for raw in scripts:
        try:
            obj = json.loads(raw.strip())
        except Exception:
            continue
        objs = obj if isinstance(obj, list) else [obj]
        for node in objs:
            if not isinstance(node, dict):
                continue
            name = node.get("name") or name
            items = node.get("track") or node.get("tracks") or []
            if isinstance(items, dict):
                items = items.get("itemListElement") or [items]
            for it in items:
                rec = it.get("item", it) if isinstance(it, dict) else {}
                if not isinstance(rec, dict):
                    continue
                t_name = (rec.get("name") or "").strip()
                by = rec.get("byArtist") or node.get("byArtist") or {}
                if isinstance(by, list):
                    artist = ", ".join(a.get("name", "") for a in by if isinstance(a, dict))
                elif isinstance(by, dict):
                    artist = by.get("name", "")
                else:
                    artist = str(by)
                if t_name and artist:
                    tracks.append({"artist": artist.strip(), "title": t_name})
    if not tracks:
        raise RuntimeError("No tracklist found on page.")
    return name, tracks


def _split_artist_title(raw_title: str, uploader: str | None) -> tuple[str, str]:
    cleaned = clean_title(raw_title)
    for sep in (" - ", " – ", " — "):
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip()
    return (uploader or "Unknown Artist").strip(), cleaned


def _extract_ytdlp(url: str) -> tuple[str, list[dict[str, Any]]]:
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("No metadata returned by yt-dlp.")

    name = info.get("title") or info.get("playlist_title") or "Extracted Playlist"
    entries = info.get("entries") or [info]
    tracks: list[dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        entry_url = e.get("webpage_url") or e.get("url")
        raw_title = e.get("track") or e.get("title") or ""
        artist = e.get("artist") or e.get("uploader") or e.get("channel")
        if e.get("artist") and e.get("track"):
            t_artist, t_title = str(e["artist"]).strip(), clean_title(str(e["track"]))
        else:
            t_artist, t_title = _split_artist_title(raw_title, artist)
        if not t_title:
            continue
        item: dict[str, Any] = {"artist": t_artist, "title": t_title}
        if e.get("duration"):
            item["duration_sec"] = round(float(e["duration"]))
        if entry_url and str(entry_url).startswith("http"):
            item["url"] = entry_url
        tracks.append(item)
    return name, tracks


def cmd_extract(url: str, output_json: Path) -> int:
    """Extract tracklist JSON from Spotify, Apple Music, SoundCloud, YouTube, Bandcamp, etc."""
    if SPOTIFY_URL_RE.search(url):
        name, tracks = _extract_spotify(url)
    elif APPLE_URL_RE.search(url) or "music.apple.com" in url:
        name, tracks = _extract_apple_music(url)
    else:
        try:
            name, tracks = _extract_ytdlp(url)
        except Exception:
            name, tracks = _extract_jsonld_page(url)

    if not tracks:
        print("No tracks extracted.")
        return 1
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(tracks, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Extracted {len(tracks)} tracks from '{name}' -> {output_json}")
    return 0


def pick_youtube_candidate(
    artist: str,
    title: str,
    target_dur: int | None,
    tolerance: int,
    allow_mismatch: bool,
) -> tuple[str, str | None, str | None]:
    """Select the best YouTube match, refusing obvious sets/snippets/duration mismatches."""
    import yt_dlp

    queries = (
        [f"ytsearch8:{artist} - {title} audio", f"ytsearch5:{artist} {title}"]
        if target_dur
        else [f"ytsearch3:{artist} - {title} audio"]
    )
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    entries: list[dict[str, Any]] = []

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for q in queries:
            info = ydl.extract_info(q, download=False)
            entries = [e for e in (info.get("entries") or []) if isinstance(e, dict)]
            if target_dur:
                valid = [
                    (abs((e.get("duration") or 0) - target_dur), e)
                    for e in entries
                    if e.get("duration") and abs(e["duration"] - target_dur) <= tolerance
                ]
                if valid:
                    valid.sort(key=lambda pair: pair[0])
                    chosen = valid[0][1]
                    url = chosen.get("url") or f"https://www.youtube.com/watch?v={chosen['id']}"
                    return url, chosen.get("thumbnail"), None
            elif entries:
                sane = [
                    e
                    for e in entries
                    if not e.get("duration") or (45 <= e["duration"] <= 900)
                ]
                chosen = sane[0] if sane else entries[0]
                url = chosen.get("url") or f"https://www.youtube.com/watch?v={chosen['id']}"
                warn = (
                    f"WARN long/short ({fmt_dur(chosen.get('duration'))})"
                    if chosen not in sane
                    else None
                )
                return url, chosen.get("thumbnail"), warn

    if target_dur:
        summary = ", ".join(
            f"{fmt_dur(e.get('duration'))} ({(e.get('title') or '')[:35]})"
            for e in entries[:4]
        )
        if not allow_mismatch or not entries:
            raise RuntimeError(
                f"DURATION MISMATCH: expected {fmt_dur(target_dur)}±{tolerance}s; "
                f"found [{summary or 'none'}]"
            )
        chosen = min(
            entries,
            key=lambda e: abs((e.get("duration") or 99999) - target_dur),
        )
        url = chosen.get("url") or f"https://www.youtube.com/watch?v={chosen['id']}"
        return (
            url,
            chosen.get("thumbnail"),
            f"WARN duration {fmt_dur(chosen.get('duration'))} != {fmt_dur(target_dur)}",
        )

    raise RuntimeError(f"No YouTube results for {artist} - {title}")


def process_track(
    idx: int,
    total: int,
    track: dict[str, Any],
    out_dir: Path,
    ffmpeg_exe: str,
    use_index: bool,
    tolerance: int,
    allow_mismatch: bool,
) -> str:
    import yt_dlp
    from mutagen.mp3 import MP3

    artist = track["artist"].strip()
    title = clean_title(track["title"].strip())
    target_dur = track.get("duration_sec")
    prefix = f"{idx:03d}. " if use_index else ""
    filename = sanitize_filename(f"{prefix}{artist} - {title}") + ".mp3"
    final_path = out_dir / filename

    if final_path.exists() and final_path.stat().st_size > 100_000:
        return f"[{idx}/{total}] {filename} (skipped - exists)"

    deezer = fetch_deezer_meta(artist, title, target_dur)
    itunes = fetch_itunes_meta(artist, title, target_dur) if not deezer else {}

    album = track.get("album") or deezer.get("album") or itunes.get("album")
    genre = track.get("genre") or itunes.get("genre") or "Electronic"
    year = track.get("year") or itunes.get("year")

    art_source = "none"
    art_url = None
    if deezer.get("art_url"):
        art_url, art_source = deezer["art_url"], "Deezer"
    elif itunes.get("art_url"):
        art_url, art_source = itunes["art_url"], "iTunes"

    target_url = track.get("url")
    yt_thumb: str | None = None
    notes: list[str] = []
    if not target_url:
        target_url, yt_thumb, dur_warn = pick_youtube_candidate(
            artist, title, target_dur, tolerance, allow_mismatch
        )
        if dur_warn:
            notes.append(dur_warn)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(tmp_path / "raw.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            if not yt_thumb and isinstance(info, dict):
                yt_thumb = info.get("thumbnail")

        raw_files = [p for p in tmp_path.iterdir() if p.is_file() and p.name.startswith("raw.")]
        if not raw_files:
            raise RuntimeError(f"Audio download failed for {filename}")

        temp_mp3 = tmp_path / "encoded.mp3"
        transcode_to_mp3(ffmpeg_exe, raw_files[0], temp_mp3)

        actual_dur = round(MP3(str(temp_mp3)).info.length)
        if target_dur and abs(actual_dur - target_dur) > tolerance and not notes:
            notes.append(f"WARN encoded {fmt_dur(actual_dur)} != {fmt_dur(target_dur)}")

        raw_art = download_bytes(art_url) if art_url else None
        art_bytes, art_note = prepare_cover_art(raw_art, art_source)
        if not art_bytes and yt_thumb:
            yt_raw = download_bytes(yt_thumb)
            art_bytes, art_note = prepare_cover_art(yt_raw, "YT-thumb")
            if art_bytes:
                notes.append("WARN fallback YT cover")

        embed_id3v23(temp_mp3, artist, title, album, genre, year, art_bytes)
        shutil.move(str(temp_mp3), str(final_path))

    detail = f"{fmt_dur(actual_dur)} | art: {art_note}"
    if notes:
        detail += " | " + "; ".join(notes)
    return f"[{idx}/{total}] {filename} ({detail})"


def cmd_audit(
    root: Path,
    fix_ext: bool = False,
    convert_wav: bool = False,
    delete_wav: bool = False,
) -> int:
    """Validate and optionally repair a DJ music folder."""
    from mutagen.mp3 import MP3

    if not root.is_dir():
        print(f"Directory not found: {root}")
        return 1

    ffmpeg_exe = find_ffmpeg_exe() if convert_wav else None
    fixed_ext_count = 0
    converted_wav_count = 0

    if fix_ext or convert_wav:
        for path in list(root.rglob("*")):
            if not path.is_file():
                continue
            m = DOUBLE_EXT_RE.search(path.name)
            if fix_ext and m:
                new_name = DOUBLE_EXT_RE.sub(f".{m.group(1).lower()}", path.name)
                target = path.with_name(new_name)
                if not target.exists():
                    path.rename(target)
                    print(f"[FIXED EXT] {path.name} -> {new_name}")
                    fixed_ext_count += 1
            elif convert_wav and path.suffix.lower() == ".wav" and "_original_wav" not in path.parts:
                if not ffmpeg_exe:
                    print(f"[SKIP WAV] No ffmpeg available to convert {path.name}")
                    continue
                mp3_target = path.with_suffix(".mp3")
                if not mp3_target.exists():
                    transcode_to_mp3(ffmpeg_exe, path, mp3_target)
                    parts = path.stem.split(" - ", 1)
                    artist = parts[0].strip() if len(parts) == 2 else "Unknown Artist"
                    title = parts[1].strip() if len(parts) == 2 else path.stem
                    dz = fetch_deezer_meta(artist, title) if artist != "Unknown Artist" else {}
                    it = fetch_itunes_meta(artist, title) if (artist != "Unknown Artist" and not dz) else {}
                    src_label = "Deezer" if dz.get("art_url") else ("iTunes" if it.get("art_url") else "none")
                    art_url = dz.get("art_url") or it.get("art_url")
                    raw_art = download_bytes(art_url) if art_url else None
                    art_bytes, _ = prepare_cover_art(raw_art, src_label)
                    embed_id3v23(
                        mp3_target,
                        artist,
                        title,
                        dz.get("album") or it.get("album"),
                        it.get("genre"),
                        it.get("year"),
                        art_bytes,
                    )
                if delete_wav:
                    path.unlink()
                    print(f"[WAV -> MP3] {path.name} converted (original deleted)")
                else:
                    backup_dir = path.parent / "_original_wav"
                    backup_dir.mkdir(exist_ok=True)
                    shutil.move(str(path), str(backup_dir / path.name))
                    print(f"[WAV -> MP3] {path.name} converted (original moved to _original_wav/)")
                converted_wav_count += 1

    issues: list[str] = []
    mp3_count = 0
    wav_count = 0
    double_ext_count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "_original_wav" in path.parts:
            continue
        if DOUBLE_EXT_RE.search(path.name):
            double_ext_count += 1
            issues.append(f"Double extension: {path.name}")
            continue
        ext = path.suffix.lower()
        if ext == ".wav":
            wav_count += 1
            issues.append(f"WAV (no artwork support): {path.name}")
            continue
        if ext != ".mp3":
            continue
        mp3_count += 1
        try:
            audio = MP3(str(path))
            tags = audio.tags
            missing = []
            if not tags or not tags.get("TIT2"):
                missing.append("TIT2")
            if not tags or not tags.get("TPE1"):
                missing.append("TPE1")
            apics = tags.getall("APIC") if tags else []
            if not apics:
                missing.append("APIC")
            else:
                dims = inspect_image_size(apics[0].data)
                if dims:
                    w, h = dims
                    if min(w, h) < 250:
                        missing.append(f"tiny_art={w}x{h}")
                    elif not (0.9 <= (w / max(h, 1)) <= 1.1):
                        missing.append(f"non_square_art={w}x{h}")
            if audio.info.sample_rate not in (44100, 48000):
                missing.append(f"sample_rate={audio.info.sample_rate}")
            if missing:
                issues.append(f"{path.name}: {', '.join(missing)}")
        except Exception as exc:
            issues.append(f"{path.name}: unreadable ({exc})")

    print(
        f"Audited {root}: {mp3_count} MP3s, {wav_count} WAVs, {double_ext_count} double-ext "
        f"(fixed ext: {fixed_ext_count}, converted WAV: {converted_wav_count})"
    )
    for item in issues:
        print(f"  [ISSUE] {item}")
    if not issues:
        print("All tracks passed DJ readiness checks.")
        return 0
    return 1


def cmd_download(args: argparse.Namespace) -> int:
    if any(importlib.util.find_spec(m) is None for m in REQUIRED_PACKAGES):
        print("Missing Python dependencies. Run: doctor --install")
        return 1
    ffmpeg_exe = find_ffmpeg_exe()
    if not ffmpeg_exe:
        print("ffmpeg not found. Run: doctor --install")
        return 1

    out_dir = Path(args.output).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    tracks = json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
    total = len(tracks)

    free_gb = shutil.disk_usage(out_dir).free / (1024**3)
    est_gb = (total * 10) / 1024
    print(f"Disk check: ~{est_gb:.2f} GB estimated for {total} tracks ({free_gb:.1f} GB free on destination)")
    if free_gb < est_gb + 0.5:
        print("WARNING: Destination drive may run low on disk space!")

    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                process_track,
                i,
                total,
                t,
                out_dir,
                ffmpeg_exe,
                args.index,
                args.tolerance,
                args.allow_duration_mismatch,
            ): t
            for i, t in enumerate(tracks, 1)
        }
        for fut in concurrent.futures.as_completed(futures):
            t = futures[fut]
            try:
                print(fut.result(), flush=True)
            except Exception as exc:
                failures += 1
                print(
                    f"[FAILED] {t.get('artist')} - {t.get('title')}: {exc}",
                    flush=True,
                )

    print("-" * 60)
    print(f"Downloaded {total - failures}/{total} tracks ({failures} failed) -> {out_dir}")
    if not args.skip_audit:
        audit_rc = cmd_audit(out_dir, fix_ext=False, convert_wav=False, delete_wav=False)
        return 1 if (failures or audit_rc) else 0
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Universal DJ Music Downloader & Auditor")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("doctor", help="Check or install dependencies & ffmpeg.")
    p_doc.add_argument("--install", action="store_true", help="Auto-install missing packages.")

    p_ex = sub.add_parser(
        "extract",
        help="Extract tracklist JSON from Spotify, Apple Music, SoundCloud, YouTube, Bandcamp, etc.",
    )
    p_ex.add_argument("url", help="Playlist, album, set, or track URL.")
    p_ex.add_argument("-o", "--output", required=True, help="Output JSON path.")

    p_dl = sub.add_parser("download", help="Download, transcode, and tag tracks.")
    p_dl.add_argument("-i", "--input", required=True, help="Input tracks JSON path.")
    p_dl.add_argument(
        "-o",
        "--output",
        default=str(Path.home() / "Music" / "DJ Music" / "Downloads"),
        help="Output folder path.",
    )
    p_dl.add_argument("--workers", type=int, default=4, help="Parallel workers.")
    p_dl.add_argument("--index", action="store_true", help="Prefix filenames with 001., 002.")
    p_dl.add_argument("--tolerance", type=int, default=8, help="Duration tolerance (sec).")
    p_dl.add_argument(
        "--allow-duration-mismatch",
        action="store_true",
        help="Download closest match with warning instead of failing on duration mismatch.",
    )
    p_dl.add_argument("--skip-audit", action="store_true", help="Skip post-download audit.")

    p_au = sub.add_parser("audit", help="Audit and repair a DJ folder.")
    p_au.add_argument("directory", help="Folder to audit.")
    p_au.add_argument("--fix-ext", action="store_true", help="Strip .mp3.mpeg / .m4a.mp4 suffixes.")
    p_au.add_argument(
        "--convert-wav",
        action="store_true",
        help="Convert .wav files to tagged 320 kbps MP3 (keeps backups in _original_wav/).",
    )
    p_au.add_argument("--fix", action="store_true", help="Run both --fix-ext and --convert-wav.")
    p_au.add_argument(
        "--delete-wav",
        action="store_true",
        help="With --convert-wav/--fix, delete original .wav instead of backing up.",
    )

    args = parser.parse_args()
    if args.command == "doctor":
        return cmd_doctor(args.install)
    if args.command == "extract":
        return cmd_extract(args.url, Path(args.output).expanduser())
    if args.command == "download":
        return cmd_download(args)
    if args.command == "audit":
        return cmd_audit(
            Path(args.directory).expanduser(),
            fix_ext=args.fix_ext or args.fix,
            convert_wav=args.convert_wav or args.fix,
            delete_wav=args.delete_wav,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
