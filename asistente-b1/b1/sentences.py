"""Cut a streamed answer into sentences the speaker can say one at a time.

The model writes in pieces of a few characters. Speaking each piece would
sound broken, and waiting for the whole answer is what streaming avoids, so
the text is held until a sentence ends and handed over then. Pure code: text
in, sentences out.
"""

from __future__ import annotations

import re

# A sentence ends at . ! ? or … (closing quotes and brackets may follow),
# then a space; or at a line break. "3.5" and "b1.local" have no space after
# the dot, so they never end one.
_END = re.compile(r"[.!?…]+[\"'”’»)\]]*(?=\s)|\n+")

# Words whose dot is not the end of a sentence.
_ABBREVIATIONS = {
    "sr", "sra", "srta", "dr", "dra", "ud", "uds", "lic", "ing", "prof", "pág",
    "núm", "aprox", "mr", "mrs", "ms", "st", "vs", "etc", "e.g", "i.e", "p.ej",
}

# Shorter pieces wait for the next one: "Sí." alone is a pause, not a phrase.
MIN_CHARS = 20


class SentenceBuffer:
    """Feed text as it arrives; take back each sentence once it is complete."""

    def __init__(self, min_chars: int = MIN_CHARS) -> None:
        self.min_chars = min_chars
        self._text = ""

    def feed(self, piece: str) -> list[str]:
        """Add a piece of text and return the sentences it completed."""
        self._text += piece or ""
        out: list[str] = []
        start = 0
        for match in _END.finditer(self._text):
            end = match.end()
            candidate = self._text[start:end]
            if match.group().startswith((".",)) and _ends_in_abbreviation(candidate):
                continue
            if len(candidate.strip()) < self.min_chars and "\n" not in match.group():
                continue
            if candidate.strip():
                out.append(candidate.strip())
            start = end
        self._text = self._text[start:]
        return out

    def flush(self) -> list[str]:
        """Whatever is left once the answer is over."""
        rest, self._text = self._text.strip(), ""
        return [rest] if rest else []


def _ends_in_abbreviation(text: str) -> bool:
    words = text.rstrip(".").split()
    if not words:
        return False
    return words[-1].lower().strip("¿¡(\"'") in _ABBREVIATIONS
