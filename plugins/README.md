# Plugins

One folder per plugin; each is independent of the others.

- **[`advanced-file-operations/`](advanced-file-operations/)** — H.265
  conversion, split a scene at its markers, repair a broken file. Runs
  ffmpeg on the server, so it needs ffmpeg with libx265 and Python 3 with
  `requests` there.
- **[`marker-improvements-plugin/`](marker-improvements-plugin/)** — tag
  images on the video scrubber, click-to-edit markers, per-tag styles.
  Browser only, nothing to install.
- **[`tag-tree/`](tag-tree/)** — all tags as a collapsible parent/child
  tree. Browser only, nothing to install.

Installing, updating and the full feature list are in the
[main README](../README.md). Each folder's own README has the details.

Every `*.yml` in these folders is picked up by `build_site.sh`, which
the GitHub Actions workflow runs on every push to `main` to publish the
plugin source index.
