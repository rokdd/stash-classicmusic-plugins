# Marker Editor for Chapters (Stash plugin)

One panel for a scene's chapters (markers) — editing and importing in one
place. Uses [Markers as Chapters](../markers-as-chapters/) for the sources,
the audio, the composers and the tags; Stash installs it with this plugin.

## Where

- **The Markers tab** shows it in place of Stash's marker list — switch
  **Chapters | Stash's list** next to the buttons (remembered in the
  browser). While Stash's own marker form is open (Create Marker, editing
  one) the tab is Stash's; afterwards the editor loads the chapters again.
- **Scrape markers… → Chapter editor** — the same as a dialog.

## What it does

- **All sources in one table:** the markers in Stash, and with **Add from**
  whatever a source finds — the file's chapters, a chapter file (CUE, JSON …),
  ARTE / ORF ON, subtitles, text in the picture, pasted text. A chapter at
  the same time (±5 s) gets it as an alternative — take its **title**,
  **times** or **tags** with one click — the rest come in as new chapters.
- **Combine duplicates:** chapters less than 10 s apart — the fuller one
  stays, the other becomes its alternative (its tags aren't merged by
  themselves: a duplicate may carry a wrong composer).
- **Clean titles & composers:** composers named in the titles become tags
  (under Composers), the titles lose their names.
- **Extend to the next pause:** each chapter ends where the audio's next
  pause begins, never past the next chapter. **Starts onto the pauses**,
  **Shift all**, a new chapter **at the player**'s position.
- **Overview:** the whole scene as a bar — chapters in Stash blue, changed
  orange, new green, to be deleted red, pauses light blue; click one to get
  to its row.
- **Played:** how often each chapter was played, how long, and when last —
  counted while the scene's video plays (once per visit, after a minute of
  a chapter or half of a shorter one), kept by Markers as Chapters on the
  server.
- **Columns** (time, title, primary tag, tags, source, audio, played) can be
  hidden; remembered in the browser.
- **Save** creates, updates and deletes in one go; tags that don't exist yet
  are asked about first (make a performer from Wikidata, a plain tag, or
  leave it out).
