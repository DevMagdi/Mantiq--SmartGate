"""Egyptian licence-plate rules: transliteration, parsing and fuzzy variants.

Egyptian plates mix Arabic letters with Western or Arabic-Indic digits, e.g.
``أ ب ج ١٢٣٤`` or ``ABC 1234`` with a governorate code.  Cameras in the field
also see Latin transliterations on private and diplomatic plates, so the
canonical form used for storage stays Latin-ish while Arabic readings are
transliterated into extra *lookup variants* at match time.

This module has no database or model dependencies: it is pure string/geometry
logic so it can be unit-tested exhaustively.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

# --------------------------------------------------------------------------- #
# Character normalisation
# --------------------------------------------------------------------------- #

ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
EXTENDED_ARABIC_INDIC_DIGITS = "۰۱۲۳۴۵۶۷۸۹"

_DIGIT_TRANSLATION: dict[int, str] = {
    **{ord(ch): str(index) for index, ch in enumerate(ARABIC_INDIC_DIGITS)},
    **{ord(ch): str(index) for index, ch in enumerate(EXTENDED_ARABIC_INDIC_DIGITS)},
}

# Egyptian plates use a subset of the Arabic alphabet.  The values mirror the
# Latin letters printed on the same plate when the owner orders a "Latin"
# variant, which is what ANPR models are trained on.
ARABIC_TO_LATIN: dict[str, str] = {
    "ا": "A",
    "أ": "A",
    "إ": "A",
    "آ": "A",
    "ٱ": "A",
    "ب": "B",
    "ت": "T",
    "ث": "T",
    "ج": "G",
    "ح": "H",
    "خ": "K",
    "د": "D",
    "ذ": "Z",
    "ر": "R",
    "ز": "Z",
    "س": "S",
    "ش": "S",
    "ص": "S",
    "ض": "D",
    "ط": "T",
    "ظ": "Z",
    "ع": "A",
    "غ": "G",
    "ف": "F",
    "ق": "Q",
    "ك": "K",
    "ل": "L",
    "م": "M",
    "ن": "N",
    "ه": "H",
    "ة": "T",
    "و": "W",
    "ي": "Y",
    "ى": "Y",
    "ء": "A",
}

# Latin letters that do not appear on Egyptian plates are mapped to the closest
# legal letter so OCR noise (``V`` instead of ``Y``) still resolves.
_LATIN_FALLBACK = str.maketrans(
    {
        "V": "Y",
        "U": "W",
        "O": "W",
        "X": "K",
        "C": "K",
        "P": "B",
        "J": "G",
    }
)

ARABIC_RANGE = re.compile(r"[\u0600-\u06FF]")
_KEEP = re.compile(r"[^A-Z0-9\u0600-\u06FF]")
_LETTER_GROUP = re.compile(r"[A-Z\u0600-\u06FF]+")
_DIGIT_GROUP = re.compile(r"\d+")

# Governorate codes used in the API/UI (Latin only).  The key is the Arabic
# letter group sometimes read from the plate.
GOVERNORATE_CODES: dict[str, str] = {
    "القاهرة": "CAI",
    "الجيزة": "GZ",
    "الإسكندرية": "ALX",
    "الدقهلية": "DK",
    "الشرقية": "SHR",
    "القليوبية": "KB",
    "المنوفية": "MNF",
    "الغربية": "GH",
    "البحيرة": "BH",
    "كفر الشيخ": "KFS",
    "دمياط": "DT",
    "بورسعيد": "PTS",
    "الإسماعيلية": "IS",
    "السويس": "SUZ",
    "شمال سيناء": "NSN",
    "جنوب سيناء": "SSN",
    "الفيوم": "FYM",
    "بني سويف": "BNS",
    "المنيا": "MNA",
    "أسيوط": "AST",
    "سوهاج": "SHG",
    "قنا": "QNA",
    "الأقصر": "LXR",
    "أسوان": "ASW",
    "البحر الأحمر": "RSA",
    "الوادي الجديد": "WAD",
    "مطروح": "MT",
}

LATIN_GOVERNORATE_CODES: frozenset[str] = frozenset(GOVERNORATE_CODES.values())

# OCR confusions seen on Egyptian plates.  Applied both ways when building
# lookup variants and when scoring fuzzy matches.
DIGIT_LETTER_CONFUSIONS: dict[str, str] = {
    "0": "O",
    "1": "I",
    "2": "Z",
    "4": "A",
    "5": "S",
    "6": "G",
    "7": "T",
    "8": "B",
}
LETTER_DIGIT_CONFUSIONS: dict[str, str] = {
    "O": "0",
    "Q": "0",
    "D": "0",
    "I": "1",
    "L": "1",
    "Z": "2",
    "A": "4",
    "S": "5",
    "G": "6",
    "T": "7",
    "B": "8",
}

MIN_PLATE_LENGTH = 3
MAX_PLATE_LENGTH = 12
MAX_VARIANTS = 32


# --------------------------------------------------------------------------- #
# Cleaning / transliteration
# --------------------------------------------------------------------------- #


def strip_diacritics(text: str) -> str:
    """Remove Arabic diacritics and tatweel so ``أَ`` and ``ا`` compare equal."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.replace("\u0640", "")  # tatweel


