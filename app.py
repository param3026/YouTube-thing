#!/usr/bin/env python3
"""
YouTube-to-Shorts CLI

Usage:
  python app.py process --url <YOUTUBE_URL> --clips 10
  python app.py process --file path/to/video.mp4 --clips 5 --output my_shorts
  python app.py doctor
  python app.py clean-cache
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

import setup_env
setup_env.ensure_ffmpeg()  # inject bundled ffmpeg into PATH before any subprocess

# ---------------------------------------------------------------------------
# Logging setup — write to console AND file
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"


def _setup_logging(output_dir: Path, verbose: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(ch)

    # File handler
    fh = logging.FileHandler(output_dir / "pipeline.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(fh)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_process(args: argparse.Namespace) -> int:
    """Run the full pipeline."""
    import pipeline

    output_dir = Path(args.output)
    cache_dir = output_dir / "cache"

    _setup_logging(output_dir, verbose=args.verbose)
    logger = logging.getLogger("app")

    source = args.url or args.file
    if not source:
        logger.error("Provide either --url or --file.")
        return 1

    logger.info("Starting pipeline for: %s", source)
    logger.info("Clips requested: %d | Model: %s | Output: %s", args.clips, args.model, output_dir)

    result = pipeline.run(
        source=source,
        output_dir=output_dir,
        cache_dir=cache_dir,
        num_clips=args.clips,
        whisper_model=args.model,
        language=args.language,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        force_transcribe=args.force_transcribe,
    )

    if result.get("failures"):
        logger.warning("Failed clips:")
        for f in result["failures"]:
            logger.warning("  %s", f)

    if result["clips"]:
        logger.info("Output folder: %s", result["output_dir"])
        logger.info("Done. %d clip(s) produced.", len(result["clips"]))
        logger.info("Review report.md in the output folder before uploading.")
    else:
        logger.error("No clips were produced.")

    return 0 if result.get("success") else 1


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Check all dependencies."""
    import downloader
    import media_probe
    import transcriber

    print("\n=== Dependency Check ===\n")
    all_ok = True

    checks = [
        ("Python 3.9+", _check_python()),
        ("ffmpeg / ffprobe", media_probe.check_ffmpeg()),
        ("yt-dlp", downloader.check_ytdlp()),
        ("Whisper", transcriber.check_whisper()),
        ("Ollama (optional)", _check_ollama()),
    ]

    for name, ok in checks:
        status = "[OK]     " if ok else "[MISSING]"
        print(f"  {name:<25} {status}")
        if not ok and name != "Ollama (optional)":
            all_ok = False

    print()
    if all_ok:
        print("All required dependencies are present. Ready to run!\n")
    else:
        print("One or more required dependencies are missing.\n"  )
        print("Install guide:")
        print("  ffmpeg:   https://ffmpeg.org/download.html")
        print("  yt-dlp:   pip install yt-dlp")
        print("  Whisper:  pip install openai-whisper\n")

    return 0 if all_ok else 1


def cmd_clean_cache(args: argparse.Namespace) -> int:
    """Remove cached downloads and transcripts."""
    cache_dir = Path(args.output) / "cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        print(f"Cache cleared: {cache_dir}")
    else:
        print("No cache directory found.")
    return 0


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def _check_python() -> bool:
    return sys.version_info >= (3, 9)


def _check_ollama() -> bool:
    import subprocess
    try:
        r = subprocess.run(["ollama", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description="YouTube-to-Shorts automated pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- process ---
    proc = sub.add_parser("process", help="Run the full pipeline")
    src = proc.add_mutually_exclusive_group()
    src.add_argument("--url", metavar="URL", help="YouTube video URL")
    src.add_argument("--file", metavar="PATH", help="Local video file path")
    proc.add_argument("--clips", type=int, default=10, metavar="N", help="Number of Shorts to produce (default: 10)")
    proc.add_argument("--output", default="output", metavar="DIR", help="Output directory (default: output)")
    proc.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large"], help="Whisper model (default: base)")
    proc.add_argument("--language", default="en", metavar="LANG", help="Language code for Whisper (default: en)")
    proc.add_argument("--min-duration", type=float, default=15.0, metavar="SEC", help="Minimum clip duration in seconds (default: 15)")
    proc.add_argument("--max-duration", type=float, default=59.0, metavar="SEC", help="Maximum clip duration in seconds (default: 59 — just under YouTube Shorts 60s cap)")
    proc.add_argument("--force-transcribe", action="store_true", help="Re-transcribe even if cache exists")
    proc.add_argument("--verbose", "-v", action="store_true", help="Enable verbose (debug) logging")

    # --- doctor ---
    sub.add_parser("doctor", help="Check all dependencies")

    # --- clean-cache ---
    clean = sub.add_parser("clean-cache", help="Remove cached files")
    clean.add_argument("--output", default="output", metavar="DIR", help="Output directory containing cache (default: output)")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "process": cmd_process,
        "doctor": cmd_doctor,
        "clean-cache": cmd_clean_cache,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
