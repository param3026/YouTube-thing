"""Download YouTube videos or validate local files using yt-dlp."""

import hashlib
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


def is_youtube_url(url: str) -> bool:
    """Return True if the string looks like a YouTube URL."""
    parsed = urlparse(url)
    return parsed.netloc in ("www.youtube.com", "youtube.com", "youtu.be", "m.youtube.com")


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from a URL, used for cache naming."""
    parsed = urlparse(url)
    if parsed.netloc in ("youtu.be",):
        return parsed.path.lstrip("/").split("?")[0]
    qs = parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0]
    # Fallback: hash the URL
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _cache_key(source: str) -> str:
    """Derive a stable filename-safe key from a URL or file path."""
    if is_youtube_url(source):
        return extract_video_id(source)
    return hashlib.md5(Path(source).resolve().as_posix().encode()).hexdigest()[:12]


def download(source: str, cache_dir: Path) -> Path:
    """
    Given a YouTube URL or local file path, return a Path to the video file.

    For URLs, download with yt-dlp and cache the result.
    For local files, validate existence and return the path as-is.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if is_youtube_url(source):
        return _download_youtube(source, cache_dir)
    else:
        return _validate_local(source)


def _download_youtube(url: str, cache_dir: Path) -> Path:
    """Download a YouTube video via yt-dlp, returning the path to the file."""
    vid_id = extract_video_id(url)
    cache_file = cache_dir / f"downloaded_{vid_id}.mp4"

    if cache_file.exists() and cache_file.stat().st_size > 0:
        logger.info("Cache hit — skipping download: %s", cache_file)
        return cache_file

    logger.info("Downloading video: %s", url)

    # Use a temp output template so yt-dlp controls the extension,
    # then we rename to the stable cache path.
    tmp_template = str(cache_dir / f"dl_{vid_id}.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "-o", tmp_template,
        "--no-part",           # avoid .part files on crash
        "--no-mtime",
        url,
    ]

    logger.debug("yt-dlp command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("yt-dlp stderr:\n%s", result.stderr)
        raise RuntimeError(f"yt-dlp failed (exit {result.returncode}): {result.stderr[-500:]}")

    # Find what yt-dlp actually wrote
    downloaded = _find_downloaded_file(cache_dir, f"dl_{vid_id}")
    if downloaded is None:
        raise RuntimeError("yt-dlp reported success but no output file was found.")

    downloaded.rename(cache_file)
    logger.info("Download complete: %s (%.1f MB)", cache_file, cache_file.stat().st_size / 1e6)
    return cache_file


def _find_downloaded_file(directory: Path, stem_prefix: str) -> "Path | None":
    """Return the first file in directory whose stem starts with stem_prefix."""
    for p in directory.iterdir():
        if p.stem.startswith(stem_prefix) and p.suffix in (".mp4", ".mkv", ".webm", ".mov"):
            return p
    return None


def _validate_local(path: str) -> Path:
    """Validate and return a local video file path."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Local file not found: {p}")
    if not p.is_file():
        raise ValueError(f"Not a file: {p}")
    if p.stat().st_size == 0:
        raise ValueError(f"File is empty: {p}")
    logger.info("Using local file: %s", p)
    return p


def check_ytdlp() -> bool:
    """Return True if yt-dlp is available on PATH."""
    try:
        r = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False
