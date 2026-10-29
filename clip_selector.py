"""
Generate, score, and select highlight clip candidates from a transcript.

Scoring rubric (weights sum to 1.0):
  Hook strength      25% – attention-grabbing opening
  Content interest   25% – information density / surprise
  Standalone context 20% – makes sense without surrounding video
  Payoff / closure   15% – reaches a satisfying end
  Pacing             10% – speech fluency (words per second)
  Duration fit        5% – prefers 45–59 s (YouTube Shorts algorithm sweet spot)

YouTube Shorts duration research:
  - Eligible:      15–60 s (hard limit)
  - High retention: 45–59 s maximises watch-time signal sent to algorithm
  - Viral range:   30–59 s (high completion + enough content for engagement)
  - Under 15 s:    penalised (too short to build any watch-time signal)
  The scoring therefore targets 45 s with full marks for 30–59 s.
"""

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

Segment = dict[str, Any]

# Keywords that hint at a strong hook / interesting content
HOOK_WORDS = {
    "imagine", "what if", "here's", "actually", "surprising",
    "secret", "truth", "nobody", "everyone", "mistake", "wrong",
    "never", "always", "why", "how", "best", "worst", "most",
    "incredible", "unbelievable", "finally", "simple", "easy",
    "really", "honestly", "story", "happened", "discovered",
}

FILLER_WORDS = {
    "um", "uh", "like", "you know", "sort of", "kind of",
    "basically", "literally", "whatever", "anyway",
}

# Phrases that indicate dependence on prior context
CONTEXT_DEPENDENT = {
    "as i said", "as i mentioned", "earlier", "back to",
    "like i said", "we covered", "remember when", "previous",
    "going back", "as we discussed",
}

WEIGHT_HOOK = 0.25
WEIGHT_CONTENT = 0.25
WEIGHT_CONTEXT = 0.20
WEIGHT_PAYOFF = 0.15
WEIGHT_PACING = 0.10
WEIGHT_DURATION = 0.05

