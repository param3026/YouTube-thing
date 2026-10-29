"""Convert transcript segments to SRT subtitle files."""

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

Segment = dict[str, Any]

MAX_CHARS = 38   # characters per line before wrapping
MAX_WORDS = 7    # words per caption block
SENTENCE_END = re.compile(r"[.!?]\s*$")


def segments_to_srt(
    segments: list[Segment],
    clip_start: float,
    clip_end: float,
    output_path: Path,
) -> Path:
    """
    Filter segments that fall within [clip_start, clip_end],
    shift times to clip-relative, then write an SRT file.
    """
    output_path = Path(output_path)
    relevant = [
        s for s in segments
        if s["end"] > clip_start and s["start"] < clip_end
    ]

    if not relevant:
        logger.warning("No transcript segments found for clip [%.2f–%.2f]", clip_start, clip_end)

    has_words = any(s.get("words") for s in relevant)
    if has_words:
        blocks = _word_level_blocks(relevant, clip_start, clip_end)
    else:
        blocks = _segment_level_blocks(relevant, clip_start)

    _write_srt(blocks, output_path)
    logger.info("SRT written: %s (%d blocks)", output_path, len(blocks))
    return output_path


# ---------------------------------------------------------------------------
# Word-level captions (preferred — uses Whisper word timestamps)
# ---------------------------------------------------------------------------

def _word_level_blocks(
    segments: list[Segment],
    clip_start: float,
    clip_end: float,
) -> list[dict]:
    """
    Build caption blocks from word timestamps, respecting sentence endings
    so blocks never split across sentence boundaries when avoidable.
    """
    # Collect all words in the clip window with clip-relative timestamps
    all_words = []
    for seg in segments:
        for w in seg.get("words", []):
            ws = w["start"]
            we = w["end"]
            if we <= clip_start or ws >= clip_end:
                continue
            all_words.append({
                "word": w["word"].strip(),
                "start": max(0.0, ws - clip_start),
                "end":   max(0.0, we - clip_start),
            })

    if not all_words:
        return []

    blocks = []
    i = 0
    while i < len(all_words):
        chunk: list[dict] = []
        j = i
        while j < len(all_words) and len(chunk) < MAX_WORDS:
            chunk.append(all_words[j])
            text_so_far = " ".join(w["word"] for w in chunk)
            j += 1
            # Prefer to break at sentence end
            if SENTENCE_END.search(text_so_far):
                break

        if not chunk:
            i += 1
            continue

        text = " ".join(w["word"] for w in chunk).strip()
        if text:
            blocks.append({
                "start": chunk[0]["start"],
                "end":   chunk[-1]["end"],
                "text":  _wrap(text),
            })
        i = j

    return blocks


# ---------------------------------------------------------------------------
# Segment-level captions (fallback — no word timestamps)
# ---------------------------------------------------------------------------

def _segment_level_blocks(segments: list[Segment], clip_start: float) -> list[dict]:
    blocks = []
    for seg in segments:
        start = max(0.0, seg["start"] - clip_start)
        end   = max(0.0, seg["end"]   - clip_start)
        text  = seg["text"].strip()
        if not text or end <= start:
            continue

        words = text.split()
        seg_dur = end - start
        idx = 0
        while idx < len(words):
            chunk_words = words[idx: idx + MAX_WORDS]
            frac_start = idx / len(words)
            frac_end   = min((idx + MAX_WORDS) / len(words), 1.0)
            blocks.append({
                "start": round(start + frac_start * seg_dur, 3),
                "end":   round(start + frac_end   * seg_dur, 3),
                "text":  _wrap(" ".join(chunk_words)),
            })
            idx += MAX_WORDS

    return blocks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap(text: str) -> str:
    """Wrap caption text so no line exceeds MAX_CHARS characters."""
    if len(text) <= MAX_CHARS:
        return text
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        needed = len(word) + (1 if current else 0)
        if current_len + needed > MAX_CHARS and current:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += needed
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _write_srt(blocks: list[dict], path: Path) -> None:
    lines: list[str] = []
    for idx, block in enumerate(blocks, 1):
        lines += [
            str(idx),
            f"{_ts(block['start'])} --> {_ts(block['end'])}",
            block["text"],
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _ts(seconds: float) -> str:
    """Float seconds → SRT timestamp HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