def clean_plate_text(raw: str) -> str:
    """Uppercase, drop separators and normalise Arabic-Indic digits.

    Arabic letters are preserved so the canonical key keeps what the camera
    actually saw; :func:`transliterate_plate` produces the Latin alias.
    """
    text = strip_diacritics(raw or "").translate(_DIGIT_TRANSLATION).upper()
    return _KEEP.sub("", text).strip()


def transliterate_plate(text: str | None) -> str:
    """Convert Arabic letters to their Latin counterparts (``ب ج ١٢٣٤`` → ``BG1234``)."""
    cleaned = clean_plate_text(text or "")
    if not cleaned:
        return ""
    latin = "".join(ARABIC_TO_LATIN.get(ch, ch) for ch in cleaned)
    return _KEEP.sub("", latin)


def has_arabic(text: str | None) -> bool:
    """Return ``True`` when the string still contains Arabic script."""
    return bool(text and ARABIC_RANGE.search(text))


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PlateParse:
    """Structured view of a plate reading."""

    raw: str
    canonical: str
    latin: str
    letters: str
    digits: str
    style: str
    governorate: str | None = None

    @property
    def is_valid(self) -> bool:
        return bool(self.letters) and bool(self.digits) and len(self.canonical) >= MIN_PLATE_LENGTH

    @property
    def digit_count(self) -> int:
        return len(self.digits)

    @property
    def letter_count(self) -> int:
        return len(self.letters)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "canonical": self.canonical,
            "latin": self.latin,
            "letters": self.letters,
            "digits": self.digits,
            "style": self.style,
            "governorate": self.governorate,
        }


def parse_plate(text: str | None) -> PlateParse:
    """Split a plate reading into its letter and digit groups.

    Egyptian plates are usually printed as ``ABC 1234`` (letters first) or
    ``1234 ABC`` (digits first); both are recognised, plus mixed layouts used
    by older and diplomatic plates.
    """
    canonical = clean_plate_text(text or "")
    latin = transliterate_plate(canonical)
    letters = "".join(_LETTER_GROUP.findall(canonical))
    digits = "".join(_DIGIT_GROUP.findall(canonical))
    latin_letters = "".join(_LETTER_GROUP.findall(latin))
    latin_digits = "".join(_DIGIT_GROUP.findall(latin))
    style = "unknown"
    if latin:
        first_is_letter = bool(latin[0].isalpha())
        last_is_digit = bool(latin[-1].isdigit())
        if first_is_letter and last_is_digit:
            style = "letters-first"
        elif not first_is_letter and not last_is_digit:
            style = "digits-first"
        elif first_is_letter:
            style = "letters-mixed"
        else:
            style = "digits-mixed"
    governorate = None
    for name, code in GOVERNORATE_CODES.items():
        if name in (text or ""):
            governorate = code
            break
    if governorate is None:
        upper = latin_letters
        for code in LATIN_GOVERNORATE_CODES:
            if len(code) >= 3 and code in upper:
                governorate = code
                break
    return PlateParse(
        raw=text or "",
        canonical=canonical,
        latin=clean_plate_text(latin) if latin else "",
        letters=latin_letters or letters,
        digits=latin_digits or digits,
        style=style,
        governorate=governorate,
    )


