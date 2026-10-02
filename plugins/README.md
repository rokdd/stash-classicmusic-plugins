# Plugins

One folder per plugin; each is independent of the others.

- **[`advanced-file-operations/`](advanced-file-operations/)** — H.265
  conversion, split a scene at its markers, repair a broken file, a
  torrent check and yt-dlp downloads. Runs
  ffmpeg on the server, so it needs ffmpeg with libx265 and Python 3 with
  `requests` there.
- **[`marker-improvements-plugin/`](marker-improvements-plugin/)** — tag
  images on the video's seek bar, click-to-edit markers, per-tag styles,
  marker scrapers (chapters from the file or online, or from plain text).
  Python 3 for the scrapers (no extra modules).
- **[`tag-improvements/`](tag-improvements/)** — a tag tree on the Tags
  page, tag descriptions from StashDB, and scraping that adds tags instead
  of replacing them. Needs Python 3 on the server (for StashDB), no extra
  modules.

Installing, updating and the full feature list are in the
[main README](../README.md). Each folder's own README has the details.

Every `*.yml` in these folders is picked up by `build_site.sh`, which
the GitHub Actions workflow runs on every push to `main` to publish the
plugin source index.
