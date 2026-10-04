"""Where Markers as Chapters keeps its analyses: in Stash's generated
folder (Settings → System → Application Paths → Generated), under
markers-as-chapters/ — with Stash's other generated content, so they can be
cleared with it and don't sit in the plugin's folder. The plugin passes the
folder as STASH_GENERATED (made absolute: Stash starts its plugins in its
own working directory, against which a relative "generated" counts).
Without it, or when it can't be written to: the plugin's folder, as before.

  audio     the loudness of each video's audio (the pauses, lining up files)
  frames    what was read in the picture (Text in the picture)
  progress  how far a long scraper is, per scene (and its lock)
"""

import os
import shutil

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD = {"audio": ".audio-cache", "frames": ".frames-cache", "progress": ".progress"}


def folder(kind):
    """The folder for `kind`, made if needed; what was in the old place in
    the plugin's folder is moved there the first time."""
    old = os.path.join(PLUGIN_DIR, OLD[kind])
    base = os.environ.get("STASH_GENERATED", "").strip()
    if base:
        new = os.path.join(base, "markers-as-chapters", kind)
        try:
            first = not os.path.isdir(new)
            os.makedirs(new, exist_ok=True)
            if first and os.path.isdir(old):
                for name in os.listdir(old):
                    try:
                        shutil.move(os.path.join(old, name), os.path.join(new, name))
                    except OSError:
                        pass
                shutil.rmtree(old, ignore_errors=True)
            return new
        except OSError:
            pass  # not writable: the plugin's folder
    os.makedirs(old, exist_ok=True)
    return old
