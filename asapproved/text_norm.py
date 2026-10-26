"""Normalising text before comparing it to prescribed wording (R11).

The problem this solves, concretely. COBS 4.12A.11R prescribes:

    Don't invest unless you're prepared to lose all the money you invest.

The FCA handbook sets that with typographic apostrophes (U+2019). A design tool,
a CMS, an OCR pass or a copywriter's keyboard may produce straight ASCII ones.
Both render as the same words on screen and a reader could not tell them apart —
but a byte comparison calls them different, and R11 would then report that a
perfectly correct warning had been altered.

The opposite error matters more, though: if normalisation is too aggressive it
will quietly accept a warning whose MEANING was changed, which is the thing R11
exists to catch. So the line is drawn deliberately:

  NORMALISED (encoding, not wording)
    - curly quotes and apostrophes -> ASCII equivalents
    - en/em dashes -> hyphen, ellipsis character -> three dots
    - non-breaking and exotic spaces -> ordinary space
    - runs of whitespace -> one space; leading/trailing trimmed
    - case

  NEVER NORMALISED (these are wording)
    - any word substitution, insertion or deletion
    - punctuation that is not a typographic variant (added/removed commas,
      full stops, question marks)
    - word order

"you are unlikely to be protected" and "you should not expect to be protected"
differ by wording and must stay different after normalisation — they are the
cryptoasset and NRRS variants, and collapsing them would defeat the per-type
table entirely (DECISIONS.md D-007).
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normalise", "same_prescribed_text", "diff_summary"]

# Typographic variants that are encodings of the same character.
_PUNCT_MAP = {
    "‘": "'",  # left single quote
    "’": "'",  # right single quote / apostrophe
    "‚": "'",
    "‛": "'",
    "′": "'",  # prime
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "„": '"',
    "″": '"',
    "–": "-",  # en dash
    "—": "-",  # em dash
    "−": "-",  # minus sign
    "…": "...",  # ellipsis
    " ": " ",  # non-breaking space
    " ": " ",
    " ": " ",
    " ": " ",
    "​": "",  # zero-width space
    "﻿": "",  # BOM
}

_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Fold typographic encoding differences. Never changes words."""
    if text is None:
        return ""
    # NFKC first: composes accents and folds compatibility forms consistently.
    out = unicodedata.normalize("NFKC", text)
    for src, dst in _PUNCT_MAP.items():
        out = out.replace(src, dst)
    out = _WS.sub(" ", out).strip()
    return out.casefold()


def same_prescribed_text(observed: str, prescribed: str) -> bool:
    """True when the observed warning is the prescribed wording."""
    return normalise(observed) == normalise(prescribed)


def diff_summary(observed: str, prescribed: str) -> str:
    """A short, human description of the first divergence, for the finding.

    Word-level rather than character-level: "fine print" beats a caret pointing
    at character 143 when a compliance officer has to decide what happened.
    """
    o_words = normalise(observed).split()
    p_words = normalise(prescribed).split()
    if o_words == p_words:
        return "matches the prescribed wording"

    # strict=False is deliberate: unequal lengths are the truncation case, which
    # the two branches below report explicitly rather than raising on.
    for i, (a, b) in enumerate(zip(o_words, p_words, strict=False)):
        if a != b:
            start = max(0, i - 3)
            return (
                f"diverges at word {i + 1}: "
                f"expected “…{' '.join(p_words[start : i + 3])}…”, "
                f"found “…{' '.join(o_words[start : i + 3])}…”"
            )

    if len(o_words) < len(p_words):
        return f"truncated: {len(p_words) - len(o_words)} words missing from the end"
    return f"extended: {len(o_words) - len(p_words)} extra words at the end"
