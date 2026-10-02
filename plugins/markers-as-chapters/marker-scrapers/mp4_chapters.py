"""The chapter track of an MP4 / M4V / MOV file, read directly.

MP4 files can hold chapters twice: a Nero "chpl" list and a QuickTime
chapter track (a text track, one sample per chapter). ffprobe merges them,
and when one is broken (all starting at 0:00) the times are lost in its
output — while the text track may still have them. This reads the text
track itself: its sample times (stts) and texts (stsz / stsc / stco).
Titles are decoded as UTF-8, UTF-16 (with a byte order mark) or, failing
that, Windows-1252 — so "schönen" written in the wrong encoding comes out
right. Standard library only; reads only the file's index (moov), not the
video.
"""

import struct

from encoding_fix import decode_bytes, fix_text

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf", b"udta"}


def _boxes(data, start=0, end=None):
    """(type, payload start, payload end) of the boxes in data[start:end]."""
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            break
        yield kind, pos + header, min(pos + size, end)
        pos += size


def _find(data, start, end, kind):
    for k, a, b in _boxes(data, start, end):
        if k == kind:
            return a, b
    return None


def _read_moov(path):
    """The moov box's bytes (the file's index), wherever it is."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size_of_file = f.tell()
        pos = 0
        while pos + 8 <= size_of_file:
            f.seek(pos)
            header = f.read(16)
            size, kind = struct.unpack(">I4s", header[:8])
            skip = 8
            if size == 1:
                size = struct.unpack(">Q", header[8:16])[0]
                skip = 16
            elif size == 0:
                size = size_of_file - pos
            if size < skip:
                return None
            if kind == b"moov":
                f.seek(pos + skip)
                return f.read(size - skip)
            pos += size
    return None


def _decode(raw):
    return fix_text(decode_bytes(raw))


def _text_track(moov, start, end):
    """For one trak: (timescale, stbl range) if it's a text track."""
    mdia = _find(moov, start, end, b"mdia")
    if not mdia:
        return None
    hdlr = _find(moov, *mdia, b"hdlr")
    if not hdlr or moov[hdlr[0] + 8:hdlr[0] + 12] not in (b"text", b"sbtl"):
        return None
    mdhd = _find(moov, *mdia, b"mdhd")
    version = moov[mdhd[0]]
    timescale = struct.unpack(">I", moov[mdhd[0] + (20 if version == 1 else 12):][:4])[0]
    minf = _find(moov, *mdia, b"minf")
    stbl = minf and _find(moov, *minf, b"stbl")
    return (timescale, stbl) if stbl and timescale else None


def read_chapters(path):
    """[(seconds, title)] from the file's chapter text track, or [] if it
    has none. Times are where each chapter starts."""
    moov = _read_moov(path)
    if not moov:
        return []
    for kind, a, b in _boxes(moov):
        if kind != b"trak":
            continue
        found = _text_track(moov, a, b)
        if not found:
            continue
        timescale, (s, e) = found
        table = {k: (x, y) for k, x, y in _boxes(moov, s, e)}
        if b"stts" not in table or b"stsz" not in table or b"stsc" not in table:
            continue
        # sample start times
        x = table[b"stts"][0]
        count = struct.unpack(">I", moov[x + 4:x + 8])[0]
        starts, t = [], 0
        for i in range(count):
            n, delta = struct.unpack(">II", moov[x + 8 + 8 * i:x + 16 + 8 * i])
            for _ in range(n):
                starts.append(t)
                t += delta
        # sample sizes
        x = table[b"stsz"][0]
        size, n = struct.unpack(">II", moov[x + 4:x + 12])
        sizes = [size] * n if size else list(struct.unpack(f">{n}I", moov[x + 12:x + 12 + 4 * n]))
        # chunk offsets
        if b"stco" in table:
            x = table[b"stco"][0]
            n = struct.unpack(">I", moov[x + 4:x + 8])[0]
            offsets = list(struct.unpack(f">{n}I", moov[x + 8:x + 8 + 4 * n]))
        elif b"co64" in table:
            x = table[b"co64"][0]
            n = struct.unpack(">I", moov[x + 4:x + 8])[0]
            offsets = list(struct.unpack(f">{n}Q", moov[x + 8:x + 8 + 8 * n]))
        else:
            continue
        # samples per chunk
        x = table[b"stsc"][0]
        n = struct.unpack(">I", moov[x + 4:x + 8])[0]
        runs = [struct.unpack(">III", moov[x + 8 + 12 * i:x + 20 + 12 * i]) for i in range(n)]
        positions = []
        for i, (first, per_chunk, _desc) in enumerate(runs):
            last = runs[i + 1][0] - 1 if i + 1 < len(runs) else len(offsets)
            for chunk in range(first, last + 1):
                pos = offsets[chunk - 1]
                for _ in range(per_chunk):
                    if len(positions) >= len(sizes):
                        break
                    positions.append(pos)
                    pos += sizes[len(positions) - 1]
        titles = []
        with open(path, "rb") as f:
            for pos, size in zip(positions, sizes):
                f.seek(pos)
                sample = f.read(size)
                length = struct.unpack(">H", sample[:2])[0] if len(sample) >= 2 else 0
                titles.append(_decode(sample[2:2 + length]).strip())
        return [(starts[i] / timescale, titles[i]) for i in range(min(len(starts), len(titles)))]
    return []
