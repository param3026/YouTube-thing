"""
Render Short clips using FFmpeg.

For each clip:
  1. Trim to [start, end]
  2. Crop/scale to 1080×1920 (9:16) – center-crop horizontal sources;
     pad vertical sources if already narrower than needed.
  3. Burn in SRT captions (skipped if SRT is empty).
  4. Encode: libx264 (fast/crf 23) + aac (128 k, stereo).
"""

import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import setup_env  # ensures ffmpeg is on PATH before first subprocess

logger = logging.getLogger(__name__)

TARGET_W = 1080
TARGET_H = 1920


def render_clip(
    source: Path,
    srt_path: Path,
    output_path: Path,
    start: float,
    end: float,
    source_width: int,
    source_height: int,
    crf: int = 23,
    preset: str = "fast",
) -> Path:
    """
    Render one Short clip from *source* trimmed to [start, end].

    Returns *output_path* on success, raises RuntimeError on failure.
    """
    source = Path(source)
    srt_path = Path(srt_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    crop_filter = _build_crop_filter(source_width, source_height)
    has_subs = _srt_has_content(srt_path)

    if has_subs:
        # Copy SRT to a temp dir with a simple ASCII filename to avoid
        # path-escaping issues in the FFmpeg subtitles filter on Windows.
        with tempfile.TemporaryDirectory() as tmpdir:
            safe_srt = Path(tmpdir) / "subs.srt"
            shutil.copy2(srt_path, safe_srt)
            subtitle_filter = _build_subtitle_filter(safe_srt)
            vf = f"{crop_filter},{subtitle_filter}"
            return _run_ffmpeg(source, output_path, start, end, vf, crf, preset)
    else:
        vf = crop_filter
        return _run_ffmpeg(source, output_path, start, end, vf, crf, preset)


def _run_ffmpeg(
    source: Path,
    output_path: Path,
    start: float,
    end: float,
    vf: str,
    crf: int,
    preset: str,
) -> Path:
    cmd = [
        setup_env.get_ffmpeg(), "-y",
        "-ss", str(start),
        "-to", str(end),
        "-i", str(source),
        "-vf", vf,
        # Video: H.264 High profile, yuv420p required by YouTube/Instagram/TikTok
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level", "4.0",
        "-pix_fmt", "yuv420p",
        "-preset", preset,
        "-crf", str(crf),
        # Audio: AAC stereo, 44100 Hz — normalized for all platforms
        "-c:a", "aac",
        "-ac", "2",
        "-ar", "44100",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    logger.debug("FFmpeg: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("FFmpeg stderr:\n%s", result.stderr[-1000:])
        raise RuntimeError(
            f"FFmpeg failed (exit {result.returncode}) for {output_path.name}"
        )

    logger.info("Rendered: %s", output_path.name)
    return output_path


def _srt_has_content(srt_path: Path) -> bool:
    """Return True only if the SRT file exists and has at least one subtitle block."""
    try:
        return srt_path.exists() and srt_path.stat().st_size > 10
    except Exception:
        return False


def _build_crop_filter(src_w: int, src_h: int) -> str:
    """
    Return an FFmpeg vf filter string that converts any source aspect ratio
    to 1080×1920 (9:16).

    - Wide (landscape) source → center-crop a 9:16 column → scale.
    - Already ~9:16 → scale only.
    - Narrow / portrait → scale to height, blur-pad the sides.
    """
    if src_w == 0 or src_h == 0:
        return f"crop=ih*9/16:ih,scale={TARGET_W}:{TARGET_H}"

    src_ratio = src_w / src_h
    target_ratio = TARGET_W / TARGET_H  # ≈ 0.5625

    if src_ratio > target_ratio + 0.02:
        # Landscape → center-crop vertical column
        return f"crop=ih*9/16:ih,scale={TARGET_W}:{TARGET_H}"
    elif abs(src_ratio - target_ratio) <= 0.02:
        return f"scale={TARGET_W}:{TARGET_H}"
    else:
        # Portrait or square → blur-pad sides
        return (
            f"split[fg][bg];"
            f"[bg]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},boxblur=20:20[blurred];"
            f"[fg]scale=-2:{TARGET_H}[scaled];"
            f"[blurred][scaled]overlay=(W-w)/2:(H-h)/2"
        )


def _build_subtitle_filter(srt_path: Path) -> str:
    """Return the subtitles FFmpeg filter string with safe font styling."""
    srt_str = str(srt_path.resolve())

    if platform.system() == "Windows":
        # FFmpeg subtitles filter on Windows: use forward slashes,
        # escape the drive-letter colon as \:
        srt_str = srt_str.replace("\\", "/")
        if len(srt_str) >= 2 and srt_str[1] == ":":
            srt_str = srt_str[0] + "\\:" + srt_str[2:]
    else:
        srt_str = srt_str.replace(":", "\\:")

    style = (
        "FontName=Arial,"
        "FontSize=15,"
        "Bold=1,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BackColour=&H80000000,"
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=80"
    )

    return f"subtitles='{srt_str}':force_style='{style}'"
