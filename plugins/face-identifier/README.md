# Face Identifier (Stash plugin)

Who's in a scene, by their faces — like
[starIdentifier](https://github.com/stashapp/CommunityScripts/tree/main/plugins/starIdentifier),
with a dialog to work in, and [Visage](https://discourse.stashapp.cc/t/visage/11785)
as a second opinion.

## Install

Settings → Plugins → Available Plugins, source
`https://rokdd.github.io/stash-classicmusic-plugins/main/index.yml`, tick
**Face Identifier**. It needs **OpenCV** for the Python Stash runs — on the
Stash server:

    python3 -m pip install opencv-python-headless numpy

(the Python Stash uses — the dialog says which one if it's missing). The two
face models (OpenCV's YuNet and SFace, 40 MB) are downloaded the first time
into Stash's generated folder.

## Use

1. **Settings → Tasks → Learn the performers' faces** — every performer's
   portrait is read once and the face in it remembered (again after portraits
   change). Performers without a portrait can't be recognised yet — the
   Classical Music scraper fills portraits in.
2. On a scene: **⋮ → Who's in this scene?** — frames spread over the video
   (40; not Stash's small preview thumbnails: in real frames a face is big
   enough) are looked at. Runs as a Stash task: closing the dialog doesn't
   stop it, the dialog shows how far it is.
   - **Recognised:** the face in the video next to the portrait, in how many
     frames, how alike, the times (click: the video plays from there) —
     **Add to scene**. Unsure ones (once, barely alike) as *maybe*:
     **Yes, that's them** (added, and the face learnt) or **No**.
   - **Not recognised:** each unknown person's faces together. Say who it is
     — **That's them**: added to the scene and learnt, so next time they're
     recognised. The more you confirm, the better it knows them.
   - **Ask Visage too:** sends the scene's preview sprite to the Visage
     service (public on Hugging Face, or your own — setting **Visage
     service**). Visage knows StashDB's and JavStash's performers only — for
     concert recordings it rarely knows anyone; matches under 70 % aren't
     shown.
3. **Settings → Tasks → Identify the tagged scenes** — as starIdentifier:
   scenes tagged **Identify faces** get the performers recognised in two
   frames or more and clearly alike (0.45 — setting), and lose the tag.

Performers who died before 1930 (a composer's painted portrait) are left out —
they can't be in a video.

## How sure

SFace counts two faces as one person from 0.36 (cosine likeness); a match is
*recognised* when it's seen in two frames or is 0.45 alike, else *maybe*. The
face prints are kept in Stash's generated folder (`face-identifier/index.json`):
a portrait's print, plus up to 40 confirmed faces per performer.
