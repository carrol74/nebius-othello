import re

from nemothello.coaching import (
    BOARD_LINE,
    CHINESE_NUMBER,
    COORDINATE,
    COORDINATE_RUN,
    ENGLISH_NUMBER,
    ENGLISH_NUMBERS,
    SCORE_WORDS,
    SIDE_NAMES,
    SLOT,
    TERM_FIXES,
    chinese_number,
    strip_citations,
)

MOVE_NUMBER = re.compile(r"第\s*(\d+)\s*[手步]|\bmove\s*#?\s*(\d+)\b", re.IGNORECASE)
LIST_NUMBER = re.compile(r"(?m)^[ \t]*\d+(?:[.)][ \t]+|、[ \t]*)")
POSITION_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_])(?:\{\s*review[_-]([A-Z]+)\s*\}|review[_-]([A-Z]+))(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def render_position_references(text, positions, language):
    references = []

    def move_reference(match):
        identifier = f"review_{(match.group(1) or match.group(2)).upper()}"
        position = positions.get(identifier)
        if position is None:
            return match.group()
        references.append(f"{position['id']}_decision")
        number = position["move_number"]
        return f"第 {number} 手" if language == "Simplified Chinese" else f"move {number}"

    return POSITION_REFERENCE.sub(move_reference, text), references


def prepare_paragraph(text, fact_ids, available, positions, language):
    text = text.replace(r"\r\n", "\n").replace(r"\n", "\n").replace(r"\t", " ")
    text, references = render_position_references(text, positions, language)
    text, inline = strip_citations(text, available)
    text = COORDINATE.sub(lambda match: match.group().lower(), text)
    text = " ".join(LIST_NUMBER.sub("", text).split())
    return text, list(dict.fromkeys([*(identifier.strip() for identifier in fact_ids), *inline, *references]))


def paragraph_problems(text, cited, positions):
    problems = []
    if not text:
        problems.append("The paragraph has no coaching text")
    unresolved = set(SLOT.findall(text)) | {match.group().strip("{} ") for match in POSITION_REFERENCE.finditer(text)}
    for identifier in sorted(unresolved):
        problems.append(f"Unresolved reference {{{identifier}}}; use a supplied position or fact")
    coordinates = {move.lower() for entry in cited for move in COORDINATE.findall(entry["text"])}
    for move in COORDINATE.findall(text):
        if move.lower() not in coordinates:
            problems.append(f"Coordinate {move} is not in the evidence cited by this paragraph")
    move_numbers = {position["move_number"] for position in positions
                    if any(entry.get("revision") == position["revision"] for entry in cited)}
    for match in MOVE_NUMBER.finditer(text):
        value = int(match.group(1) or match.group(2))
        if value not in move_numbers:
            problems.append(f"Move {value} is not a cited game move; cited move numbers are {sorted(move_numbers)}")
    sources = " ".join(COORDINATE.sub("", entry["text"]) for entry in cited)
    allowed = {1, *move_numbers, *(int(value) for value in re.findall(r"\d+", sources))}
    allowed.update(ENGLISH_NUMBERS[word.lower()] for word in ENGLISH_NUMBER.findall(sources))
    bare = COORDINATE.sub("", MOVE_NUMBER.sub("", BOARD_LINE.sub("", LIST_NUMBER.sub("", text))))
    numbers = [(match.group(), int(match.group())) for match in re.finditer(r"\d+", bare)]
    numbers.extend((match.group(), ENGLISH_NUMBERS[match.group().lower()]) for match in ENGLISH_NUMBER.finditer(bare))
    numbers.extend((match.group(), chinese_number(match.group(1))) for match in CHINESE_NUMBER.finditer(bare))
    for written, value in numbers:
        if value not in allowed:
            problems.append(f"Number {written} is not supported by the cited evidence")
    return problems


def paragraph_style_notes(text):
    notes = []
    if COORDINATE_RUN.search(text):
        notes.append("The coordinate list is long; prefer the few squares that explain the lesson")
    if SCORE_WORDS.search(text):
        notes.append("Prefer board consequences to evaluation terminology")
    if SIDE_NAMES.search(text):
        notes.append("Address the player as you and the other side as the opponent")
    for pattern, preferred in TERM_FIXES:
        if pattern.search(text):
            notes.append(f"Prefer the glossary term {preferred}")
    return notes
