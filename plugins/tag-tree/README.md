# Tag Tree (Stash plugin)

Shows all your tags as a collapsible tree of parents and children — the
hierarchy you set up with each tag's *Parent tags* / *Sub-tags* — on its
own page. Pure frontend: no Python, nothing to install beyond the folder.

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/tag-tree

## Opening it

A **sitemap icon** button appears in Stash's top navigation bar, next to
its own utility buttons. Click it to open the tree, or go straight to
`/plugin/tag-tree` on your Stash address.

Needs Stash v0.25 or newer (the plugin API that lets a plugin add a page).

## What it shows

- Every tag without a parent at the top level, its sub-tags nested
  beneath it, sorted by name.
- Each tag's image (if it has a custom one uploaded), its name — a link to
  its own tag page — and how many scenes and markers use it.
- A tag with several parents appears under each of them.
- A loop in the hierarchy (a tag that's its own ancestor) is shown once
  and marked "loop — already above" instead of repeating forever.

## Using it

- **Expand/collapse** a branch with the arrow in front of it, or all of
  them at once with **Expand all** / **Collapse all**. Which branches are
  open is remembered in your browser for next time.
- **Search** matches tag names and aliases. Matching tags are shown in
  their place in the tree, with the path from the top down to each one
  opened automatically.
