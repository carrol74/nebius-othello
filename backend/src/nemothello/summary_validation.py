import re

from nemothello.coaching import (
    BOARD_LINE,
    CHINESE_NUMBER,
    CITATION,
    CJK,
    COORDINATE,
    COORDINATE_RUN,
    ENGLISH_NUMBER,
    ENGLISH_NUMBERS,
    IDENTIFIER,
    LATIN_WORD,
    NAMES,
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


# Chinese drafts often wrap a placeholder as 第{review_A}手, which would otherwise read 第第 3 手手
CHINESE_REFERENCE = re.compile(r"(?:第\s*)?" + POSITION_REFERENCE.pattern + r"(?:\s*[手步])?", re.IGNORECASE)
BRACED_COORDINATE = re.compile(r"\{\s*([a-h][1-8])\s*\}", re.IGNORECASE)


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

    pattern = CHINESE_REFERENCE if language == "Simplified Chinese" else POSITION_REFERENCE
    return pattern.sub(move_reference, text), references


FACT_ID = re.compile(r"[A-Za-z]+(?:_[A-Za-z0-9]+)+")


def drop_fact_citations(text, available):
    # A citation is not prose, so one unknown ID drops the whole bracket instead of costing a retry
    cited = []

    def replace(match):
        identifiers = [item.strip() for item in re.split(r"[,，]", match.group(1))]
        # Braces hold move references, which must resolve rather than vanish
        if match.group().lstrip()[0] == "{" or not all(FACT_ID.fullmatch(identifier) for identifier in identifiers):
            return match.group()
        cited.extend(identifier for identifier in identifiers if identifier in available)
        return ""

    return CITATION.sub(replace, text), cited


def prepare_paragraph(text, fact_ids, available, positions, language):
    text = text.replace(r"\r\n", "\n").replace(r"\n", "\n").replace(r"\t", " ")
    # A coordinate is not a placeholder, so braces around one are dropped instead of costing a retry
    text = BRACED_COORDINATE.sub(r"\1", text)
    text, references = render_position_references(text, positions, language)
    text, inline = strip_citations(text, available)
    text, dropped = drop_fact_citations(text, available)
    text = COORDINATE.sub(lambda match: match.group().lower(), text)
    text = " ".join(LIST_NUMBER.sub("", text).split())
    return text, list(dict.fromkeys([*(identifier.strip() for identifier in fact_ids), *inline, *dropped, *references]))


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


# Common wording slips, fixed in place instead of costing a retry
PLAIN_TERMS = ((re.compile("中游|中局"), "中盘"), (re.compile("末局|残局"), "终局"), (re.compile("玩家|您"), "你"),
               (re.compile("与搜索一致"), "与推荐一致"),
               (re.compile("(?:\\s*Edax\\s*|搜索)(?:推荐的?)?最佳(?:走法)?|(?:\\s*Edax\\s*|搜索)推荐"), "推荐"))
SENTENCE = re.compile(r"[^。！？.!?]+[。！？.!?]*")


def replace_terms(text, language):
    if language != "Simplified Chinese":
        return text
    for pattern, term in PLAIN_TERMS:
        text = pattern.sub(term, text)
    text = re.sub(r"\s*第\s*([a-h][1-8])\s*[步手]", r" \1 这一步", text)
    # Filled-in move numbers keep the spaces the model put around its placeholders
    text = re.sub(r"(?<=[\u4e00-\u9fff，。、；])\s+(?=第 \d+ 手)", "", text)
    return re.sub(r"(第 \d+ 手)\s+(?=[\u4e00-\u9fff，。、；])", r"\1", text)


def question_only(text):
    questions = [sentence.strip() for sentence in SENTENCE.findall(text) if sentence.strip().endswith(("?", "？"))]
    return questions[-1] if questions else None


def presentation_problems(text, language):
    problems = []
    if language == "Simplified Chinese" and CJK.search(text):
        for match in LATIN_WORD.finditer(COORDINATE.sub(" ", text)):
            if match.group() not in NAMES:
                problems.append(f"The summary mixes in the English word {match.group()}; write it in plain Chinese")
    for match in IDENTIFIER.finditer(text):
        problems.append(f"The summary shows the field name {match.group()}; write plain words")
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
