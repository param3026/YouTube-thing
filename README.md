# YouTube Shorts Pipeline

> Fully automated, 100% local, zero-cost pipeline that turns any YouTube video (or local file) into upload-ready vertical Shorts with burned-in captions.

---

## What it does

Feed it a URL. Walk away. Come back to a folder of polished vertical clips.

```
Input  →  Download  →  Transcribe  →  Score  →  Crop & Render  →  Report
(URL)    (yt-dlp)    (Whisper)      (AI)     (FFmpeg 9:16)      (JSON+MD)
```

Every clip is:
- **1080 × 1920**, portrait 9:16, H.264 High / `yuv420p` — accepted by YouTube, TikTok, Instagram Reels without re-encoding
- **AAC stereo at 44 100 Hz** — platform-safe audio
- **30 fps** — matches the most common upload spec
- **15 – 59 seconds** — within the YouTube Shorts window; scoring prefers the 30–59 s range where the algorithm gives the most push
- **Captions burned in** — word-aligned, bold white text with black outline, safe-margin placement

---

## Features

| Feature | Detail |
|---------|--------|
| Download | `yt-dlp` — supports YouTube and thousands of other sites |
| Transcription | OpenAI Whisper (local, no API key) — word-level timestamps |
| Highlight scoring | Weighted rubric: hook strength, content interest, standalone context, payoff, pacing, duration fit |
| Duration targeting | Scoring sweet spot 30–59 s; target 45 s; hard cap 59 s |
| Caption rendering | Sentence-aware splitting, burned via libass / FFmpeg |
| Deduplication | Clips with > 50 % overlap are deduplicated |
| Caching | Downloaded video and transcript are cached — re-runs are fast |
| Fallback | Fixed 45 s windows when speech detection returns no segments |
| Validation | Every output is verified after render (resolution, streams, duration) |
| Reporting | `report.json` + `report.md` per batch |
| Dependency check | `python app.py doctor` |

---

## Requirements

