# Plugins

One folder per plugin; each is independent of the others.

- **[`advanced-file-operations/`](advanced-file-operations/)** — H.265
  conversion, split a scene at its markers, repair a broken file. Runs
  ffmpeg on the server, so it needs ffmpeg with libx265 and Python 3 with
  `requests` there.
- **[`marker-improvements-plugin/`](marker-improvements-plugin/)** — tag
  images on the video scrubber, click-to-edit markers, per-tag styles.
  Browser only, nothing to install.
- **[`tag-improvements/`](tag-improvements/)** — a tag tree on the Tags
  page, tag descriptions from StashDB, and scraping that adds tags instead
  of replacing them. Needs Python 3 on the server (for StashDB), no extra
  modules.
- **[`yt-dlp-downloader/`](yt-dlp-downloader/)** — download videos and
  playlists with yt-dlp into a library folder, with the scenes filled in
  from the video's info. Needs yt-dlp and Python 3 on the server.

Installing, updating and the full feature list are in the
[main README](../README.md). Each folder's own README has the details.

Every `*.yml` in these folders is picked up by `build_site.sh`, which
the GitHub Actions workflow runs on every push to `main` to publish the
plugin source index.
