# Stash plugins

Two independent Stash plugins, each in its own subfolder:

- **`advanced-file-operations/`** — H265 conversion, split-scene-at-markers,
  and corrupt-file repair. Has a Python backend (needs `ffmpeg`/`ffprobe`
  and `pip install -r requirements.txt`). See its own README for details.
- **`marker-improvements-plugin/`** — shows each marker's tag image on the
  video scrubber, hover-to-reveal. Pure frontend, no backend, nothing to
  install beyond the folder itself. See its own README for details.

They don't depend on each other — install one, both, or neither.

## Installing directly (no git)

Copy each subfolder into your Stash `plugins` directory (Settings →
Plugins shows the exact path), so you end up with:

```
<your Stash plugins dir>/
  advanced-file-operations/
  marker-improvements-plugin/
```

Then Settings → Plugins → **Reload plugins**.

## Getting this onto GitHub

This folder is already a git repo with one commit, so pushing it is three
commands once you've made an empty repo on GitHub to push to:

1. On GitHub: **New repository** → give it a name → **do not** initialize
   it with a README/license/`.gitignore` (this folder already has
   content, and an empty repo avoids a merge conflict on the first push).
2. Copy the repo's URL GitHub shows you after creating it (the
   `https://github.com/<you>/<repo>.git` one, not the SSH one unless you
   already use SSH keys with GitHub).
3. In a terminal, inside this folder:
   ```
   git remote add origin https://github.com/<you>/<repo>.git
   git branch -M main
   git push -u origin main
   ```
   You'll be prompted to sign in — GitHub no longer accepts your account
   password for this; use a Personal Access Token (GitHub → Settings →
   Developer settings → Personal access tokens) as the password, or set
   up the GitHub CLI (`gh auth login`) once and it handles this for you.

### If you'd rather not use git at all

GitHub's web UI can take files directly:

1. Create the repo the same way as step 1 above.
2. On the repo's page, **Add file → Upload files**.
3. Either drag in the two subfolders' contents, or drag in this whole zip
   — GitHub will unzip it into the browser upload queue automatically —
   then **Commit changes**.

This works fine for getting the files up, but you'd need to repeat it
manually for every future update instead of `git push`; the git route
above is worth it if you plan on iterating.

## After it's on GitHub

To update your Stash instance later: `git pull` inside wherever you
cloned this repo into your Stash plugins directory, then Reload Plugins —
no manual re-copying needed from then on. (If you installed by copying
files instead of cloning, you'd `git clone` the repo fresh into your
plugins directory once, then `git pull` going forward.)
