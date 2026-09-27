#!/Library/Frameworks/Python.framework/Versions/3.10/bin/python3

from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from music_tag import load_file


PROCESSED_COMMENT = "Ford Sync REALLY Sucks v5"
PREVIOUS_PROCESSED_COMMENT_V4 = "Ford Sync REALLY Sucks v4"
PREVIOUS_PROCESSED_COMMENT_V3 = "Ford Sync REALLY Sucks v3"
PREVIOUS_PROCESSED_COMMENT_V2 = "Ford Sync REALLY Sucks v2"
PREVIOUS_PROCESSED_COMMENT = "Ford Sync REALLY Sucks"
LEGACY_COMMENT = "Ford Sync Sucks"
SUPPORTED_EXTENSIONS = {".mp3", ".m4a"}
OLD_PROCESSED_COMMENTS = {
    PREVIOUS_PROCESSED_COMMENT_V4,
    PREVIOUS_PROCESSED_COMMENT_V3,
    PREVIOUS_PROCESSED_COMMENT_V2,
    PREVIOUS_PROCESSED_COMMENT,
    LEGACY_COMMENT,
}
TRACK_PREFIX = re.compile(r"^\d+\s+-\s+")


@dataclass
class TrackPlan:
    """Metadata needed to update one track after the whole album is known."""

    file_path: Path
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int
    disc_number: int
    total_discs: int
    compilation: bool
    previous_comments: set
    adjusted_track_number: int = 0
    multi_disc: bool = False

    @property
    def already_processed(self):
        return PROCESSED_COMMENT in self.previous_comments

    @property
    def album_key(self):
        if self.album:
            return (self.album.casefold(), self.album_artist.casefold())
        # Do not accidentally combine unrelated tracks whose album tag is blank.
        return (str(self.file_path.parent), "")

    @property
    def expected_artist(self):
        return self.album if self.compilation else self.artist

    @property
    def title_artist_suffix(self):
        if not self.compilation:
            return ""
        match = re.search(r"\(([^()]*)\)$", self.title)
        return match.group(1) if match else ""

    @property
    def title_already_includes_artist(self):
        if self.previous_comments.intersection(
            {PREVIOUS_PROCESSED_COMMENT_V2, PREVIOUS_PROCESSED_COMMENT_V3}
        ):
            return True
        if PREVIOUS_PROCESSED_COMMENT_V4 in self.previous_comments:
            return bool(
                self.title_artist_suffix
                and self.artist.casefold() == self.album.casefold()
            )
        return PROCESSED_COMMENT in self.previous_comments

    @property
    def track_artist(self):
        """Return the original artist after compilation metadata was rewritten."""
        if self.title_already_includes_artist and self.title_artist_suffix:
            return self.title_artist_suffix
        return self.artist

    @property
    def expected_track_number(self):
        return self.adjusted_track_number if self.multi_disc else self.track_number

    @property
    def expected_disc_number(self):
        return 1 if self.multi_disc else self.disc_number

    @property
    def expected_total_discs(self):
        return 1 if self.multi_disc else self.total_discs

    @property
    def expected_title(self):
        old_marker = next(
            (c for c in OLD_PROCESSED_COMMENTS if c in self.previous_comments),
            "",
        )
        return ford_title(
            self.title,
            self.adjusted_track_number,
            old_marker,
            artist=self.artist,
            compilation=(self.compilation and not self.title_already_includes_artist),
        )


def tag_value(audio, key):
    """Return a music_tag value as plain text."""
    return str(audio[key]).strip()


def is_various_artists(value):
    """Recognize common Various Artists album-artist values."""
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    return normalized in {"various", "variousartists"}


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


def ford_title(
    title, track_number, previous_comment="", artist="", compilation=False
):
    """Build the title SYNC should sort, migrating titles made by older versions."""
    track = int(track_number)
    prefix = f"{track:02d} - "

    if previous_comment in OLD_PROCESSED_COMMENTS:
        title = TRACK_PREFIX.sub("", title, count=1)

    if compilation:
        title = f"{title} ({artist})"

    return f"{prefix}{title}"


def ford_filename(file_path, artist, compilation):
    """Remove a compilation track's artist segment from its filename."""
    if not compilation or not artist:
        return file_path

    pattern = re.compile(
        rf"^(?P<prefix>.*\.\s+)?{re.escape(artist)}\s+-\s+(?P<title>.+)$",
        re.IGNORECASE,
    )
    match = pattern.match(file_path.stem)
    if not match:
        return file_path

    cleaned_stem = f"{match.group('prefix') or ''}{match.group('title')}"
    return file_path.with_name(f"{cleaned_stem}{file_path.suffix}")


def planned_destination(plan, extension=None):
    """Return the output path after compilation filename cleanup."""
    destination = ford_filename(
        plan.file_path,
        plan.track_artist,
        plan.compilation,
    )
    return destination.with_suffix(extension) if extension else destination


def ensure_destination_available(source, destination):
    if destination != source and destination.exists():
        raise FileExistsError(
            f"cannot rename {source.name}: {destination.name} already exists"
        )