# --------------------------------------------------------------------------- #
# Canonical key and lookup variants
# --------------------------------------------------------------------------- #


def normalize_plate(text: str | None) -> str:
    """Canonical identity key (keeps letters, strips separators and spaces)."""
    return clean_plate_text(text or "")


def _swap_halves(value: str) -> str | None:
    """Return the plate with its letter/digit groups swapped (``1234ABC``)."""
    letters = "".join(_LETTER_GROUP.findall(value))
    digits = "".join(_DIGIT_GROUP.findall(value))
    if not letters or not digits:
        return None
    if len(letters) + len(digits) != len(value):
        return None  # interleaved layout, swapping is meaningless
    swapped = f"{digits}{letters}"
    return swapped if swapped != value else None


def _confusion_variants(base: str, limit: int) -> list[str]:
    """Breadth-first expansion of ambiguous characters, capped at ``limit``."""
    results: list[str] = []
    queue: list[tuple[str, int]] = [(base, 0)]
    seen = {base}
    while queue and len(results) < limit:
        value, index = queue.pop(0)
        if index >= len(value):
            results.append(value)
            continue
        char = value[index]
        alternatives = []
        if char.isdigit() and char in DIGIT_LETTER_CONFUSIONS:
            alternatives.append(DIGIT_LETTER_CONFUSIONS[char])
        if char.isalpha() and char in LETTER_DIGIT_CONFUSIONS:
            alternatives.append(LETTER_DIGIT_CONFUSIONS[char])
        # Always explore the unchanged branch first so the original is kept.
        queue.append((value, index + 1))
        for alternative in alternatives:
            candidate = value[:index] + alternative + value[index + 1 :]
            if candidate in seen:
                continue
            seen.add(candidate)
            queue.append((candidate, index + 1))
    return results[:limit]


def plate_variants(text: str | None, *, max_variants: int = MAX_VARIANTS) -> set[str]:
    """Return every key that should be compared against stored plates.

    The set always contains the canonical key.  It also contains:

    * the Latin transliteration of Arabic readings,
    * the letter/digit swap (cameras read ``1234 ABC`` as ``ABC1234``),
    * systematic OCR-confusion expansions (``0``↔``O``, ``1``↔``I``, …).
    """
    base = normalize_plate(text)
    if not base:
        return set()
    variants: set[str] = {base}
    latin = transliterate_plate(base)
    if latin and latin != base:
        variants.add(latin)
    for candidate in list(variants):
        swapped = _swap_halves(candidate)
        if swapped:
            variants.add(swapped)
    # Expand the most useful keys first (Latin form is the usual stored shape).
    ordered = [latin or base, base, *sorted(variants - {base, latin})]
    budget = max(1, max_variants - len(variants))
    for candidate in ordered:
        if len(variants) >= max_variants:
            break
        variants.update(_confusion_variants(candidate, budget))
        budget = max(1, max_variants - len(variants))
    return {variant for variant in variants if len(variant) >= MIN_PLATE_LENGTH}


# --------------------------------------------------------------------------- #
# Display
# --------------------------------------------------------------------------- #


