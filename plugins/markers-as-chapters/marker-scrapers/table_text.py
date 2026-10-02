"""Text that's a table: a programme or tracklist in columns.

read_table(text) → (rows, description) or None, where each row is
{"start", "end", "duration", "composer", "title", "performer"} (whatever
was found) and description says how the text was read — for the notes.

1. The separator: tabs, ";", "|", two or more spaces, or commas — the one
   that splits most lines into the same number (2+) of columns. Commas only
   when that's very consistent, since titles have commas of their own
   ("Walzer, op. 314"). Quoted cells ("a, b") are kept together.
2. The columns: by a header row if there is one (Zeit / Time / Start /
   Beginn, Ende / End, Dauer / Duration / Länge, Komponist / Composer,
   Titel / Title / Werk / Work, Interpret / Performer, Nr. / No. / #);
   otherwise by what's in them:
     - times: increasing ones are start times (a second increasing column,
       later than the first, the end times), others durations;
     - 1, 2, 3 …: a track number — left out;
     - text: the column with repeated, name-like, short cells is the
       composer; the least name-like (numbers, "op.", "Nr.") and longest the
       title; another one the performers.
Lines that don't fit (a heading, an empty line) are left out.
"""

import csv
import io
import re
from collections import Counter

TIME_CELL = re.compile(r"^\s*[\[(]?\s*(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?:[.,](\d{1,3}))?\s*[\])]?\s*$")
NUMBER_CELL = re.compile(r"^\s*(\d{1,3})[.)]?\s*$")

HEADERS = {
    "start": r"^(zeit|time|start|beginn|anfang|ab|von|from|timecode|tc)$",
    "end": r"^(ende|end|bis|to|until)$",
    "duration": r"^(dauer|duration|länge|laenge|length|spielzeit)$",
    "composer": r"^(komponist(in)?|composer|komp\.?|autor|author|von)$",
    "title": r"^(titel|title|werk|work|stück|stueck|piece|programm|program(me)?|track)$",
    "performer": r"^(interpret(en|in)?|performer|künstler|kuenstler|artist|solist(en)?|ausführende)$",
    "number": r"^(nr\.?|no\.?|#|track ?nr\.?|nummer|pos\.?)$",
}
LABELS = {"start": "start time", "end": "end time", "duration": "duration", "composer": "composer",
          "title": "title", "performer": "performer", "number": "number"}


def seconds(cell):
    m = TIME_CELL.match(cell or "")
    if not m:
        return None
    h, mi, s, frac = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + (float("0." + frac) if frac else 0)


def _split(lines, delimiter):
    if delimiter == "  ":
        return [[c.strip() for c in re.split(r"\s{2,}", line.strip())] for line in lines]
    if delimiter in (",", ";"):
        return [[c.strip() for c in row] for row in csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)]
    return [[c.strip() for c in line.split(delimiter)] for line in lines]


def _best_split(lines):
    best = None
    for delimiter, name in (("\t", "tab-separated"), (";", "separated by ;"), ("|", "separated by |"),
                            ("  ", "in columns of spaces"), (",", "separated by commas")):
        rows = _split(lines, delimiter)
        counts = Counter(len(r) for r in rows if len(r) > 1)
        if not counts:
            continue
        width, fitting = counts.most_common(1)[0]
        share = fitting / len(lines)
        needed = 0.9 if delimiter == "," else 0.6
        if share < needed or fitting < 2:
            continue
        score = share + (0.05 if delimiter == "\t" else 0)
        if not best or score > best[0]:
            best = (score, rows, width, name)
    return best


def _increasing(values):
    known = [v for v in values if v is not None]
    return len(known) > 1 and all(b > a for a, b in zip(known, known[1:]))


def _name_like(cell):
    words = cell.split()
    return 1 <= len(words) <= 5 and not re.search(r"\d", cell) and all(w[:1].isupper() or w.lower() in
                                                                          ("van", "von", "de", "der", "di", "da", "y", "le", "la", "du") for w in words)


def read_table(text):
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    found = _best_split(lines)
    if not found:
        return None
    _score, rows, width, how = found
    rows = [r for r in rows if len(r) == width]

    # A header row?
    roles = {}
    first = [c.strip().lower().rstrip(":") for c in rows[0]]
    for i, cell in enumerate(first):
        for role, pattern in HEADERS.items():
            if role not in roles.values() and re.match(pattern, cell):
                roles[i] = role
                break
    if len(roles) >= 2 or (roles and not any(seconds(c) is not None for c in rows[0])):
        rows = rows[1:]
        from_header = True
    else:
        roles = {}
        from_header = False
    if not rows:
        return None

    if not from_header:
        columns = list(zip(*rows))
        time_cols, text_cols = [], []
        for i, col in enumerate(columns):
            filled = [c for c in col if c]
            if not filled:
                continue
            times = [seconds(c) for c in col]
            if sum(t is not None for t in times) >= 0.7 * len(filled):
                time_cols.append((i, times))
            elif all(NUMBER_CELL.match(c) for c in filled) and _increasing([int(NUMBER_CELL.match(c).group(1)) for c in filled]):
                roles[i] = "number"
            else:
                text_cols.append(i)
        increasing = [(i, t) for i, t in time_cols if _increasing(t)]
        if increasing:
            roles[increasing[0][0]] = "start"
            if len(increasing) > 1:
                roles[increasing[1][0]] = "end"
        for i, _t in time_cols:
            if i not in roles:
                roles[i] = "duration"
                break
        if len(text_cols) == 1:
            roles[text_cols[0]] = "title"
        elif text_cols:
            def stats(i):
                cells = [r[i] for r in rows if r[i]]
                avg = sum(len(c) for c in cells) / max(1, len(cells))
                repeated = 1 - len(set(cells)) / max(1, len(cells))
                names = sum(_name_like(c) for c in cells) / max(1, len(cells))
                return avg, repeated, names
            info = {i: stats(i) for i in text_cols}
            # The composer first: the most repeated, most name-like cells
            # (ties: the shorter ones); then the title: the longest of the rest.
            composer_col = max(text_cols, key=lambda i: (round(info[i][1] + info[i][2], 2), -info[i][0]))
            rest = [i for i in text_cols if i != composer_col]
            # the title: the least name-like (works have numbers, "op.", "Nr."),
            # then the longest; a name-like column left over is performers
            title_col = max(rest, key=lambda i: (round(1 - info[i][2], 2), info[i][0]))
            if info[composer_col][1] + info[composer_col][2] <= info[title_col][1] + info[title_col][2] \
                    and info[composer_col][0] > info[title_col][0]:
                composer_col, title_col = title_col, composer_col  # nothing tells them apart: longer = title
            roles[composer_col] = "composer"
            roles[title_col] = "title"
            for i in text_cols:
                if i not in roles:
                    roles[i] = "performer"
                    break

    if "title" not in roles.values() and "composer" not in roles.values():
        return None
    out = []
    for r in rows:
        row = {}
        for i, role in roles.items():
            cell = r[i] if i < len(r) else ""
            if role in ("start", "end", "duration"):
                row[role] = seconds(cell)
            elif role != "number":
                row[role] = cell.strip()
        if row.get("title") or row.get("composer"):
            out.append(row)
    if not out:
        return None
    order = [LABELS[roles[i]] for i in sorted(roles)]
    description = (f"Read as a table ({how}, {width} columns"
                   + (", with a header row" if from_header else "") + "): " + ", ".join(order) + ".")
    return out, description
