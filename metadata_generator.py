"""Generate report.json and report.md after pipeline completion."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_title(clip: dict) -> str:
    """Derive a short, punchy title from the first sentence of the clip's text."""
    text = clip.get("text", "").strip()
    # Take the first sentence
    match = re.match(r"^([^.!?]{10,80}[.!?]?)", text)
    if match:
        title = match.group(1).strip().rstrip(".")
    else:
        title = text[:60].strip()
    # Title-case and trim
    return title[:72]


def generate_hashtags(clip: dict, max_tags: int = 5) -> list[str]:
    """Extract likely hashtag keywords from the clip text."""
    text = clip.get("text", "").lower()
    words = re.findall(r"\b[a-z]{4,}\b", text)
    # Exclude very common words
    stopwords = {
        "that", "this", "with", "from", "have", "been", "they",
        "will", "what", "when", "your", "about", "just", "some",
        "more", "than", "into", "also", "very", "here", "there",
    }
    freq: dict[str, int] = {}
    for w in words:
        if w not in stopwords:
            freq[w] = freq.get(w, 0) + 1
    top_words = sorted(freq, key=lambda w: -freq[w])[:max_tags]
    return ["#" + w.capitalize() for w in top_words]


def build_report_entry(
    clip: dict,
    clip_index: int,
    clip_file: Path,
    srt_file: Path,
    validation: dict,
    source_url: str = "",
) -> dict[str, Any]:
    """Return a single report dict for one rendered clip."""
    return {
        "clip": clip_file.name,
        "index": clip_index,
        "source": source_url,
        "start_time": clip["start"],
        "end_time": clip["end"],
        "duration": clip["duration"],
        "title": generate_title(clip),
        "score": clip.get("score", 0),
        "scores": clip.get("scores", {}),
        "transcript_excerpt": clip.get("text", "")[:400],
        "hashtags": generate_hashtags(clip),
        "srt_file": srt_file.name,
        "validation": validation,
        "rendered_at": datetime.utcnow().isoformat() + "Z",
    }


def write_json_report(entries: list[dict], output_dir: Path) -> Path:
    """Write report.json to *output_dir*."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps({"clips": entries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("JSON report written: %s", report_path)
    return report_path


def write_markdown_report(entries: list[dict], output_dir: Path, source: str = "") -> Path:
    """Write report.md to *output_dir*."""
    output_dir = Path(output_dir)
    report_path = output_dir / "report.md"

    lines = [
        "# YouTube Shorts — Pipeline Report",
        "",
        f"**Source:** {source or 'N/A'}  ",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"**Clips produced:** {len(entries)}",
        "",
        "---",
        "",
    ]

    ok_count = sum(1 for e in entries if e.get("validation", {}).get("ok", False))
    failed_count = len(entries) - ok_count
    lines += [
        f"**Passed validation:** {ok_count}  ",
        f"**Failed validation:** {failed_count}",
        "",
        "---",
        "",
    ]

    for e in entries:
        val = e.get("validation", {})
        status = "[OK]" if val.get("ok") else "[WARN]"
        issues = val.get("issues", [])
        issue_str = "; ".join(issues) if issues else "None"

        lines += [
            f"## {status} Clip {e['index']:03d}: {e['title']}",
            "",
            f"- **File:** `{e['clip']}`",
            f"- **Duration:** {e['duration']:.1f}s  ({e['start_time']:.1f}s → {e['end_time']:.1f}s)",
            f"- **Score:** {e['score']:.1f}",
            f"- **Tags:** {' '.join(e.get('hashtags', []))}",
            f"- **Validation:** {issue_str}",
            "",
            f"> {e['transcript_excerpt'][:200]}",
            "",
            "---",
            "",
        ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Markdown report written: %s", report_path)
    return report_path
