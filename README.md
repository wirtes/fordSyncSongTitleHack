# Ford Sync Song Title Hack
This script works around an egregious bug in the Ford Sync audio system as it relates to playing music from USB sticks. Specifically, Ford Sync will play songs in alphabetical order based on the song title in the metadata in the .mp3 or .m4a file. So simply adding track numbers to the beginning of the filenames doesn't work.

This script will read the song title from the music file `title` and `tracknumber` metadata from each music file recursively from a starting point in a directory. It will then update the `title` to prefix the `tracknumber` at the beginning. This will force Ford Sync to play the songs in the correct order. It also updates the music file metadata with the comment "Ford Sync Sucks." This serves as a flag that the file has been updated & it will be skipped on subsequent executiuons of the script.

