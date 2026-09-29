# yt-dlp Downloader (Stash plugin)

Download videos — or whole playlists — with [yt-dlp](https://github.com/yt-dlp/yt-dlp)
straight into one of your Stash library folders. Each new scene gets its
title, source URL, upload date, description and thumbnail (as cover)
filled in from the video's own information.

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/yt-dlp-downloader

## Using it

1. Click the **download** button in Stash's top navigation bar.
2. Paste one or more URLs, one per line. Playlist URLs download every
   video in the playlist.
3. Pick the **library folder** to save into, optionally a **subfolder**
   (created if needed), and the **quality**: best available, or at most
   4K, 1080p or 720p.
4. **Download.** Progress shows in Settings → Tasks.

Your last folder, subfolder and quality are remembered in the browser.

Files are saved as `<title> [<video id>].mp4`. Video and audio are merged
into an `.mp4`, which plays in the browser as long as the site's codecs
do.

## What happens after the download

Stash runs one task at a time, so the download can't wait for its own
scan. Instead it queues a scan of the new files and a **Finish downloads**
task behind it. That one runs once the scan has created the scenes, and
fills each one in:

| Scene field | From |
|---|---|
| Title | the video's title |
| URL | the video's page |
| Date | its release or upload date |
| Details | its description |
| Cover | its thumbnail |

Until it has run, the new scenes show up with just their file name. The
video information and thumbnails are kept in a temporary folder, not in
your library (so Stash doesn't import the thumbnails as images), and
deleted once the scenes are filled in.

## Running in the background

Tick **Run in the background** in the dialog and the download runs
outside Stash's one-at-a-time task queue, so other tasks don't wait
behind it. The task finishes at once and names a log file (in a `logs`
folder inside the plugin's folder) with the download's progress, and the
command to stop it (`kill -- -<pid>`). The scan and **Finish downloads**
are queued as usual when it's done.

## Settings

Settings → Plugins → yt-dlp Downloader:

| Setting | Effect |
|---|---|
| Path to yt-dlp | Leave empty if `yt-dlp` is on the server's PATH; otherwise its full path. |
| Cookies file | A `cookies.txt` on the server, for sites that need a login. |
| Extra yt-dlp options | Passed to yt-dlp as they are, e.g. `--limit-rate 5M --embed-subs`. |

## Requirements

- **yt-dlp** on the machine Stash runs on — Debian/Ubuntu:
  `sudo apt install yt-dlp`, or `pip install yt-dlp` for the newest
  version (sites change often; an old yt-dlp is the most common reason a
  download fails).
- **ffmpeg**, for merging video and audio — Stash needs it anyway.
- **Python 3** — standard library only, nothing else to install.
- The library folder you save into must be one of Stash's library paths
  (Settings → Library); the dialog only offers those.

Only download what you have the right to.