| Tool | Install |
|------|---------|
| Python 3.9 + | [python.org](https://www.python.org/) |
| FFmpeg | [ffmpeg.org](https://ffmpeg.org/download.html) — or installed automatically via `imageio-ffmpeg` |
| yt-dlp | `pip install yt-dlp` |
| Whisper | `pip install openai-whisper` |

> **Note — Windows users:** FFmpeg does not need to be on your system PATH. The pipeline will automatically use the bundled binary from `imageio-ffmpeg` if the system FFmpeg is not found.

---

## Installation

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/youtube-shorts-pipeline.git
cd youtube-shorts-pipeline

# 2. Create a virtual environment (recommended)
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Verify everything is wired up
python app.py doctor
```

Expected `doctor` output:
```
=== Dependency Check ===
  Python 3.9+               [OK]
  ffmpeg / ffprobe          [OK]
  yt-dlp                    [OK]
  Whisper                   [OK]
  Ollama (optional)         [OK]

All required dependencies are present. Ready to run!
```

---

## Usage

### Process a YouTube video
```bash
python app.py process --url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" --clips 10
```

### Process a local file
```bash
python app.py process --file path/to/video.mp4 --clips 10
```

### All options
```
process
  --url URL           YouTube (or other) video URL
  --file PATH         Local video file path
  --clips N           Number of Shorts to produce  (default: 10)
  --output DIR        Output folder               (default: output)
  --model MODEL       Whisper model: tiny | base | small | medium | large
                      (default: base — use small for better accuracy)
  --language LANG     Transcription language code (default: en)
  --min-duration SEC  Minimum clip length in seconds (default: 15)
  --max-duration SEC  Maximum clip length in seconds (default: 59)
  --force-transcribe  Re-run Whisper even if transcript is cached
  --verbose / -v      Debug logging

doctor              Check all dependencies
clean-cache         Remove cached downloads and transcripts
```

### Recommended first run
```bash
python app.py process \
  --url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" \
  --clips 10 \
  --model small
```

`--model small` gives noticeably better caption accuracy on natural speech. The first run downloads the Whisper model weights (~240 MB) once and caches them.

---

## Output

```
output/
├── short_001.mp4      # 1080x1920, H.264, AAC, burned-in captions
├── short_001.srt      # Subtitle file (keep alongside the MP4)
├── short_002.mp4
├── short_002.srt
│   …
├── report.json        # Scores, timestamps, transcript excerpts, hashtags
├── report.md          # Human-readable summary — review before uploading
├── pipeline.log       # Full run log for debugging
└── cache/
    ├── downloaded_<id>.mp4       # Cached source video
    └── transcript_<id>.json      # Cached Whisper transcript
```

**Always review `report.md` before uploading.** It lists every clip's score, rationale, and a transcript excerpt so you can sanity-check content before it goes live.

---

## How the clip scoring works

Each candidate clip is scored 0 – 100 on six factors:

| Factor | Weight | What it measures |
|--------|--------|-----------------|
| Hook strength | **25 %** | Does the clip open with a question, bold claim, or attention word? |
| Content interest | **25 %** | Lexical richness, surprising language, facts, numbers |
| Standalone context | **20 %** | Makes sense without the surrounding video |
| Payoff / closure | **15 %** | Ends on a complete thought, punchline, or sentence |
| Pacing | **10 %** | ~2–3 words / second (natural conversational rate) |
| Duration fit | **5 %** | Full marks for 30–59 s; ramps from 15 s; zero outside 15–59 s |

The top-N clips are selected after deduplicating any pair that shares more than 50 % overlap. Timestamps are then snapped to the nearest Whisper sentence boundary with 0.5 s of padding.

---

## Module map

```
app.py                 CLI entry point (process / doctor / clean-cache)
pipeline.py            Orchestrator — runs all 7 steps, isolates per-clip errors
downloader.py          yt-dlp wrapper with URL validation and download caching
media_probe.py         ffmpeg -i metadata parser (resolution, fps, audio)
transcriber.py         Whisper API wrapper with JSON caching
clip_selector.py       Candidate generation, weighted scoring, dedup selection
timestamp_refiner.py   Snap clip boundaries to sentence edges + padding
caption_generator.py   Segments → SRT (sentence-aware word chunking)
editor.py              FFmpeg render: crop 9:16, burn captions, H.264/AAC encode
metadata_generator.py  report.json + report.md writer
setup_env.py           Resolves bundled FFmpeg binary and injects into PATH
```

---

## Platform notes

- **Windows:** The bundled `imageio-ffmpeg` binary is used automatically. No system FFmpeg install required.
- **macOS / Linux:** Install FFmpeg via your package manager (`brew install ffmpeg` / `apt install ffmpeg`).
- **GPU acceleration:** Whisper will use CUDA automatically if a compatible GPU and PyTorch-CUDA are installed. CPU-only is fully supported.
- **Ollama (optional):** If Ollama is running locally with a model loaded, it can be wired in to the scoring step for LLM-assisted ranking. Not required.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `yt-dlp` fails on a URL | Update yt-dlp: `pip install -U yt-dlp` |
| Whisper is slow | Use `--model tiny` for speed or `--model small` for quality |
| Empty captions in output | Video may have no speech — fixed-window fallback is used |
| `ffmpeg` not found | Run `python app.py doctor` — the pipeline will locate the bundled binary |
| Clip durations are wrong | The source video may be shorter than `--min-duration`; lower the value |

---

## Contributing

Pull requests welcome. Please open an issue first for any substantial change.

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-improvement`
3. Commit your changes
4. Push and open a Pull Request

---

## License

MIT — do whatever you want, just don't remove the license header.

---

*Built with [yt-dlp](https://github.com/yt-dlp/yt-dlp), [OpenAI Whisper](https://github.com/openai/whisper), and [FFmpeg](https://ffmpeg.org).*