def format_plate(text: str | None) -> str:
    """Return a human-friendly plate (``cai-4821`` → ``CAI 4821``)."""
    cleaned = clean_plate_text(text or "")
    tokens = re.findall(r"[A-Z\u0600-\u06FF]+|\d+", cleaned)
    return " ".join(tokens) if tokens else cleaned


def format_plate_latin(text: str | None) -> str:
    """Always render the Latin form (used in exports and SMS/WhatsApp alerts)."""
    return format_plate(transliterate_plate(text))


def plate_display(text: str | None, *, latin: bool = False) -> str:
    """Display helper that tolerates ``None``."""
    if not text:
        return ""
    return format_plate_latin(text) if latin else format_plate(text)


# --------------------------------------------------------------------------- #
# Validation and similarity
# --------------------------------------------------------------------------- #


def valid_plate_candidate(
    text: str,
    *,
    min_length: int = MIN_PLATE_LENGTH,
    max_length: int = MAX_PLATE_LENGTH,
) -> bool:
    """Reject obviously malformed OCR output."""
    cleaned = clean_plate_text(text)
    if not (min_length <= len(cleaned) <= max_length):
        return False
    digits = sum(ch.isdigit() for ch in cleaned)
    letters = sum(ch.isalpha() for ch in cleaned)
    if digits < 1 or letters < 1:
        return False
    # Arabic digits are already normalised, so ``digits`` counts both scripts.
    return digits <= 6 and letters <= 5


def levenshtein(left: str, right: str) -> int:
    """Classic edit distance (small strings, no external dependency)."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            substitute = previous[j - 1] + (left_char != right_char)
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]


def plate_similarity(left: str | None, right: str | None) -> float:
    """Similarity in ``[0, 1]`` between two plate readings.

    Used for "did you mean" hints in the registry and for detecting duplicate
    enrolments; matching itself always uses :func:`plate_variants`.
    """
    a = normalize_plate(left)
    b = normalize_plate(right)
    if not a or not b:
        return 0.0
    a, b = a.translate(_LATIN_FALLBACK), b.translate(_LATIN_FALLBACK)
    distance = levenshtein(a, b)
    return max(0.0, 1.0 - distance / max(len(a), len(b)))


def best_plate_match(
    text: str | None,
    candidates: Iterable[str],
    *,
    threshold: float = 0.82,
) -> tuple[str, float] | None:
    """Return the closest candidate above ``threshold`` (for suggestions only)."""
    scored: list[tuple[str, float]] = [
        (candidate, plate_similarity(text, candidate)) for candidate in candidates
    ]
    if not scored:
        return None
    best = max(scored, key=lambda item: item[1])
    return best if best[1] >= threshold else None


def quality_score(confidence: float, parse: PlateParse) -> float:
    """Blend model confidence with plate plausibility (0–100).

    A confident OCR result that violates the Egyptian layout (e.g. seven
    letters) is still suspicious, so the score is reduced.
    """
    score = max(0.0, min(1.0, float(confidence))) * 100.0
    if not parse.is_valid:
        score *= 0.5
    elif not (2 <= parse.letter_count <= 4 and 1 <= parse.digit_count <= 5):
        score *= 0.85
    if parse.style in {"letters-first", "digits-first"}:
        score = min(100.0, score + 2.0)
    return round(score, 2)


def describe_plate(text: str | None) -> dict[str, str | float | bool | None]:
    """Debug-friendly summary used by the CV status and analysis endpoints."""
    parse = parse_plate(text)
    return {
        **parse.as_dict(),
        "display": format_plate(text) if text else None,
        "valid": parse.is_valid,
        "has_arabic": has_arabic(text),
        "variants": len(plate_variants(text)) if text else 0,
    }


def merge_plate_readings(readings: Sequence[str]) -> str | None:
    """Pick the most frequent reading among OCR passes (majority vote)."""
    counts: dict[str, int] = {}
    for reading in readings:
        cleaned = normalize_plate(reading)
        if cleaned:
            counts[cleaned] = counts.get(cleaned, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: (item[1], len(item[0])))[0]
