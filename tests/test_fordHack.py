import unittest
from pathlib import Path
from unittest.mock import patch

from fordHack import (
    PROCESSED_COMMENT,
    PREVIOUS_PROCESSED_COMMENT,
    PREVIOUS_PROCESSED_COMMENT_V2,
    PREVIOUS_PROCESSED_COMMENT_V3,
    PREVIOUS_PROCESSED_COMMENT_V4,
    TrackPlan,
    assign_album_track_numbers,
    ford_filename,
    ford_title,
    is_various_artists,
    planned_destination,
    read_track_plan,
    verify_updated_metadata,
)


def track(name, track_number, disc_number, **overrides):
    values = {
        "file_path": Path(f"/music/Album/{name}.mp3"),
        "title": name,
        "artist": "Artist",
        "album": "Album",
        "album_artist": "Artist",
        "track_number": track_number,
        "disc_number": disc_number,
        "total_discs": 2,
        "compilation": False,
        "previous_comments": set(),
    }
    values.update(overrides)
    return TrackPlan(**values)


class FordTitleTests(unittest.TestCase):
    def test_compilation_adds_artist_after_title(self):
        self.assertEqual(
            ford_title("Song", 3, artist="Singer", compilation=True),
            "03 - Song (Singer)",
        )

    def test_previous_prefix_is_replaced_during_migration(self):
        self.assertEqual(
            ford_title(
                "01 - Song",
                12,
                PREVIOUS_PROCESSED_COMMENT,
                artist="Singer",
                compilation=True,
            ),
            "12 - Song (Singer)",
        )

    def test_v2_compilation_migration_does_not_duplicate_artist_suffix(self):
        item = track(
            "01 - Song (Singer)",
            1,
            1,
            artist="Collection",
            album="Collection",
            album_artist="Various Artists",
            compilation=True,
            previous_comments={PREVIOUS_PROCESSED_COMMENT_V2},
        )
        item.adjusted_track_number = 1

        self.assertEqual(item.expected_title, "01 - Song (Singer)")
        self.assertEqual(item.track_artist, "Singer")

    def test_v3_compilation_migration_recovers_original_artist(self):
        item = track(
            "01 - Song (Singer)",
            1,
            1,
            artist="Collection",
            album="Collection",
            album_artist="Various Artists",
            compilation=True,
            previous_comments={PREVIOUS_PROCESSED_COMMENT_V3},
        )

        self.assertEqual(item.track_artist, "Singer")

    def test_v4_unrecognized_various_artist_album_gets_full_migration(self):
        item = track(
            "01 - Lifetime Monologue",
            1,
            1,
            file_path=Path(
                "/music/1-01. Lou Rawls - Lifetime Monologue.mp3"
            ),
            artist="Lou Rawls",
            album="Collection",
            album_artist="Various Artists",
            compilation=True,
            previous_comments={PREVIOUS_PROCESSED_COMMENT_V4},
        )
        item.adjusted_track_number = 1

        self.assertEqual(
            item.expected_title,
            "01 - Lifetime Monologue (Lou Rawls)",
        )
        self.assertEqual(item.expected_artist, "Collection")
        self.assertEqual(
            planned_destination(item),
            Path("/music/1-01. Lifetime Monologue.mp3"),
        )

    def test_v4_existing_compilation_suffix_is_not_duplicated(self):
        item = track(
            "01 - Song (Singer)",
            1,
            1,
            artist="Collection",
            album="Collection",
            album_artist="Various Artists",
            compilation=True,
            previous_comments={PREVIOUS_PROCESSED_COMMENT_V4},
        )
        item.adjusted_track_number = 1

        self.assertEqual(item.expected_title, "01 - Song (Singer)")
        self.assertEqual(item.track_artist, "Singer")


class FordFilenameTests(unittest.TestCase):
    def test_compilation_artist_is_removed_from_filename(self):
        source = Path("/music/1-07. Art Blakey - Afrique.mp3")

        self.assertEqual(
            ford_filename(source, "Art Blakey", compilation=True),
            Path("/music/1-07. Afrique.mp3"),
        )

    def test_lou_rawls_artist_is_removed_from_filename(self):
        source = Path("/music/1-01. Lou Rawls - Lifetime Monologue.mp3")

        self.assertEqual(
            ford_filename(source, "Lou Rawls", compilation=True),
            Path("/music/1-01. Lifetime Monologue.mp3"),
        )

    def test_non_compilation_filename_is_unchanged(self):
        source = Path("/music/1-07. Art Blakey - Afrique.mp3")

        self.assertEqual(
            ford_filename(source, "Art Blakey", compilation=False),
            source,
        )

    def test_artist_text_elsewhere_in_filename_is_unchanged(self):
        source = Path("/music/1-07. Afrique - Art Blakey.mp3")

        self.assertEqual(
            ford_filename(source, "Art Blakey", compilation=True),
            source,
        )


