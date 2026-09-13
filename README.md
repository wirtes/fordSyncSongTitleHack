# Ford SYNC Song Title Hack

Ford SYNC can play music from a USB drive in alphabetical **title-tag** order instead of album track order. Renaming files to `01 Song.mp3`, `02 Song.mp3`, and so on does not fix that behavior because SYNC ignores the filenames when deciding what comes next.

`fordHack.py` works around the problem by putting each track number at the beginning of the song's embedded title:

```text
Before:  title = London Calling    tracknumber = 1
After:   title = 01 - London Calling
```

The result is ugly metadata made necessary by uglier playback software, but it makes albums play in the intended order.

## Read this before running it

> **This script makes destructive, irreversible changes. Run it only on a USB copy of your library—never on your master music collection.**

- MP3 audio is not re-encoded, but its title and comment metadata may be rewritten.
- M4A files are converted to MP3. After the converted file is verified, the original M4A is deleted.
- There is no undo command and no built-in backup.
- The script has no preview or dry-run mode.
- A file that fails is reported and left for you to inspect; processing continues with the remaining files.

Keep an untouched copy somewhere other than the USB drive.

## What the script does

The configured music directory is scanned recursively. Hidden files and directories—names beginning with `.`—are ignored. File extensions are matched without regard to case.

| Input | Result |
| --- | --- |
| Unprocessed `.mp3` | Prefixes the title tag with a two-digit track number and adds the processed marker. The audio stream is untouched. |
| Unprocessed `.m4a` | Converts it to a 192 kbps, 44.1 kHz, stereo MP3; updates the title; verifies the result; installs the `.mp3`; then deletes the `.m4a`. |
| MP3 already marked `Ford Sync REALLY Sucks` | Skips it, preventing another title prefix. |
| MP3 marked by the older script with `Ford Sync Sucks` | Updates only the marker. It does not alter the title again or re-encode the audio. |
| M4A marked by the older script | Converts it to MP3 without adding a duplicate track-number prefix. |

Successfully processed files receive this comment tag:

```text
Ford Sync REALLY Sucks
```

That marker makes repeat runs safe for already-processed MP3 files. It also lets you add new music to the USB drive later and run the script again: old MP3s are skipped and new tracks are processed.

## Requirements

