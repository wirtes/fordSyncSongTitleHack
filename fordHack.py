#!/Library/Frameworks/Python.framework/Versions/3.10/bin/python3

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from music_tag import load_file


PROCESSED_COMMENT = "Ford Sync REALLY Sucks"
LEGACY_COMMENT = "Ford Sync Sucks"
SUPPORTED_EXTENSIONS = {".mp3", ".m4a"}


def tag_value(audio, key):
    """Return a music_tag value as plain text."""
    return str(audio[key]).strip()


def mp3_comment_values(audio):
    """Read standard ID3 comments and comment-like custom ID3 fields."""
    values = {tag_value(audio, "comment")}
    tags = getattr(getattr(audio, "mfile", None), "tags", None)
    if tags:
        for frame in tags.values():
            frame_id = getattr(frame, "FrameID", "")
            description = str(getattr(frame, "desc", "")).casefold()
            if frame_id == "COMM" or (
                frame_id == "TXXX" and description == "comment"
            ):
                values.update(str(value).strip() for value in frame.text)
    values.discard("")
    return values


def set_mp3_comment(audio, comment):
    """Replace every ID3 representation of the comment with one value."""
    tags = getattr(getattr(audio, "mfile", None), "tags", None)
    if tags:
        tags.delall("COMM")
        for key, frame in list(tags.items()):
            if (
                getattr(frame, "FrameID", "") == "TXXX"
                and str(getattr(frame, "desc", "")).casefold() == "comment"
            ):
                del tags[key]
    audio["comment"] = comment


def ford_title(title, track_number, previous_comment):
    """Prefix a title once, including when converting a legacy-marked M4A."""
    track = int(track_number)
    prefix = f"{track:02d} - "

    # Files handled by the old version already have this prefix. Its old marker
    # is not enough to skip them now because they still need audio conversion.
    if previous_comment == LEGACY_COMMENT and title.startswith(prefix):
        return title

    return f"{prefix}{title}"


def run_ffmpeg(source, destination):
    """Create a conservative, broadly compatible Ford SYNC MP3."""
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-map_metadata",
        "0",
        "-metadata",
        "comment=",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-id3v2_version",
        "3",
        "-write_id3v1",
        "1",
        "-f",
        "mp3",
        str(destination),
    ]
    subprocess.run(command, check=True)