class AlbumNumberingTests(unittest.TestCase):
    def test_each_disc_continues_after_previous_discs_last_track(self):
        tracks = [
            track("Disc 1 Track 1", 1, 1),
            track("Disc 1 Track 3", 3, 1),
            track("Disc 2 Track 1", 1, 2),
            track("Disc 2 Track 2", 2, 2),
        ]

        assign_album_track_numbers(tracks)

        self.assertEqual(
            [item.adjusted_track_number for item in tracks],
            [1, 3, 4, 5],
        )
        self.assertEqual(
            [item.expected_track_number for item in tracks],
            [1, 3, 4, 5],
        )
        self.assertEqual(
            [item.expected_disc_number for item in tracks],
            [1, 1, 1, 1],
        )
        self.assertEqual(
            [item.expected_total_discs for item in tracks],
            [1, 1, 1, 1],
        )

    def test_single_disc_keeps_original_track_numbers(self):
        tracks = [
            track("Track 2", 2, 1, total_discs=1),
            track("Track 4", 4, 1, total_discs=1),
        ]

        assign_album_track_numbers(tracks)

        self.assertEqual(
            [item.adjusted_track_number for item in tracks],
            [2, 4],
        )
        self.assertEqual(
            [item.expected_track_number for item in tracks],
            [2, 4],
        )

    def test_offsets_accumulate_across_three_discs(self):
        tracks = [
            track("Disc 1", 2, 1, total_discs=3),
            track("Disc 2", 3, 2, total_discs=3),
            track("Disc 3", 1, 3, total_discs=3),
        ]

        assign_album_track_numbers(tracks)

        self.assertEqual(
            [item.adjusted_track_number for item in tracks],
            [2, 5, 6],
        )

    def test_albums_with_the_same_name_but_different_artists_stay_separate(self):
        first = track("First", 10, 1, album_artist="First Artist")
        second = track("Second", 1, 2, album_artist="Second Artist")

        assign_album_track_numbers([first, second])

        self.assertEqual(first.adjusted_track_number, 10)
        self.assertEqual(second.adjusted_track_number, 1)


class TrackPlanTests(unittest.TestCase):
    def test_compilation_uses_album_as_artist(self):
        item = track(
            "Song",
            1,
            1,
            total_discs=1,
            artist="Singer",
            album="Collection",
            album_artist="Various Artists",
            compilation=True,
        )
        item.adjusted_track_number = 1

        self.assertEqual(item.expected_title, "01 - Song (Singer)")
        self.assertEqual(item.expected_artist, "Collection")

    def test_various_artists_album_artist_implies_compilation(self):
        audio = {
            "title": "Lifetime Monologue",
            "artist": "Lou Rawls",
            "album": "Collection",
            "albumartist": "Various Artists",
            "tracknumber": "1",
            "discnumber": "1",
            "totaldiscs": "1",
            "compilation": "",
            "comment": "",
        }

        with patch("fordHack.load_file", return_value=audio):
            item = read_track_plan(Path("/music/song.m4a"))

        self.assertTrue(item.compilation)

    def test_various_artist_labels_are_recognized(self):
        self.assertTrue(is_various_artists("Various Artists"))
        self.assertTrue(is_various_artists("various-artists"))
        self.assertTrue(is_various_artists("Various"))
        self.assertFalse(is_various_artists("Lou Rawls"))


class MetadataVerificationTests(unittest.TestCase):
    def test_single_disc_allows_blank_optional_disc_tags(self):
        item = track("Song", 1, 1, total_discs=1)
        item.adjusted_track_number = 1
        audio = {
            "title": "01 - Song",
            "artist": "Artist",
            "tracknumber": "1",
            "discnumber": "",
            "totaldiscs": "",
            "comment": PROCESSED_COMMENT,
        }

        with patch("fordHack.load_file", return_value=audio):
            verify_updated_metadata(item.file_path, item)


if __name__ == "__main__":
    unittest.main()
