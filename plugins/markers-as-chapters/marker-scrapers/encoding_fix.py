"""Text in the wrong encoding, set right.

decode_bytes(raw): text from bytes that should be UTF-8 but may contain
  parts in Windows-1252 / Latin-1 (old tools write "schönen" as one byte
  0xF6): valid UTF-8 stays as it is, every byte that isn't is read as
  Windows-1252. A UTF-16 byte order mark is honoured.
fix_text(s): repairs text that was decoded the wrong way round already —
  UTF-8 read as Windows-1252 ("schÃ¶nen" → "schönen"), even twice. Text
  that doesn't look like that is returned unchanged.
"""

import codecs
import re


def _cp1252_fallback(error):
    bad = error.object[error.start:error.end]
    return bad.decode("cp1252", "replace"), error.end


codecs.register_error("cp1252_fallback", _cp1252_fallback)


def decode_bytes(raw):
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    return raw.decode("utf-8", "cp1252_fallback")


# "Ã¶", "Ã©", "â€™" … — the marks UTF-8 leaves when read as Windows-1252.
_MOJIBAKE = re.compile("[ÂÃÅÆâ][\u0080-¿ŒœŠšŸŽžƒˆ˜–-…‰‹›€™]")


def fix_text(text):
    if not text or not _MOJIBAKE.search(text):
        return text
    for _ in range(2):  # sometimes it happened twice
        try:
            fixed = text.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            try:
                fixed = text.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
        if fixed == text:
            break
        text = fixed
        if not _MOJIBAKE.search(text):
            break
    return text
