# Project History

A full, honest record of how this project was built — every decision, every bug, every fix — in chronological order.

---

## Session — October 2026

### Starting point: the master prompt

The project began from a detailed master prompt specifying a fully automated YouTube-to-Shorts pipeline. Requirements included:

- `yt-dlp` for downloading
- OpenAI Whisper for local transcription
- A weighted scoring rubric (hook, content, context, payoff, pacing, duration)
- FFmpeg for all video editing — crop to 9:16, burned-in captions, H.264/AAC output
- A clean CLI (`python app.py process --url ... --clips 10`)
- Caching so re-runs on the same video skip expensive steps
- Per-clip error isolation (one bad clip must not abort the whole job)
- A `report.json` and `report.md` per batch

---

### Phase 1: Initial build

All ten modules were written from scratch in one pass:

| Module | Purpose |
|--------|---------|
| `app.py` | CLI — `process`, `doctor`, `clean-cache` |
| `pipeline.py` | Orchestrator — 7-step sequence |
| `downloader.py` | yt-dlp wrapper, URL validation, caching |
| `media_probe.py` | ffprobe / ffmpeg -i metadata extraction |
| `transcriber.py` | Whisper Python API + CLI fallback |
| `clip_selector.py` | Candidate generation, weighted scoring, dedup |
| `timestamp_refiner.py` | Snap timestamps to Whisper sentence boundaries |
| `caption_generator.py` | Segments → SRT subtitle file |
| `editor.py` | FFmpeg render pipeline |
| `metadata_generator.py` | report.json + report.md |

The scoring rubric weights were set from the master prompt:
- Hook strength 25 %, Content interest 25 %, Standalone context 20 %,  
  Payoff 15 %, Pacing 10 %, Duration fit 5 %

---

### Phase 2: First test — dependency check

**Problem:** Running `python app.py doctor` crashed immediately with a `UnicodeEncodeError`.

**Root cause:** The `doctor` command used `✅` and `❌` emoji in `print()` calls. Windows terminal defaults to the `cp1252` codepage, which cannot encode those characters.

**Fix:** Replaced emoji with plain ASCII `[OK]` and `[MISSING]` strings. Same fix applied to `report.md` generation which also used emoji status indicators.

---

### Phase 3: Missing dependencies

Running `doctor` revealed:

```
ffmpeg / ffprobe    [MISSING]
yt-dlp             [MISSING]
Whisper            [MISSING]
```

**yt-dlp and Whisper:** Installed via `pip install yt-dlp openai-whisper`. Torch and numba were pulled in as transitive dependencies.

**FFmpeg:** No system FFmpeg was present, and neither `winget` nor `choco` was available. Solution: install `imageio-ffmpeg` via pip, which bundles a static FFmpeg build for Windows.

**New problem:** The bundled binary is named `ffmpeg-win-x86_64-v7.1.exe`, not `ffmpeg.exe`. Subprocess calls like `subprocess.run(["ffmpeg", ...])` could not find it through PATH.

**Fix:** Created `setup_env.py`. On startup it:
1. Locates the bundled binary via `imageio_ffmpeg.get_ffmpeg_exe()`
2. Creates `ffmpeg.exe` and `ffprobe.exe` copies in the same directory
3. Prepends that directory to `os.environ["PATH"]`

All modules now import `setup_env` at the top so the binary is available before any subprocess call.

After this, `doctor` showed all required dependencies as `[OK]`.

---

### Phase 4: First pipeline run

Ran against a 90-second synthetic test video (FFmpeg colour bars + sine tone, no speech).

**Problem 1 — Transcription crash:**  
`[WinError 2] The system cannot find the file specified` inside the Whisper Python API.

**Root cause:** Whisper internally calls `ffmpeg` to decode audio from the video file, but at that point PATH had not yet been updated. `transcriber.py` imported before `setup_env` ran.

**Fix:** Added `import setup_env; setup_env.ensure_ffmpeg()` at the top of `transcriber.py`.

