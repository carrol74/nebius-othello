from nemothello.errors import AppError
from nemothello.rules import legal_moves
from nemothello.teaching import compare_lesson


def resolve_lesson_view(item, view):
    selected = view["selected_move"] if view else item["actual_move"]
    line = view["line"] if view else []
    comparison = compare_lesson({"evidence": [item]}, item["revision"], selected)
    choice = comparison["choices"][0]
    lines = [choice["frames"], *(defense["frames"] for defense in choice["defense_lines"])]
    frames = next((frames for frames in lines if len(line) < len(frames)
                   and [frame["coordinate"] for frame in frames[1:len(line) + 1]] == line), None)
    if frames is None:
        raise AppError("LESSON_VIEW", "The question must use a displayed teaching line", 422)
    frame = frames[len(line)]
    return {
        "selected_move": selected, "line": line, "board": frame["board"],
        "turn": frame["turn"], "actor": frame["actor"], "flipped": frame["flipped"],
        "legal_moves": list(legal_moves(tuple(frame["board"]), frame["turn"])) if frame["turn"] else [],
        "recorded_move": item["actual_move"] if item.get("is_played", True) else None,
        "assessment": choice["assessment"], "insight": comparison["insight"],
        "teaching": {"insight": comparison["insight"], "choices": [
            {"coordinate": entry["coordinate"], "corner_proof": entry["corner_proof"],
             "continuation_lesson": entry["continuation_lesson"]}
            for entry in comparison["choices"]]},
    }
