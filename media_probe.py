"""Probe video/audio metadata using ffprobe (or ffmpeg -i as fallback)."""

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ffprobe_cmd() -> str:
    try:
        import setup_env
        return setup_env.get_ffprobe()
    except Exception:
        return "ffprobe"


def _ffmpeg_cmd() -> str:
    try:
        import setup_env
        return setup_env.get_ffmpeg()
    except Exception:
        return "ffmpeg"


def probe(file_path: Path) -> dict[str, Any]:
    """
    Run ffprobe (or ffmpeg -i) on *file_path* and return a structured metadata dict.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    raw = _try_ffprobe_json(file_path)
    if raw is not None:
        return _parse_ffprobe_json(raw, file_path)

    # Fallback: parse ffmpeg -i stderr
    logger.info("ffprobe JSON failed — using ffmpeg -i stderr parsing")
    return _parse_ffmpeg_stderr(file_path)


# ---------------------------------------------------------------------------
# ffprobe JSON path
# ---------------------------------------------------------------------------

def _try_ffprobe_json(file_path: Path) -> "dict | None":
    cmd = [
        _ffprobe_cmd(),
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def _parse_ffprobe_json(raw: dict, file_path: Path) -> dict[str, Any]:
    video_stream = _find_stream(raw, "video")
    audio_stream = _find_stream(raw, "audio")

    duration = float(raw.get("format", {}).get("duration", 0))
    if duration == 0 and video_stream:
        duration = float(video_stream.get("duration", 0))

    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0
    rotation = _extract_rotation(video_stream) if video_stream else 0
    fps = _parse_rate(video_stream.get("r_frame_rate", "0/1")) if video_stream else 0.0
    has_audio = audio_stream is not None
    audio_channels = int(audio_stream.get("channels", 0)) if audio_stream else 0
    video_codec = video_stream.get("codec_name", "unknown") if video_stream else "none"
    audio_codec = audio_stream.get("codec_name", "unknown") if audio_stream else "none"
    size_bytes = int(raw.get("format", {}).get("size", 0))

    meta = {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "rotation": rotation,
        "has_audio": has_audio,
        "audio_channels": audio_channels,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "format": raw.get("format", {}).get("format_name", "unknown"),
        "size_bytes": size_bytes,
        "raw": raw,
    }
    logger.info(
        "Probed %s: %.1fs, %dx%d, %.1f fps, audio=%s",
        file_path.name, duration, width, height, fps, has_audio,
    )
    return meta


# ---------------------------------------------------------------------------
# ffmpeg -i stderr fallback
# ---------------------------------------------------------------------------

def _parse_ffmpeg_stderr(file_path: Path) -> dict[str, Any]:
    """Parse metadata from `ffmpeg -i file` stderr output."""
    cmd = [_ffmpeg_cmd(), "-i", str(file_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    # ffmpeg exits with code 1 when no output is specified — that's expected
    text = result.stderr

    duration = _parse_duration(text)
    width, height = _parse_resolution(text)
    fps = _parse_fps(text)
    has_audio = bool(re.search(r"Stream.*Audio:", text))
    audio_channels = _parse_audio_channels(text)
    video_codec = _parse_codec(text, "Video")
    audio_codec = _parse_codec(text, "Audio")

    meta = {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "rotation": 0,
        "has_audio": has_audio,
        "audio_channels": audio_channels,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "format": "mp4",
        "size_bytes": file_path.stat().st_size,
        "raw": {"stderr": text},
    }
    logger.info(
        "Probed (ffmpeg) %s: %.1fs, %dx%d, %.1f fps, audio=%s",
        file_path.name, duration, width, height, fps, has_audio,
    )
    return meta


def _parse_duration(text: str) -> float:
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", text)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mn * 60 + s
    return 0.0


def _parse_resolution(text: str) -> tuple[int, int]:
    m = re.search(r"(\d{2,5})x(\d{2,5})", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def _parse_fps(text: str) -> float:
    m = re.search(r"([\d.]+)\s+fps", text)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d.]+)\s+tbr", text)
    if m:
        return float(m.group(1))
    return 0.0


def _parse_audio_channels(text: str) -> int:
    if "stereo" in text:
        return 2
    if "mono" in text:
        return 1
    m = re.search(r"(\d+)\s+channels?", text)
    return int(m.group(1)) if m else 0


def _parse_codec(text: str, stream_type: str) -> str:
    m = re.search(rf"Stream.*{stream_type}:\s+(\w+)", text)
    return m.group(1) if m else "unknown"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def verify_short(file_path: Path) -> dict[str, Any]:
    meta = probe(file_path)
    issues = []
    if meta["width"] != 1080 or meta["height"] != 1920:
        issues.append(f"Expected 1080x1920, got {meta['width']}x{meta['height']}")
    if not meta["has_audio"]:
        issues.append("No audio stream found")
    if meta["duration"] < 5:
        issues.append(f"Duration too short: {meta['duration']:.1f}s")
    return {"ok": len(issues) == 0, "issues": issues, "meta": meta}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_stream(raw: dict, codec_type: str) -> "dict | None":
    for stream in raw.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream
    return None


def _extract_rotation(stream: dict) -> int:
    tags = stream.get("tags", {})
    if "rotate" in tags:
        return int(tags["rotate"])
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            return abs(int(side["rotation"]))
    return 0


def _parse_rate(rate_str: str) -> float:
    try:
        if "/" in rate_str:
            num, den = rate_str.split("/")
            den = int(den)
            return int(num) / den if den else 0.0
        return float(rate_str)
    except (ValueError, ZeroDivisionError):
        return 0.0


def check_ffmpeg() -> bool:
    try:
        import setup_env
        path = setup_env.get_ffmpeg()
        r = subprocess.run([path, "-version"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        pass
    try:
        r = subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=10)
        return r.returncode == 0
    except FileNotFoundError:
        return False
