"""Legacy Georgian CAD font encoding (AcadNusx / AcadMtavr family) <-> Unicode Georgian.

Georgian CAD offices type Georgian with Latin keys and let a special font draw the Georgian
glyphs, so the PDF text layer holds Latin letters: "sacxovrebeli farTobi" is
"საცხოვრებელი ფართობი". Case matters for a few letters (T=თ but t=ტ, S=შ but s=ს, ...).
"""

import re

# Lower-case keys and the case-sensitive capitals with their own meaning.
_TO_GEORGIAN = {
    "a": "ა", "b": "ბ", "g": "გ", "d": "დ", "e": "ე", "v": "ვ", "z": "ზ", "i": "ი",
    "k": "კ", "l": "ლ", "m": "მ", "n": "ნ", "o": "ო", "p": "პ", "r": "რ", "s": "ს",
    "t": "ტ", "u": "უ", "f": "ფ", "q": "ქ", "y": "ყ", "c": "ც", "w": "წ", "x": "ხ",
    "j": "ჯ", "h": "ჰ",
    "T": "თ", "J": "ჟ", "R": "ღ", "S": "შ", "C": "ჩ", "Z": "ძ", "W": "ჭ",
}
_TO_LATIN = {v: k for k, v in _TO_GEORGIAN.items()}

# Fonts whose Latin text layer is really Georgian. Matched case-insensitively against the
# PDF font name with any subset prefix ("ABCDEF+AcadNusx") removed.
# Fonts that draw Georgian from Latin codes (text "saxanZro" shows as სახანძრო). Checked against
# the samples' actual text: Avaza/AvazaMtavruli carry only Latin; BPG* fonts (BPGExtraSquareMtavruli)
# are real Unicode Georgian with genuine Latin words ("EXIT") and must not be converted.
_LEGACY_FONT = re.compile(r"^((acad|lit)(nusx|mtavr)|avaza|avantgardemtavr)", re.IGNORECASE)


def is_legacy_georgian_font(font_name: str | None) -> bool:
    if not font_name:
        return False
    return bool(_LEGACY_FONT.match(font_name.split("+")[-1]))


def to_georgian(text: str) -> str:
    """Decode AcadNusx-style Latin text to Unicode Georgian. Digits/punctuation pass through.

    Capitals without a special meaning (A, B, G, ...) are typed with Shift held by habit and
    draw the same glyph as their lower-case letter, so they fall back to it.
    """
    out = []
    for ch in text:
        if ch in _TO_GEORGIAN:
            out.append(_TO_GEORGIAN[ch])
        elif ch.lower() in _TO_GEORGIAN:
            out.append(_TO_GEORGIAN[ch.lower()])
        else:
            out.append(ch)
    return "".join(out)


def to_acadnusx(text: str) -> str:
    """Encode Unicode Georgian to AcadNusx Latin (used to match Georgian dictionary words)."""
    return "".join(_TO_LATIN.get(ch, ch) for ch in text)


# Informal romanization people use in layer names ("SAXANDZRO", "shenoba") -> AcadNusx.
# Order matters: two-letter sequences first.
_INFORMAL = [("dz", "Z"), ("sh", "S"), ("ch", "C"), ("kh", "x"), ("gh", "R"), ("zh", "J"), ("ts", "c"), ("th", "T")]


def informal_to_acadnusx(text: str) -> str:
    out = text.lower()
    for a, b in _INFORMAL:
        out = out.replace(a, b)
    return out


def folded(words) -> tuple[str, ...]:
    """Keywords folded once, for starts_with / contains."""
    return tuple(fold(w) for w in words)


def starts_with(token: str, keywords: tuple[str, ...]) -> bool:
    """Token begins with one of the (already folded) keywords, in any spelling: "ბინა-01",
    AcadNusx "bina-01" and plain-Latin "Bina-01" all start with "ბინა"."""
    return fold(token).startswith(keywords)


def contains(token: str, keywords: tuple[str, ...]) -> bool:
    t = fold(token)
    return any(k in t for k in keywords)


# Words that are names when typed in Latin: lower-case letters (not codes like "W", "D1"), or a
# capitals word of 3+ letters ("OFFICE", "CORRIDOR" — English plans label rooms in capitals)
# that isn't a drawing code.
LATIN_NAME = re.compile(r"[A-Za-z]*[a-z][A-Za-z]{2,}[,.]?")
CAPS_NAME = re.compile(r"[A-Z]{3,}[,.]?")
DRAWING_CODES = {"EXIT", "DOWN", "UP", "DN", "REF", "TYP", "SIM", "MAX", "MIN", "NTS", "EL", "ELEV.", "SEE", "DET"}


def is_name_word(token: str) -> bool:
    """A room-name word in Georgian script, or in Latin spelling ("sadzinebeli", "Office")."""
    return bool(re.fullmatch(r"[ა-ჰ]{3,}[,.]?", token) or LATIN_NAME.fullmatch(token)
                or (CAPS_NAME.fullmatch(token) and token.rstrip(",.") not in DRAWING_CODES)) or token.lower() == "wc"


def fold(text: str) -> str:
    """Canonical lower-case key for dictionary lookups across all three spellings.

    Unicode Georgian is encoded to AcadNusx, informal digraphs are collapsed, then everything
    is lower-cased — so "კედელი", "kedeli", "KEDELI" and "SAXANDZRO"/"saxanZro" compare equal.
    """
    return informal_to_acadnusx(to_acadnusx(text)).lower()