MIN_DURATION = 15.0
MAX_DURATION = 59.0   # YouTube Shorts hard cap is 60 s; stay just under
TARGET_DURATION = 45.0  # sweet spot — maximises watch-time algorithm signal
SWEET_RANGE_LO = 30.0   # full score starts here
SWEET_RANGE_HI = 59.0   # full score ends here


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def generate_candidates(
    segments: list[Segment],
    min_dur: float = MIN_DURATION,
    max_dur: float = MAX_DURATION,
    step_size: float = 5.0,
) -> list[dict]:
    """
    Slide a window over the segments list to create candidate clips.
    Each candidate: {"start", "end", "text", "segments"}
    """
    candidates = []
    n = len(segments)

    for i in range(n):
        accumulated = []
        for j in range(i, n):
            seg = segments[j]
            if not accumulated:
                start = seg["start"]
            end = seg["end"]
            accumulated.append(seg)
            duration = end - start

            if duration < min_dur:
                continue
            if duration > max_dur:
                break

            text = " ".join(s["text"].strip() for s in accumulated)
            candidates.append(
                {
                    "start": start,
                    "end": end,
                    "duration": duration,
                    "text": text,
                    "segments": list(accumulated),
                    "first_seg_idx": i,
                    "last_seg_idx": j,
                }
            )

    logger.info("Generated %d raw candidates.", len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_candidates(candidates: list[dict]) -> list[dict]:
    """Attach a 'score' (0–100) and 'scores' dict to each candidate."""
    scored = []
    for c in candidates:
        s = _score_one(c)
        c = dict(c)
        c["scores"] = s
        c["score"] = round(
            WEIGHT_HOOK * s["hook"]
            + WEIGHT_CONTENT * s["content"]
            + WEIGHT_CONTEXT * s["context"]
            + WEIGHT_PAYOFF * s["payoff"]
            + WEIGHT_PACING * s["pacing"]
            + WEIGHT_DURATION * s["duration_fit"],
            2,
        )
        scored.append(c)
    return scored


def _score_one(c: dict) -> dict[str, float]:
    text: str = c["text"]
    duration: float = c["duration"]
    words = text.lower().split()
    word_count = len(words)
    first_sentence = _first_sentence(text)

    return {
        "hook": _score_hook(first_sentence),
        "content": _score_content(text, words),
        "context": _score_context(text.lower()),
        "payoff": _score_payoff(text),
        "pacing": _score_pacing(word_count, duration),
        "duration_fit": _score_duration(duration),
    }


def _first_sentence(text: str) -> str:
    for delim in (".", "!", "?"):
        idx = text.find(delim)
        if idx != -1:
            return text[: idx + 1]
    return text[:120]


def _score_hook(sentence: str) -> float:
    s = sentence.lower()
    score = 0.0

    # Starts with a question mark at end → strong hook
    if sentence.strip().endswith("?"):
        score += 40

    # Starts with hook words
    for w in HOOK_WORDS:
        if w in s[:60]:
            score += 15
            break

    # Exclamation
    if "!" in sentence:
        score += 10

    # Starts with imperative or bold statement patterns
    if re.match(r"^(here'?s|imagine|think about|what if|the (best|worst|biggest|real|only))", s):
        score += 20

    # Capitalized first word (normal) but also number-led facts
    if re.match(r"^\d+", sentence.strip()):
        score += 10

    return min(score, 100.0)


def _score_content(text: str, words: list[str]) -> float:
    score = 30.0  # base

    # Unique word ratio (lexical richness)
    if words:
        lexical_richness = len(set(words)) / len(words)
        score += lexical_richness * 30

    # Hook / interesting word presence
    word_set = set(words)
    hook_hits = len(HOOK_WORDS & word_set)
    score += min(hook_hits * 8, 25)

    # Penalise filler words
    filler_hits = sum(1 for w in words if w in FILLER_WORDS)
    score -= filler_hits * 3

    # Question or exclamation in body → engaging
    if "?" in text:
        score += 5
    if "!" in text:
        score += 5

    # Number / statistic presence (facts feel credible)
    if re.search(r"\b\d+\b", text):
        score += 5

    return max(0.0, min(score, 100.0))


def _score_context(text_lower: str) -> float:
    score = 80.0  # assume standalone by default

    for phrase in CONTEXT_DEPENDENT:
        if phrase in text_lower:
            score -= 20
            break

    # Starts mid-sentence (no capital at start or starts with conjunction)
    first_word = text_lower.split()[0] if text_lower.split() else ""
    if first_word in ("and", "but", "so", "then", "also", "or", "because"):
        score -= 15

    # References pronouns with no antecedent in clip
    if re.search(r"\b(he|she|they|it|this|that)\b", text_lower[:50]):
        score -= 10

    return max(0.0, min(score, 100.0))


def _score_payoff(text: str) -> float:
    text = text.strip()
    score = 30.0

    if text.endswith("."):
        score += 30
    elif text.endswith("?"):
        score += 25
    elif text.endswith("!"):
        score += 35
    elif text.endswith("...") or text.endswith("…"):
        score -= 20

    # Multiple sentences → more likely complete
    sentence_count = len(re.findall(r"[.!?]", text))
    score += min(sentence_count * 8, 30)

    return max(0.0, min(score, 100.0))


def _score_pacing(word_count: int, duration: float) -> float:
    if duration <= 0 or word_count == 0:
        return 30.0

    wps = word_count / duration  # words per second

    # Ideal range: 2–3 wps (natural conversational pace)
    if 2.0 <= wps <= 3.5:
        return 100.0
    if wps < 2.0:
        # Too slow / lots of silence
        return max(0.0, 100.0 - (2.0 - wps) * 40)
    # Too fast
    return max(0.0, 100.0 - (wps - 3.5) * 20)


def _score_duration(duration: float) -> float:
    """
    Score by YouTube Shorts duration sweet spot.
    Full marks (100) for 30–59 s.
    Scaled down linearly outside that range.
    Zero for anything outside the valid 15–59 s window.
    """
    if duration < MIN_DURATION or duration > MAX_DURATION:
        return 0.0
    if SWEET_RANGE_LO <= duration <= SWEET_RANGE_HI:
        return 100.0
    # 15–30 s: ramp up
    if duration < SWEET_RANGE_LO:
        return max(0.0, (duration - MIN_DURATION) / (SWEET_RANGE_LO - MIN_DURATION) * 100.0)
    return 100.0


# ---------------------------------------------------------------------------
# Selection: pick top-N with deduplication
# ---------------------------------------------------------------------------

def select_top(
    scored: list[dict],
    n: int,
    overlap_threshold: float = 0.5,
) -> list[dict]:
    """
    Sort candidates by score descending, pick top-N while avoiding
    clips that overlap > overlap_threshold with an already-selected clip.
    """
    sorted_candidates = sorted(scored, key=lambda c: c["score"], reverse=True)
    selected = []

    for c in sorted_candidates:
        if len(selected) >= n:
            break
        if not _overlaps_any(c, selected, overlap_threshold):
            selected.append(c)

    # Sort output chronologically for readability
    selected.sort(key=lambda c: c["start"])
    logger.info("Selected %d clips from %d scored candidates.", len(selected), len(scored))
    return selected


def _overlaps_any(
    candidate: dict, selected: list[dict], threshold: float
) -> bool:
    for s in selected:
        ratio = _overlap_ratio(
            candidate["start"], candidate["end"], s["start"], s["end"]
        )
        if ratio > threshold:
            return True
    return False


def _overlap_ratio(s1: float, e1: float, s2: float, e2: float) -> float:
    """Fraction of the shorter clip that overlaps with the longer."""
    overlap = max(0.0, min(e1, e2) - max(s1, s2))
    shorter = min(e1 - s1, e2 - s2)
    return overlap / shorter if shorter > 0 else 0.0