def read_track_plan(file_path):
    """Read the original tags used to plan album-wide numbering."""
    audio = load_file(file_path)
    title = tag_value(audio, "title")
    track_number = tag_value(audio, "tracknumber")
    if not title:
        raise ValueError("title metadata is missing")
    if not track_number:
        raise ValueError("tracknumber metadata is missing")

    artist = tag_value(audio, "artist")
    album = tag_value(audio, "album")
    album_artist = tag_value(audio, "albumartist")
    compilation = bool(audio["compilation"]) or is_various_artists(album_artist)
    if compilation and not artist:
        raise ValueError("artist metadata is missing for compilation track")
    if compilation and not album:
        raise ValueError("album metadata is missing for compilation track")

    if file_path.suffix.lower() == ".mp3":
        comments = mp3_comment_values(audio)
    else:
        comment = tag_value(audio, "comment")
        comments = {comment} if comment else set()

    return TrackPlan(
        file_path=file_path,
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        track_number=int(track_number),
        disc_number=int(tag_value(audio, "discnumber") or 1),
        total_discs=int(tag_value(audio, "totaldiscs") or 1),
        compilation=compilation,
        previous_comments=comments,
    )


def assign_album_track_numbers(tracks):
    """Flatten disc/track pairs into one continuous number per album."""
    albums = defaultdict(list)
    for track in tracks:
        albums[track.album_key].append(track)

    for album_tracks in albums.values():
        disc_numbers = {track.disc_number for track in album_tracks}
        is_multi_disc = (
            len(disc_numbers) > 1
            or max(track.total_discs for track in album_tracks) > 1
        )
        if not is_multi_disc:
            for track in album_tracks:
                track.adjusted_track_number = track.track_number
                track.multi_disc = False
            continue

        offset = 0
        for disc_number in sorted(disc_numbers):
            disc_tracks = [
                track for track in album_tracks if track.disc_number == disc_number
            ]
            for track in disc_tracks:
                track.adjusted_track_number = offset + track.track_number
                track.multi_disc = True
            offset += max(track.track_number for track in disc_tracks)


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


def verify_updated_metadata(file_path, plan):
    """Reopen a written file and verify every tag changed by this script."""
    verified_audio = load_file(file_path)
    if tag_value(verified_audio, "title") != plan.expected_title:
        raise RuntimeError("updated title could not be verified")
    if tag_value(verified_audio, "artist") != plan.expected_artist:
        raise RuntimeError("updated artist could not be verified")
    if plan.multi_disc:
        if int(tag_value(verified_audio, "tracknumber")) != plan.expected_track_number:
            raise RuntimeError("updated track number could not be verified")
        if int(tag_value(verified_audio, "discnumber")) != plan.expected_disc_number:
            raise RuntimeError("updated disc number could not be verified")
        if int(tag_value(verified_audio, "totaldiscs")) != plan.expected_total_discs:
            raise RuntimeError("updated total disc count could not be verified")
    if mp3_comment_values(verified_audio) != {PROCESSED_COMMENT}:
        raise RuntimeError("processed comment could not be verified")


def apply_planned_metadata(audio, plan):
    """Apply the metadata changes shared by existing and converted MP3s."""
    audio["title"] = plan.expected_title
    if plan.compilation:
        audio["artist"] = plan.album
    if plan.multi_disc:
        audio["tracknumber"] = plan.adjusted_track_number
        audio["discnumber"] = 1
        audio["totaldiscs"] = 1
    set_mp3_comment(audio, PROCESSED_COMMENT)


def update_mp3_metadata(plan):
    """Update an existing MP3 without re-encoding its audio."""
    file_path = plan.file_path
    destination = planned_destination(plan)
    ensure_destination_available(file_path, destination)
    audio = load_file(file_path)
    if plan.already_processed:
        if destination != file_path:
            os.replace(file_path, destination)
            return "metadata", destination
        return "skipped", destination

    apply_planned_metadata(audio, plan)
    audio.save()
    verify_updated_metadata(file_path, plan)
    if destination != file_path:
        os.replace(file_path, destination)
    return "metadata", destination


def convert_and_update(plan):
    """Convert one non-MP3 track and atomically install the finished MP3."""
    file_path = plan.file_path
    destination = planned_destination(plan, ".mp3")
    ensure_destination_available(file_path, destination)

    temporary = file_path.with_name(f".{file_path.stem}.ford-sync.tmp.mp3")
    try:
        run_ffmpeg(file_path, temporary)

        converted_audio = load_file(temporary)
        apply_planned_metadata(converted_audio, plan)
        converted_audio.save()

        verify_mp3(temporary)
        verify_updated_metadata(temporary, plan)

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
    file_paths = []
    tracks = []
    tracks_updated = 0
    tracks_skipped = 0
    tracks_failed = 0

    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        files = sorted(f for f in files if not f.startswith("."))
        for filename in files:
            file_path = Path(root, filename)
            if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                file_paths.append(file_path)

    for tracks_seen, file_path in enumerate(file_paths, start=1):
        if tracks_seen % 50 == 0:
            print(f"Checked {tracks_seen} tracks")
        try:
            tracks.append(read_track_plan(file_path))
        except Exception as error:
            tracks_failed += 1
            print(f"Failed to read {file_path}: {error}", file=sys.stderr)

    assign_album_track_numbers(tracks)

    for plan in tracks:
        try:
            if plan.file_path.suffix.lower() == ".mp3":
                status, result_path = update_mp3_metadata(plan)
            else:
                status, result_path = convert_and_update(plan)

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
            print(f"Failed to update {plan.file_path}: {error}", file=sys.stderr)

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