def verify_mp3(file_path):
    """Fail before replacement if ffmpeg did not produce the requested audio."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            str(file_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise RuntimeError("converted file has no audio stream")

    stream = streams[0]
    actual = (
        stream.get("codec_name"),
        str(stream.get("sample_rate")),
        int(stream.get("channels", 0)),
    )
    if actual != ("mp3", "44100", 2):
        raise RuntimeError(
            "converted audio is not MP3, 44.1 kHz, stereo "
            f"(ffprobe reported {actual})"
        )


def update_mp3_metadata(file_path):
    """Update an existing MP3 without re-encoding its audio."""
    audio = load_file(file_path)
    comments = mp3_comment_values(audio)
    if PROCESSED_COMMENT in comments:
        return "skipped", file_path

    # The previous script already updated the title on legacy-marked MP3s.
    # Change only their marker, exactly as promised, and leave the audio alone.
    if LEGACY_COMMENT in comments:
        set_mp3_comment(audio, PROCESSED_COMMENT)
        audio.save()
        if mp3_comment_values(load_file(file_path)) != {PROCESSED_COMMENT}:
            raise RuntimeError("processed comment could not be verified")
        return "metadata", file_path

    title = tag_value(audio, "title")
    track_number = tag_value(audio, "tracknumber")
    if not title:
        raise ValueError("title metadata is missing")
    if not track_number:
        raise ValueError("tracknumber metadata is missing")

    expected_title = ford_title(title, track_number, "")
    audio["title"] = expected_title
    set_mp3_comment(audio, PROCESSED_COMMENT)
    audio.save()

    verified_audio = load_file(file_path)
    if tag_value(verified_audio, "title") != expected_title:
        raise RuntimeError("updated title could not be verified")
    if mp3_comment_values(verified_audio) != {PROCESSED_COMMENT}:
        raise RuntimeError("processed comment could not be verified")
    return "metadata", file_path


def convert_and_update(file_path):
    """Convert one non-MP3 track and atomically install the finished MP3."""
    original_audio = load_file(file_path)
    previous_comment = tag_value(original_audio, "comment")

    title = tag_value(original_audio, "title")
    track_number = tag_value(original_audio, "tracknumber")
    if not title:
        raise ValueError("title metadata is missing")
    if not track_number:
        raise ValueError("tracknumber metadata is missing")

    destination = file_path.with_suffix(".mp3")
    if destination != file_path and destination.exists():
        raise FileExistsError(
            f"cannot replace {file_path.name}: {destination.name} already exists"
        )

    temporary = file_path.with_name(f".{file_path.stem}.ford-sync.tmp.mp3")
    try:
        run_ffmpeg(file_path, temporary)

        expected_title = ford_title(title, track_number, previous_comment)
        converted_audio = load_file(temporary)
        converted_audio["title"] = expected_title
        set_mp3_comment(converted_audio, PROCESSED_COMMENT)
        converted_audio.save()

        verify_mp3(temporary)
        verified_audio = load_file(temporary)
        if tag_value(verified_audio, "title") != expected_title:
            raise RuntimeError("updated title could not be verified")
        if mp3_comment_values(verified_audio) != {PROCESSED_COMMENT}:
            raise RuntimeError("processed comment could not be verified")

        os.replace(temporary, destination)
        if destination != file_path:
            file_path.unlink()
        return "converted", destination
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def update_music(directory):
    tracks_seen = 0
    tracks_updated = 0
    tracks_skipped = 0
    tracks_failed = 0

    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        files = sorted(f for f in files if not f.startswith("."))

        for filename in files:
            file_path = Path(root, filename)
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            tracks_seen += 1
            if tracks_seen % 50 == 0:
                print(f"Checked {tracks_seen} tracks")

            try:
                if file_path.suffix.lower() == ".mp3":
                    status, result_path = update_mp3_metadata(file_path)
                else:
                    status, result_path = convert_and_update(file_path)

                if status == "skipped":
                    tracks_skipped += 1
                elif status == "converted":
                    tracks_updated += 1
                    print(f"Converted audio and updated metadata for {result_path}")
                else:
                    tracks_updated += 1
                    print(f"Updated metadata for {result_path}")
            except Exception as error:
                tracks_failed += 1
                print(f"Failed to update {file_path}: {error}", file=sys.stderr)

    print(
        "Finished: "
        f"{tracks_updated} updated, {tracks_skipped} already processed, "
        f"{tracks_failed} failed."
    )
    return tracks_failed == 0


def usb_drive_for(directory):
    """Show the volume root when the configured directory is on macOS /Volumes."""
    directory = directory.expanduser().absolute()
    try:
        relative = directory.relative_to("/Volumes")
    except ValueError:
        return directory
    return Path("/Volumes", relative.parts[0]) if relative.parts else directory


def confirm_destructive_changes(directory):
    drive = usb_drive_for(directory)
    print(f"USB drive: {drive}")
    print(f"Music directory: {directory.expanduser().absolute()}")
    print(
        "WARNING: This will make major, irreversible changes to the music files "
        "on this USB drive. Existing MP3 audio will not be re-encoded, but its "
        "metadata may be rewritten. M4A tracks will be converted to Ford-compatible "
        "MP3 files and the M4A originals will be removed."
    )
    try:
        answer = input('Type YES to continue: ')
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled. No files were changed.")
        return False

    if answer != "YES":
        print("Cancelled. No files were changed.")
        return False
    return True


def main():
    # Provide the directory path where the music files are located.
    directory_path = Path("/Volumes/CAR-TUNES/Albums")

    if not confirm_destructive_changes(directory_path):
        return 1
    if not directory_path.is_dir():
        print(f"Music directory does not exist: {directory_path}", file=sys.stderr)
        return 1
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print(
            "ffmpeg and ffprobe are required. Install ffmpeg before running this script.",
            file=sys.stderr,
        )
        return 1

    return 0 if update_music(directory_path) else 1


if __name__ == "__main__":
    raise SystemExit(main())
