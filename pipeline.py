"""
Orchestrate the full YouTube-to-Shorts pipeline.

Steps:
  1. Download / validate source video
  2. Probe media metadata
  3. Transcribe with Whisper
  4. Generate + score + select clip candidates
  5. Refine timestamps
  6. For each selected clip:
       a. Generate SRT
       b. Render Short (FFmpeg)
       c. Validate output
       d. Build report entry
  7. Write JSON + Markdown reports
"""

import logging
import time
from pathlib import Path
from typing import Any

import caption_generator
import clip_selector
import downloader
import editor
import media_probe
import metadata_generator
import timestamp_refiner
import transcriber

logger = logging.getLogger(__name__)


def run(
    source: str,
    *,
    output_dir: Path,
    cache_dir: Path,
    num_clips: int = 10,
    whisper_model: str = "base",
    language: str = "en",
    min_duration: float = 15.0,
    max_duration: float = 60.0,
    crf: int = 23,
    ffmpeg_preset: str = "fast",
    force_transcribe: bool = False,
) -> dict[str, Any]:
    """
    Run the complete pipeline for *source* (URL or file path).

    Returns a summary dict with clip entries and any failures.
    """
    t_start = time.monotonic()
    output_dir = Path(output_dir)
    cache_dir = Path(cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    report_entries: list[dict] = []
    failures: list[str] = []

    # ------------------------------------------------------------------ #
    # Step 1 – Download / validate
    # ------------------------------------------------------------------ #
    logger.info("=== Step 1: Input handling ===")
    try:
        video_path = downloader.download(source, cache_dir)
    except Exception as exc:
        logger.error("Download failed: %s", exc)
        return {"success": False, "error": str(exc), "clips": [], "failures": []}

    # ------------------------------------------------------------------ #
    # Step 2 – Media probe
    # ------------------------------------------------------------------ #
    logger.info("=== Step 2: Media probe ===")
    try:
        meta = media_probe.probe(video_path)
    except Exception as exc:
        logger.error("Media probe failed: %s", exc)
        return {"success": False, "error": str(exc), "clips": [], "failures": []}

    video_duration = meta["duration"]
    src_width = meta["width"]
    src_height = meta["height"]
    logger.info(
        "Source: %s — %.1fs, %dx%d",
        video_path.name, video_duration, src_width, src_height,
    )

    if not meta["has_audio"]:
        logger.warning("Source has no audio track — captions will be empty.")

    # ------------------------------------------------------------------ #
    # Step 3 – Transcribe
    # ------------------------------------------------------------------ #
    logger.info("=== Step 3: Transcription ===")
    try:
        segments = transcriber.transcribe(
            video_path,
            cache_dir=cache_dir,
            model=whisper_model,
            language=language,
            force=force_transcribe,
        )
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        return {"success": False, "error": str(exc), "clips": [], "failures": []}

    if not segments:
        logger.warning("Transcription returned no segments — scoring will rely on fallback.")

    # ------------------------------------------------------------------ #
    # Step 4 – Candidate generation + scoring + selection
    # ------------------------------------------------------------------ #
    logger.info("=== Step 4: Clip selection ===")
    candidates = clip_selector.generate_candidates(
        segments, min_dur=min_duration, max_dur=max_duration
    )

    # Fallback: if transcription produced no usable candidates,
    # create fixed-window candidates across the video.
    if not candidates:
        logger.warning("No transcript-based candidates; using fixed windows.")
        candidates = _fixed_window_candidates(video_duration, min_duration, max_duration)

    scored = clip_selector.score_candidates(candidates)
    selected = clip_selector.select_top(scored, n=num_clips)

    if not selected:
        logger.error("No clips selected — pipeline cannot continue.")
        return {"success": False, "error": "No clips selected.", "clips": [], "failures": []}

    # ------------------------------------------------------------------ #
    # Step 5 – Refine timestamps
    # ------------------------------------------------------------------ #
    logger.info("=== Step 5: Timestamp refinement ===")
    selected = timestamp_refiner.refine_all(
        selected,
        all_segments=segments,
        video_duration=video_duration,
        min_dur=min_duration,
        max_dur=max_duration,
    )

    # ------------------------------------------------------------------ #
    # Step 6 – Render each clip
    # ------------------------------------------------------------------ #
    logger.info("=== Step 6: Rendering %d clip(s) ===", len(selected))
    for idx, clip in enumerate(selected, 1):
        clip_name = f"short_{idx:03d}"
        srt_path = output_dir / f"{clip_name}.srt"
        mp4_path = output_dir / f"{clip_name}.mp4"

        logger.info(
            "Clip %d/%d — [%.1fs–%.1fs] score=%.1f",
            idx, len(selected), clip["start"], clip["end"], clip["score"],
        )

        try:
            # 6a – Generate SRT
            caption_generator.segments_to_srt(
                segments,
                clip_start=clip["start"],
                clip_end=clip["end"],
                output_path=srt_path,
            )

            # 6b – Render
            editor.render_clip(
                source=video_path,
                srt_path=srt_path,
                output_path=mp4_path,
                start=clip["start"],
                end=clip["end"],
                source_width=src_width,
                source_height=src_height,
                crf=crf,
                preset=ffmpeg_preset,
            )

            # 6c – Validate
            validation = media_probe.verify_short(mp4_path)
            if not validation["ok"]:
                logger.warning(
                    "Clip %s failed validation: %s",
                    clip_name, validation["issues"],
                )

            # 6d – Build report entry
            entry = metadata_generator.build_report_entry(
                clip=clip,
                clip_index=idx,
                clip_file=mp4_path,
                srt_file=srt_path,
                validation=validation,
                source_url=source,
            )
            report_entries.append(entry)

        except Exception as exc:
            logger.error("Clip %s failed: %s", clip_name, exc, exc_info=True)
            failures.append(f"{clip_name}: {exc}")

    # ------------------------------------------------------------------ #
    # Step 7 – Reports
    # ------------------------------------------------------------------ #
    logger.info("=== Step 7: Writing reports ===")
    if report_entries:
        metadata_generator.write_json_report(report_entries, output_dir)
        metadata_generator.write_markdown_report(report_entries, output_dir, source=source)

    elapsed = time.monotonic() - t_start
    ok_count = sum(1 for e in report_entries if e.get("validation", {}).get("ok"))
    logger.info(
        "Pipeline complete in %.1fs — %d/%d clips OK, %d failed.",
        elapsed, ok_count, len(selected), len(failures),
    )

    return {
        "success": len(failures) < len(selected),
        "clips": report_entries,
        "failures": failures,
        "elapsed_seconds": round(elapsed, 1),
        "output_dir": str(output_dir),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixed_window_candidates(
    video_duration: float,
    min_dur: float,
    max_dur: float,
) -> list[dict]:
    """Generate fixed sliding-window candidates when transcript is unavailable."""
    target = min(45.0, max_dur)   # aim for 45 s per window
    step   = target * 0.5         # 50 % overlap for better coverage
    candidates = []
    start = 0.0
    while start + min_dur < video_duration:
        end = min(start + target, video_duration)
        dur = end - start
        if dur >= min_dur:
            candidates.append(
                {
                    "start": start,
                    "end": end,
                    "duration": dur,
                    "text": "",
                    "segments": [],
                    "first_seg_idx": 0,
                    "last_seg_idx": 0,
                }
            )
        start += step
    return candidates
