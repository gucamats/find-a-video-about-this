# broll-finder

Give it a theme and it finds videos you might cut b-roll from. It searches
YouTube, downloads the results, transcribes them, picks the moments worth
looking at and saves labeled frames as 3x3 grids. Everything for one request
ends up in one folder, with a `report.md` that lists every video.

The tool does the mechanical part only. It does not judge whether a video
fits the theme, and it calls no AI API. That judgment belongs to whoever
reads the grids. In practice that's Claude: it opens the grid images,
describes each frame and fills in the empty fields in `frames.json`.

It runs on the CPU with Python, `yt-dlp`, `faster-whisper` and `ffmpeg`. No
API key needed.

## Requirements

- Python. Tested only on 3.13, Windows 11.
- `ffmpeg` and `ffprobe` on the PATH. Tested with 9.0.2.

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows
.venv/bin/python -m pip install -r requirements.txt         # Linux/macOS
```

`av` is pinned at 18.1.0 because 19.x breaks transcription. Don't run
`pip install -U -r requirements.txt`. To refresh `yt-dlp` when a site
changes, run `pip install -U yt-dlp`, which leaves `av` alone.

The first transcription downloads the whisper model.

## Usage

Run the commands from this folder. By default, request folders go into
`./output/`, which git ignores. Use `--out DIR` (before the command) to put
them somewhere else.

### The whole flow

```
python -m broll_finder run "quebra de sigilo de Lula e Flávio" -n 3
```

This searches YouTube for the theme and takes the top 3 results through
download, transcription and frames. It prints the path of `report.md`.
Useful options:

- `--query "..."` uses a different search query from the theme.
- `--terms a,b` sets the keywords looked for in the speech. By default they
  are the theme's words of 3 or more letters, minus common stopwords.
- `--mode auto|speech|cuts|interval` and `--max-frames 36` control frame
  selection (see below).
- `--model small`, `--language pt` and `--no-subs` control transcription.

When one video fails, the error goes into the report and the next video still
runs.

### Step by step

```
python -m broll_finder search "tipografia cinética" -n 10 [--full]
python -m broll_finder download URL [URL ...] [--request NAME] [--max-height 720]
python -m broll_finder clip URL --start 1:05 --end 1:20 [--keyframes]
python -m broll_finder transcribe output/<request>/<video-id>
python -m broll_finder frames output/<request>/<video-id> --theme "..."
```

- `search` prints JSON with `id`, `url`, `channel`, `duration`,
  `upload_date`, `title` and `source`. The fast mode has no upload date
  (`null`), because YouTube's search list doesn't carry one. `--full` opens
  each video page to get it, at about 2 s per result.
- `download` saves up to 720p for analysis: landscape by height, vertical
  video by width. A format whose resolution the site doesn't report is
  accepted as a last resort, but a known resolution above 720p never is.
  The result is always remuxed to `video.mp4`. It also saves
  `video.info.json`, then checks that
  the file exists and that its ffprobe duration is within 2 s of what the
  platform reported. A link that fails becomes `{"status": "error",
  "error": "<reason>"}` and the other links still download.
- `clip` downloads only `start`-`end` at maximum quality, as
  `clip_<start>-<end>.mp4`, with start and end rounded to whole seconds in
  the name, so two clips that differ by less than a second overwrite each
  other. The duration check uses the requested range.
  `--keyframes` re-encodes around the cut points for exact edges, which is
  slower.
- `transcribe` writes `transcript.json` next to the video.
- `frames` writes `frames/`, `grids/` and `frames.json` next to the video.

The `--accept-language pt-BR` default (given before the command) also sets
YouTube's `lang=pt`. Without both, YouTube returned machine-translated English
titles. The flip side: a video in another language may get a Portuguese
machine-translated title.

## Output

```
output/2026-10-23_190017-quebra-de-sigilo-de-lula-e-flavio/
  report.md, report.json          the list: one entry per video
  KsIN1yYS4NI/
    video.mp4, video.info.json
    transcript.json
    frames/frame_001.jpg ...      640 px wide, MM:SS drawn top-left
    grids/grid_01.jpg ...         3x3 tiles of the frames
    frames.json
