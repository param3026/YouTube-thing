"""Refine clip start/end times to align with sentence (segment) boundaries."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

Segment = dict[str, Any]


def refine(
    clip: dict,
    all_segments: list[Segment],
    video_duration: float,
    padding: float = 0.5,
    min_dur: float = 15.0,
    max_dur: float = 60.0,
) -> dict:
    """
    Given a candidate clip dict and the full transcript segments list,
    snap start/end to segment boundaries and add *padding* on both sides.

    Returns an updated clip dict (does not mutate the original).
    """
    raw_start: float = clip["start"]
    raw_end: float = clip["end"]

    # Snap start to the nearest segment start ≤ raw_start (max 2 s back)
    new_start = _snap_start(raw_start, all_segments, lookback=2.0)

    # Snap end to the nearest segment end ≥ raw_end (max 2 s forward)
    new_end = _snap_end(raw_end, all_segments, look_forward=2.0)

    # Apply padding
    new_start = max(0.0, new_start - padding)
    new_end = min(video_duration, new_end + padding)

    # Clamp to duration limits
    duration = new_end - new_start
    if duration > max_dur:
        # Trim from end
        new_end = new_start + max_dur
        duration = max_dur
    elif duration < min_dur:
        # Extend end if possible
        extra = min_dur - duration
        new_end = min(video_duration, new_end + extra)
        duration = new_end - new_start

    refined = dict(clip)
    refined["start"] = round(new_start, 3)
    refined["end"] = round(new_end, 3)
    refined["duration"] = round(new_end - new_start, 3)

    logger.debug(
        "Refined [%.2f–%.2f] → [%.2f–%.2f] (%.1fs)",
        raw_start, raw_end, refined["start"], refined["end"], refined["duration"],
    )
    return refined


def _snap_start(
    raw_start: float,
    segments: list[Segment],
    lookback: float,
) -> float:
    """Find the segment start closest to raw_start, looking back up to lookback seconds."""
    best = raw_start
    best_dist = float("inf")
    for seg in segments:
        seg_start = seg["start"]
        if seg_start <= raw_start and (raw_start - seg_start) <= lookback:
            dist = raw_start - seg_start
            if dist < best_dist:
                best_dist = dist
                best = seg_start
    return best


def _snap_end(
    raw_end: float,
    segments: list[Segment],
    look_forward: float,
) -> float:
    """Find the segment end closest to raw_end, looking forward up to look_forward seconds."""
    best = raw_end
    best_dist = float("inf")
    for seg in segments:
        seg_end = seg["end"]
        if seg_end >= raw_end and (seg_end - raw_end) <= look_forward:
            dist = seg_end - raw_end
            if dist < best_dist:
                best_dist = dist
                best = seg_end
    return best


def refine_all(
    clips: list[dict],
    all_segments: list[Segment],
    video_duration: float,
    padding: float = 0.5,
    min_dur: float = 15.0,
    max_dur: float = 60.0,
) -> list[dict]:
    """Apply refine() to every clip in *clips*."""
    return [
        refine(c, all_segments, video_duration, padding, min_dur, max_dur)
        for c in clips
    ]
