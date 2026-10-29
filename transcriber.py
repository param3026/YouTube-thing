"""Transcribe video audio using OpenAI Whisper (local)."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import setup_env
setup_env.ensure_ffmpeg()  # Whisper needs ffmpeg on PATH to decode video audio

logger = logging.getLogger(__name__)

# Segment shape produced by this module:
# {"start": float, "end": float, "text": str, "words": [...]}
Segment = dict[str, Any]


def transcribe(
    video_path: Path,
    cache_dir: Path,
    model: str = "base",
    language: str = "en",
    force: bool = False,
) -> list[Segment]:
    """
    Transcribe *video_path* with Whisper and return a list of Segment dicts.

    Results are cached in *cache_dir* as `transcript_<stem>.json`.
    Set *force=True* to re-transcribe even if a cache file exists.
    """
    video_path = Path(video_path)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = cache_dir / f"transcript_{video_path.stem}.json"

    if cache_file.exists() and not force:
        logger.info("Cache hit — loading transcript: %s", cache_file)
        return json.loads(cache_file.read_text(encoding="utf-8"))

    logger.info("Transcribing with Whisper model=%s …", model)
    segments = _run_whisper(video_path, model, language, cache_dir)

    cache_file.write_text(
        json.dumps(segments, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Transcript cached: %s (%d segments)", cache_file, len(segments))
    return segments


def _run_whisper(
    video_path: Path,
    model: str,
    language: str,
    tmp_dir: Path,
) -> list[Segment]:
    """
    Try the Python Whisper API first; fall back to CLI.
    Returns normalised list of segments.
    """
    try:
        return _whisper_python_api(video_path, model, language)
    except ImportError:
        logger.warning("whisper Python package not found — falling back to CLI.")
    except Exception as exc:
        logger.warning("Whisper Python API failed (%s) — falling back to CLI.", exc)

    return _whisper_cli(video_path, model, language, tmp_dir)


def _whisper_python_api(
    video_path: Path, model: str, language: str
) -> list[Segment]:
    """Run Whisper via the openai-whisper Python package."""
    import whisper  # type: ignore

    logger.info("Loading Whisper model '%s' via Python API …", model)
    wmodel = whisper.load_model(model)

    result = wmodel.transcribe(
        str(video_path),
        language=language,
        verbose=False,
        word_timestamps=True,
    )

    segments = []
    for seg in result.get("segments", []):
        words = []
        for w in seg.get("words", []):
            words.append(
                {
                    "start": w.get("start", seg["start"]),
                    "end": w.get("end", seg["end"]),
                    "word": w.get("word", "").strip(),
                }
            )
        segments.append(
            {
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
                "words": words,
            }
        )

    logger.info("Whisper produced %d segments.", len(segments))
    return segments


def _whisper_cli(
    video_path: Path, model: str, language: str, tmp_dir: Path
) -> list[Segment]:
    """Run Whisper as a subprocess and parse its JSON output."""
    cmd = [
        sys.executable, "-m", "whisper",
        str(video_path),
        "--model", model,
        "--language", language,
        "--output_format", "json",
        "--output_dir", str(tmp_dir),
        "--word_timestamps", "True",
    ]

    logger.debug("whisper CLI: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"Whisper CLI failed (exit {result.returncode}):\n{result.stderr[-800:]}"
        )

    # Whisper writes <stem>.json next to the input file or in output_dir
    json_out = tmp_dir / f"{video_path.stem}.json"
    if not json_out.exists():
        raise FileNotFoundError(
            f"Whisper JSON output not found at expected path: {json_out}"
        )

    raw = json.loads(json_out.read_text(encoding="utf-8"))
    segments = []
    for seg in raw.get("segments", []):
        words = [
            {
                "start": w.get("start", seg["start"]),
                "end": w.get("end", seg["end"]),
                "word": w.get("word", "").strip(),
            }
            for w in seg.get("words", [])
        ]
        segments.append(
            {
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
                "words": words,
            }
        )

    return segments


def check_whisper() -> bool:
    """Return True if whisper is importable or available as a CLI."""
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        r = subprocess.run(
            [sys.executable, "-m", "whisper", "--help"],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False