```

For each video, `report.md` has its status, timings, the duration check, a
transcript summary, the speech segments that mention the theme (with
`MM:SS`), how the frames were chosen and why, the grid paths and any errors.

In `frames.json`, every frame has `time`, `mmss`, `path` and `grid`, plus
three fields left for the reviewer to fill: `on_screen_text`, `description`
and `shows_theme` (`null` until filled).

## How it decides

### Transcription

1. On YouTube it first tries uploaded subtitles (`pt-BR`, then `pt`;
   `--sub-langs` on `transcribe`). It ignores auto-generated captions. Any
   failure, such as no subtitles or `HTTP Error 429`, falls back to local
   transcription, and the reason is saved as `subtitle_error`. `--no-subs`
   skips this step.
2. Local transcription uses faster-whisper on the CPU (`int8`), with
   `language=pt` and the `small` model by default.
3. Segments with `no_speech_prob > 0.5` are dropped and kept under `dropped`
   with the reason. On a music-only video, whisper invented "1, 2, 3..." with
   `no_speech_prob` 0.60 and 0.67.
4. Kept segments get flags but stay in the transcript: `repeated` when the
   same normalized text appears in consecutive segments, `high_compression_ratio`
   above 2.4, and `low_avg_logprob` below -1.0.

`transcript.json` also records the source, the model, the language and
elapsed times (subtitle attempt, model load, transcription).

### Frame moments

Scene cuts come from `ffmpeg scdet` (threshold 10). On ffmpeg 9.0.2,
`select=gt(scene,0.3)` returned no frames at all. Cuts closer than 0.5 s are
merged into one.

Frames at theme mentions come first, in every mode: one every 2 s inside
each transcript segment that matches a theme term. The mode then adds its
own frames on top:

| Mode | When `auto` picks it | Frames added |
|---|---|---|
| `cuts` | 15 or more cuts per minute (motion design, fast edits) | the opening shot, then 0.3 s after each cut |
| `speech` | otherwise, if speech covers 30 %+ of the video and mentions a theme term | cuts inside the matching segments |
| `interval` | everything else | every 2 s across the video |

So a fast-edited news package that speaks the theme gets frames at every
cut *and* at every mention. Frames added by the mode are skipped when they
fall within 1 s of a theme-mention frame.

Term matching is a plain whole-word match that ignores case and accents.
Deciding whether a frame really shows the theme is the reviewer's job. The
cap is `--max-frames` (36 by default). Theme-mention frames are kept first,
and the remaining slots go to an evenly spread subset of the mode's frames.

These thresholds come from a handful of videos (a news clip with 0.3-0.7
cuts per minute, motion-design clips with 34-55, a lyric video with 1.3) and
have not been calibrated beyond them.

## Sources tested (23/10/2026, yt-dlp 2026.10.21)

| Source | Result |
|---|---|
| YouTube | Works: search, download, clip, uploaded subtitles. Video comes as AV1, which ffmpeg decodes. |
| TikTok | Works with `curl_cffi` installed. Without it: "Unexpected response from webpage request". |
| g1 (g1.globo.com article with a video) | Works through yt-dlp's Globo extractor. |
| CNN Brasil (article pages) | **Fails**: "Unsupported URL". The generic extractor finds no video. |
| UOL (mais.uol.com.br/view/...) | **Fails**: metadata resolves, but the download dies with "Failed to parse JSON". |
| Tribuna do Norte | The page tested had no embedded video. |

## Limits

- Search covers YouTube only. TikTok and news sites work only as direct links
  to `download`.
- `run` doesn't filter by duration. Transcribing a 6-minute video took 107 s
  on the test machine (about 3.5x real time), so a 1-hour result takes
  around 18 minutes.
- Two frames in the same second get the same `MM:SS` label. The exact time
  is in `frames.json`.
- Without a JavaScript runtime (Deno), yt-dlp warns that some YouTube formats
  may be missing. Downloads worked anyway in the tests.
- The timestamp font is the first one found among Arial Bold (Windows/macOS)
  and DejaVu Sans Bold (Linux). Pass `--font` to use another. With none
  found, ffmpeg falls back to fontconfig. That fallback was not tested.

## Tests

```
python -m pip install pytest
python -m pytest
```

The tests cover the pure logic: search-output parsing, the duration check,
time parsing, segment filtering and flags, keyword matching, VTT parsing,
cut parsing and merging, mode choice, moment selection and drawtext
escaping. With yt-dlp and whisper replaced by fakes (no network), they also
cover the subtitle-to-whisper fallback, a failing link not stopping the
next, the duration-mismatch error, and one video's failure not stopping
`run`. Real network and ffmpeg calls are checked by hand only.

## License

MIT, see `LICENSE`.
