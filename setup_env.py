"""
Locate bundled ffmpeg binary (via imageio-ffmpeg) and inject it into PATH
so that subprocess calls to 'ffmpeg' resolve correctly.

Also creates ffmpeg.exe and ffprobe.exe aliases in the binary directory
so that any tool (including Whisper) that calls 'ffmpeg' via PATH finds it.
"""

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_FFMPEG_PATH: str = ""
_FFPROBE_PATH: str = ""


def ensure_ffmpeg() -> tuple[str, str]:
    """
    Return (ffmpeg_exe, ffprobe_exe) paths and ensure both are on PATH.

    Priority:
      1. ffmpeg already on system PATH (and is actually named ffmpeg/ffprobe)
      2. imageio-ffmpeg bundled binary → copies to ffmpeg.exe / ffprobe.exe
    """
    global _FFMPEG_PATH, _FFPROBE_PATH

    if _FFMPEG_PATH:
        return _FFMPEG_PATH, _FFPROBE_PATH

    system_ff = shutil.which("ffmpeg")
    system_fp = shutil.which("ffprobe")

    if system_ff and system_fp:
        _FFMPEG_PATH = system_ff
        _FFPROBE_PATH = system_fp
        logger.info("Using system ffmpeg: %s", system_ff)
        return _FFMPEG_PATH, _FFPROBE_PATH

    # Try imageio-ffmpeg bundled binary
    try:
        import imageio_ffmpeg  # type: ignore

        bundled = Path(imageio_ffmpeg.get_ffmpeg_exe())
        bundled_dir = bundled.parent

        ffmpeg_alias = bundled_dir / "ffmpeg.exe"
        ffprobe_alias = bundled_dir / "ffprobe.exe"

        # Create aliases named ffmpeg.exe / ffprobe.exe so PATH resolution works
        if not ffmpeg_alias.exists():
            shutil.copy2(bundled, ffmpeg_alias)
            logger.info("Created ffmpeg.exe alias: %s", ffmpeg_alias)

        if not ffprobe_alias.exists():
            shutil.copy2(bundled, ffprobe_alias)
            logger.info("Created ffprobe.exe alias: %s", ffprobe_alias)

        # Prepend to PATH so any subprocess finds these before anything else
        current_path = os.environ.get("PATH", "")
        bundled_dir_str = str(bundled_dir)
        if bundled_dir_str not in current_path:
            os.environ["PATH"] = bundled_dir_str + os.pathsep + current_path
            logger.info("Added to PATH: %s", bundled_dir_str)

        _FFMPEG_PATH = str(ffmpeg_alias)
        _FFPROBE_PATH = str(ffprobe_alias)
        return _FFMPEG_PATH, _FFPROBE_PATH

    except ImportError:
        logger.warning("imageio-ffmpeg not installed; ffmpeg must be on PATH.")
    except Exception as exc:
        logger.warning("imageio-ffmpeg setup failed: %s", exc)

    # Last resort: hope they're on PATH
    _FFMPEG_PATH = system_ff or "ffmpeg"
    _FFPROBE_PATH = system_fp or "ffprobe"
    return _FFMPEG_PATH, _FFPROBE_PATH


def get_ffmpeg() -> str:
    return ensure_ffmpeg()[0]


def get_ffprobe() -> str:
    return ensure_ffmpeg()[1]