**Problem 2 — FFmpeg subtitle filter crash:**  
After fixing Whisper, the pipeline progressed to rendering but all three clips failed with:

```
[Parsed_subtitles] Unable to open .../short_001.srt
Error opening output files: Invalid data found when processing input
```

**Root cause:** The test video has no speech, so Whisper returned zero segments. `caption_generator` wrote empty SRT files (0 bytes). libass (FFmpeg's subtitle renderer) refuses to open an empty SRT file.

**Fix:** `editor.py` now checks `_srt_has_content()` before building the subtitle filter. If the SRT file is empty or absent, the subtitle filter is omitted entirely and the clip renders without captions.

After both fixes, 3/3 clips rendered successfully.

---

### Phase 5: Caption quality test

To test actual caption rendering, a speech video was generated using Windows TTS (PowerShell `System.Speech.Synthesis.SpeechSynthesizer`) with 12 spoken sentences, then combined with a test-pattern video via FFmpeg.

**Observation 1 — Captions split mid-sentence:**  
The first `caption_generator` implementation chunked at a fixed 8-word boundary regardless of sentence endings, producing blocks like *"into perfect short clips automatically. That is exactly"* — a sentence boundary in the middle of a caption block.

**Fix:** Rewrote `_word_level_blocks()` to check for sentence-ending punctuation (`.!?`) after each word. When a sentence ending is found within the 7-word window, the block closes there instead of at the hard limit.

**Observation 2 — Font size:**  
`FontSize=20` at 1080×1920 resolution produced very large text (three lines filling the lower third). Reduced to `FontSize=15` with `Bold=1` — maintains strong readability at Shorts viewing size while fitting two clean lines.

Both fixes were verified by extracting frames at multiple timestamps. Caption text was confirmed readable, sentence-aligned, and within safe margins.

---

### Phase 6: QA audit — critical encoding bugs found

A deep quality audit of the output MP4 files revealed two critical issues:

**Bug 1 — Wrong pixel format: `yuv444p` instead of `yuv420p`**

The synthetic test source (FFmpeg `testsrc`) outputs `yuv444p` by default, and without an explicit pixel format flag in the render command, FFmpeg carried that format through. YouTube, TikTok, and Instagram all require `yuv420p`. Uploading `yuv444p` video either causes rejection or forces a costly server-side re-encode that degrades quality.

**Fix:** Added `-pix_fmt yuv420p` to the FFmpeg render command in `editor.py`.

**Bug 2 — Wrong H.264 profile: `High 4:4:4 Predictive`**

As a consequence of the same issue, FFmpeg selected the `High 4:4:4 Predictive` H.264 profile (required for `yuv444p`). This profile is not supported by many mobile decoders and is incompatible with platform upload requirements.

**Fix:** Added `-profile:v high -level 4.0` to force the standard `High` profile — the correct choice for `yuv420p` at 1080p.

**Bug 3 — Audio sample rate: 22 050 Hz instead of 44 100 Hz**

The Windows TTS output was 22 050 Hz mono. Without an explicit resample flag, FFmpeg passed that sample rate through. Most platforms expect 44 100 Hz.

**Fix:** Added `-ar 44100` to the render command. FFmpeg resamples to 44 100 Hz on every render regardless of source sample rate.

After these three fixes the audit showed:

```
Pixel format yuv420p   PASS
H.264 High profile     PASS
Audio 44100 Hz         PASS
```

---

### Phase 7: Duration algorithm update

**Original settings:** `TARGET_DURATION = 30.0 s`, `MAX_DURATION = 60.0 s`

**Research finding:** YouTube Shorts are capped at 60 seconds. However, the algorithm rewards *watch-time signal* — the ratio of seconds watched to total length. A 45-second clip where the viewer watches all 45 seconds sends a stronger signal than a 30-second clip watched fully, because total watch time is higher. Creator data consistently shows that Shorts in the 30–59 second range outperform shorter clips in algorithmic distribution.

**Changes made:**

| Setting | Before | After |
|---------|--------|-------|
| `MIN_DURATION` | 15 s | 15 s (unchanged) |
| `TARGET_DURATION` | 30 s | 45 s |
| `MAX_DURATION` | 60 s | 59 s (just under hard cap) |
| Duration scoring | Full marks at 30 s | Full marks for entire 30–59 s range |
| Fixed-window fallback | 30 s windows, 20 s step | 45 s windows, 50 % overlap |
| CLI default `--max-duration` | 60 | 59 |

Duration is only 5 % of the total score — it is a preference, not a constraint. A genuinely great 20-second clip still outscores a mediocre 45-second clip on overall content merit.

---

### Phase 8: Pre-release verification — honest audit

A final verification pass was requested with three specific concerns:

**Concern 1 — Synthetic video test had failed.**  
The original synthetic video command used comma-chained lavfi sources:
```
-i 'sine=f=300:d=2,aevalsrc=0:d=0.5,sine=f=440:d=3,...'
```
FFmpeg does not accept multiple sources chained this way in a single `-i` argument. Error: `Missing 0 outpad name`.

**Fix (test only, no pipeline code changed):** Use a single continuous source:
```
-i 'sine=frequency=440:duration=90'
```
Synthetic video then generated correctly (2.9 MB, verified).

**Concern 2 — ffprobe was actually ffmpeg.**  
The `ffprobe.exe` file created by `setup_env.py` is a byte-for-byte copy of `ffmpeg.exe` (confirmed by MD5 comparison). It does not support ffprobe's `-print_format json -show_streams` flags — those calls fail silently and return no output.

All metadata extraction in `media_probe.py` uses `ffmpeg -i` stderr parsing. This was relabelled accurately everywhere. It is not a pipeline bug — the parsing is reliable and has passed all verification runs. A future improvement would be to download a full FFmpeg+ffprobe static build that includes a genuine ffprobe binary.

**Concern 3 — 45 s must be a preference, not a forced duration.**  
Verified in `clip_selector.py`: duration contributes only 5 % of the total score. The timestamp refiner clips to 59 s maximum but never pads below natural length. A 20-second clip with a great hook and strong payoff will be selected ahead of a boring 45-second clip.

Both pipeline paths were re-run fresh:
- **Synthetic path** (no speech → fixed-window fallback): 3/3 clips, 33 checks passed
- **Speech path** (TTS audio → Whisper transcript → scored candidates): 2/2 clips, 22 checks passed
- Visual frame inspection confirmed portrait framing, caption rendering, and safe margins on all fresh renders.

---

## Known limitations at release

| Limitation | Notes |
|------------|-------|
| No genuine `ffprobe` binary | `setup_env.py` copies `ffmpeg.exe` as `ffprobe.exe`. Metadata is parsed from `ffmpeg -i` stderr — works correctly but is less structured than native ffprobe JSON. |
| Whisper mishears technical terms | `ffmpeg` → `"F beg"`, `yt-dlp` → `"YTDLP"`. Use `--model small` or `--model medium` for better accuracy on real speech. |
| No GPU detected in test environment | Whisper runs on CPU only. Add a CUDA-capable GPU + PyTorch-CUDA for 10× faster transcription. |
| Single-speaker assumption | The cropping always centre-crops the frame. Face detection for speaker tracking is listed as an optional future enhancement in the master prompt. |
| No real YouTube download tested | All tests used local files. The download path (`yt-dlp`) is standard and well-tested upstream, but it was not exercised in this session due to the environment setup. |

---

## Files in this repository

```
app.py                 CLI
pipeline.py            Orchestrator
downloader.py          yt-dlp wrapper
media_probe.py         ffmpeg -i metadata parser
transcriber.py         Whisper wrapper
clip_selector.py       Scoring engine
timestamp_refiner.py   Boundary snapping
caption_generator.py   SRT generator
editor.py              FFmpeg renderer
metadata_generator.py  Report writer
setup_env.py           FFmpeg PATH resolver
requirements.txt       Python dependencies
README.md              User documentation
HISTORY.md             This file
.gitignore             Excludes output, cache, test files, model weights
```