- Python 3
- [`music-tag`](https://pypi.org/project/music-tag/)
- [`ffmpeg`](https://ffmpeg.org/) and `ffprobe` available on your `PATH`
- Music files with non-empty `title` and `tracknumber` metadata

The track number must be readable as an integer. Values such as `1`, `2`, and `12` work. If a tagging application stores a value such as `1/10`, normalize it to `1` before running the script.

## Installation

Clone or download this repository, then open a terminal in its directory.

### macOS

Install FFmpeg with [Homebrew](https://brew.sh/), create a virtual environment, and install the Python dependency:

```bash
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install music-tag
```

### Debian or Ubuntu

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-venv
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install music-tag
```

You can confirm that all three runtime dependencies are available with:

```bash
python3 -c "import music_tag; print('music-tag is available')"
ffmpeg -version
ffprobe -version
```

## How to use it

### 1. Prepare a disposable USB copy

Copy music to the USB drive and make sure the copy is complete. A layout such as this is fine:

```text
CAR-TUNES/
└── Albums/
    ├── The Clash/
    │   └── London Calling/
    │       ├── 01 London Calling.m4a
    │       └── 02 Brand New Cadillac.m4a
    └── Talking Heads/
        └── Remain in Light/
            ├── 01 Born Under Punches.mp3
            └── 02 Crosseyed and Painless.mp3
```

Filenames and nesting do not determine playback order. The embedded `title` and `tracknumber` tags do.

### 2. Point the script at the music directory

Open `fordHack.py` and edit `directory_path` near the bottom of `main()`:

```python
def main():
    directory_path = Path("/Volumes/CAR-TUNES/Albums")
```

Examples for other mount locations:

```python
# Another macOS USB volume
directory_path = Path("/Volumes/MY MUSIC/Music")

# Typical Linux mount point
directory_path = Path("/media/alex/CAR-TUNES/Albums")

# Windows drive (use a raw string)
directory_path = Path(r"E:\Albums")
```

Point to the narrowest directory that contains the music you want changed. The script processes every supported file beneath it.

### 3. Run the script

With the virtual environment active:

```bash
python3 fordHack.py
```

The script prints the detected USB volume and exact directory before touching any files:

```text
USB drive: /Volumes/CAR-TUNES
Music directory: /Volumes/CAR-TUNES/Albums
WARNING: This will make major, irreversible changes to the music files on this USB drive...
Type YES to continue:
```

Review both paths carefully. Type exactly `YES` to continue. Any other response, or pressing `Ctrl-C`, cancels the run without processing files.

### 4. Review the results

A successful run resembles:

```text
Updated metadata for /Volumes/CAR-TUNES/Albums/Talking Heads/Remain in Light/01 Born Under Punches.mp3
Converted audio and updated metadata for /Volumes/CAR-TUNES/Albums/The Clash/London Calling/01 London Calling.mp3
Finished: 2 updated, 14 already processed, 0 failed.
```

The exit status is `0` when every file succeeds and `1` when the run is cancelled, setup is invalid, or one or more tracks fail. Before ejecting the drive, spot-check a few albums in a tag editor or music player and confirm that their titles begin with the expected track numbers.

## Worked examples

### Existing MP3

Given this file:

```text
File:        Born Under Punches.mp3
title:       Born Under Punches (The Heat Goes On)
tracknumber: 1
comment:
```

After processing:

```text
File:        Born Under Punches.mp3
title:       01 - Born Under Punches (The Heat Goes On)
tracknumber: 1
comment:     Ford Sync REALLY Sucks
audio:       unchanged
```

### M4A conversion

Given `London Calling.m4a` with title `London Calling` and track number `1`, the script creates and verifies `London Calling.mp3`. The new file has this metadata and audio format:

```text
title:       01 - London Calling
tracknumber: 1
comment:     Ford Sync REALLY Sucks
codec:       MP3 (MPEG Layer III)
bit rate:    192 kbps
sample rate: 44.1 kHz
channels:    2 (stereo)
ID3:         v2.3, with an ID3v1 tag also written
```

Only after conversion, tagging, and verification succeed does the script remove `London Calling.m4a`.

### Adding music later

Suppose the drive contains 200 marked MP3 files and you add a new 10-track album. Run the script again. The 200 marked tracks are skipped, while the 10 new files receive their prefixes and markers. The old titles do not become values such as `01 - 01 - Song Name`.

### Destination-name collision

If a directory contains both `Song.m4a` and `Song.mp3`, the script will not overwrite the existing MP3. It reports an error similar to:

```text
Failed to update /Volumes/CAR-TUNES/Albums/Song.m4a: cannot replace Song.m4a: Song.mp3 already exists
```

Rename or remove the duplicate on your disposable USB copy, verify which file you want to keep, and run the script again.

## Troubleshooting

### `No module named 'music_tag'`

Activate the virtual environment and install the package using the same Python interpreter that runs the script:

```bash
source .venv/bin/activate
python3 -m pip install music-tag
python3 fordHack.py
```

### `ffmpeg and ffprobe are required`

Install FFmpeg and ensure both commands are on `PATH`. `ffprobe` is normally included with FFmpeg.

### `title metadata is missing` or `tracknumber metadata is missing`

Open the affected file in a tag editor, fill in both fields, and rerun the script. The failed file is not marked complete.

### `invalid literal for int()`

The track-number tag is not a plain integer. Change a value such as `3/12` or `Track 3` to `3`, then rerun the script.

### An album still plays in the wrong order

Check the title tags on the USB files—not just their filenames. Confirm that they begin with `01 -`, `02 -`, and so on, and that disc-two numbering follows the order you actually want. This script uses only the track number; it does not combine disc number and track number.

## Implementation and safety details

- Directories and files are processed in sorted order, although playback order is determined by the rewritten tags.
- Progress is printed every 50 supported tracks checked.
- MP3 comment variants are consolidated into one standard processed marker.
- M4A conversion is written to a temporary file in the same directory.
- `ffprobe` verifies that the temporary output contains MP3 audio at 44.1 kHz in stereo.
- The converted metadata and processed marker are reopened and verified before replacement.
- Temporary conversion files are cleaned up after success or failure.
- One bad track does not stop the rest of the drive from being processed; the final summary reports all failures.

## A personal note to Ford

USB file support in this version of SYNC feels less like a feature and more like an afterthought somebody remembered during the walk to the shipping meeting. Ignoring track order encoded in filenames, sorting an album by title metadata, and forcing owners to vandalize their music tags just to hear track two after track one is astonishingly careless. This is not an obscure edge case: playing an album in order is the baseline behavior of a music player.

The lack of thought is matched by the lack of engineering. A tiny amount of competent design, testing with one ordinary album, or even five minutes spent asking how people organize music on USB drives would have exposed this mess. Instead, Ford shipped software that makes a basic storage device behave unpredictably and pushed the cleanup onto its customers. A high school intern working after school could have done a better job—and probably would have had enough pride in the result to test whether an album actually played from beginning to end.
