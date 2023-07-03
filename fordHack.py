#!/Library/Frameworks/Python.framework/Versions/3.10/bin/python3

import os
from music_tag import load_file

def update_metadata(directory):
    # Track files processed to give feedback
    tracks_processed = 0
    # Iterate through all files and directories
    for root, dirs, files in os.walk(directory):

        # Exclude directories starting with "."
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        # Exclude files starting with "."
        files[:] = [f for f in files if not f.startswith('.')]

        for filename in files:
            tracks_processed += 1
            if filename.endswith('.mp3') or filename.endswith('.m4a'):
                # Print a dot every 50 tracks
                if tracks_processed % 50 == 0:
                    print("Processed " + str(tracks_processed) + " tracks")
                file_path = os.path.join(root, filename)
                try:
                    audio = load_file(file_path)

                    # Get the existing title and track number
                    title = audio["title"]
                    track_number = audio["tracknumber"]
                    comment = str(audio["comment"])

                    # Add a two-digit track number to the beginning of the title
                    new_track_number = str(int(track_number)).zfill(2)
                    new_title = f"{new_track_number} - {title}"
                    new_comment = "Ford Sync Sucks"
                    # print(comment, new_comment)
                    if comment != new_comment:
                        # Update the title in the metadata
                        audio["title"] = new_title
                        audio["comment"] = new_comment
                        # Save the changes
                        audio.save()
                        print(f"Updated metadata for {file_path}")
                except Exception as e:
                    print(f"Failed to update metadata for {file_path}: {e}")


# Provide the directory path where the MP3 files are located
directory_path = "/Volumes/USB/Albums"
update_metadata(directory_path)
