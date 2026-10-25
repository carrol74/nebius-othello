from typing import Any

from nemothello.board_features import CORNERS
from nemothello.rules import (
    DIRECTIONS,
    apply_move,
    coordinate,
    flips,
    legal_moves,
    opponent,
    square,
)

AXES = ((0, 1), (1, 0), (1, 1), (1, -1))
ENDGAME_EMPTIES = 16


def inside(row: int, col: int) -> bool:
    return 0 <= row < 8 and 0 <= col < 8


def touches_empty(board, row: int, col: int) -> bool:
    return any(inside(row + dr, col + dc) and board[row + dr][col + dc] == "." for dr, dc in DIRECTIONS)


def line_full(board, row: int, col: int, axis: tuple[int, int]) -> bool:
    for sign in (1, -1):
        r, c = row + sign * axis[0], col + sign * axis[1]
        while inside(r, c):
            if board[r][c] == ".":
                return False
            r, c = r + sign * axis[0], c + sign * axis[1]
    return True


def stable_discs(board, color: str) -> set[tuple[int, int]]:
    # A disc is stable when every axis is full or blocked on one side by the wall or a stable own disc.
    stable: set[tuple[int, int]] = set()
    changed = True
    while changed:
        changed = False
        for row in range(8):
            for col in range(8):
                if board[row][col] != color or (row, col) in stable:
                    continue
                if all(line_full(board, row, col, axis) or any(
                        not inside(row + sign * axis[0], col + sign * axis[1])
                        or (row + sign * axis[0], col + sign * axis[1]) in stable
                        for sign in (1, -1)) for axis in AXES):
                    stable.add((row, col))
                    changed = True
    return stable


def empty_regions(board) -> list[set[tuple[int, int]]]:
    remaining = {(row, col) for row in range(8) for col in range(8) if board[row][col] == "."}
    regions = []
    while remaining:
        stack = [remaining.pop()]
        region = set(stack)
        while stack:
            row, col = stack.pop()
            for dr, dc in DIRECTIONS:
                neighbor = (row + dr, col + dc)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    region.add(neighbor)
                    stack.append(neighbor)
        regions.append(region)
    return regions


def names(cells) -> list[str]:
    return sorted(coordinate(row, col) for row, col in cells)


def exposed_discs(after, flipped) -> list[tuple[int, int]]:
    # Edge discs are not counted as frontier, following standard Othello teaching.
    return [(row, col) for row, col in flipped
            if row not in (0, 7) and col not in (0, 7) and touches_empty(after, row, col)]


def corner_moves(board, color: str) -> set[str]:
    return set(legal_moves(board, color)) & set(CORNERS)


def concept_profile(board, actor: str, move: str) -> dict[str, Any]:
    other = opponent(actor)
    after = apply_move(board, actor, move)
    flipped = flips(board, actor, move)
    inner = [(row, col) for row, col in flipped if row not in (0, 7) and col not in (0, 7)]
    exposed = exposed_discs(after, flipped)
    already = corner_moves(after, actor)
    replies = legal_moves(after, other)
    unsafe = [reply for reply in replies if reply not in CORNERS
              and corner_moves(apply_move(after, other, reply), actor) - already]
    gained = stable_discs(after, actor) - stable_discs(board, actor)
    profile = {"move": move, "inner_flips": len(inner), "exposed": names(exposed), "replies": list(replies),
               "unsafe_replies": unsafe, "safe_replies": [reply for reply in replies if reply not in unsafe],
               "stable_gained": names(gained), "region": None}
    empties = sum(row.count(".") for row in board)
    if empties <= ENDGAME_EMPTIES:
        region = next(region for region in empty_regions(board) if square(move) in region)
        profile["region"] = len(region)
    return profile


def concept_differences(worse: dict[str, Any], better: dict[str, Any]) -> list[tuple[str, float]]:
    ranked = []
    exposed = len(worse["exposed"]) - len(better["exposed"])
    if exposed >= 2:
        ranked.append(("quiet", exposed / len(worse["exposed"])))
    safe = len(worse["safe_replies"]) - len(better["safe_replies"])
    if safe >= 2 or (safe >= 1 and not better["safe_replies"]):
        ranked.append(("mobility", safe / len(worse["safe_replies"])))
    stable = len(better["stable_gained"]) - len(worse["stable_gained"])
    if stable >= 1:
        ranked.append(("stable", stable / len(better["stable_gained"])))
    if worse["region"] and better["region"] and better["region"] % 2 == 1 and worse["region"] % 2 == 0:
        ranked.append(("parity", 0.5))
    return sorted(ranked, key=lambda entry: -entry[1])


def concept_focus(profiles: dict[str, dict[str, Any]], worse: str | None, better: str) -> list[str]:
    if worse is not None:
        return [name for name, _ in concept_differences(profiles[worse], profiles[better])][:2]
    profile = profiles[better]
    notable = []
    if profile["stable_gained"]:
        notable.append("stable")
    if profile["inner_flips"] and not profile["exposed"]:
        notable.append("quiet")
    if not profile["safe_replies"] and profile["replies"]:
        notable.append("mobility")
    return notable[:2]


def listed(moves: list[str]) -> str:
    return ", ".join(moves) if moves else "none"


def concept_facts(profiles: dict[str, dict[str, Any]], moves: list[str], revision: int):
    values = {}
    for move in moves:
        profile = profiles[move]
        key = f"p{revision}.{move}"
        values.update({f"{key}.exposed": len(profile["exposed"]), f"{key}.safe_replies": len(profile["safe_replies"]),
                       f"{key}.stable_gained": len(profile["stable_gained"])})
        if profile["region"]:
            values[f"{key}.region"] = profile["region"]
    quiet = [f"{move} flips only edge discs." if not profiles[move]["inner_flips"] else
             f"Every disc {move} flips away from the edge is surrounded by discs, so {move} is a quiet move."
             if not profiles[move]["exposed"] else
             f"{move} flips discs that then touch an empty square: {listed(profiles[move]['exposed'])}. "
             "The opponent may later play on such an empty square to flip them back."
             for move in moves]
    safety = [f"After {move}, the opponent has {len(profiles[move]['replies'])} legal replies, "
              f"{len(profiles[move]['safe_replies'])} of them safe"
              + (f"; {listed(profiles[move]['unsafe_replies'])} would let you take a corner."
                 if profiles[move]["unsafe_replies"] else ".")
              for move in moves]
    facts = [
        {"id": f"p{revision}:quiet", "text": " ".join(quiet) + " Discs on the edge are not counted.",
         "topic": "quiet_move", "revision": revision},
        {"id": f"p{revision}:mobility", "text": " ".join(safety) + " A reply is unsafe for the opponent when it "
         "lets you take a corner you could not take before. Reply count alone does not decide the move.",
         "topic": "mobility", "revision": revision},
    ]
    lessons = ["quiet_move", "mobility"]
    if any(profiles[move]["stable_gained"] for move in moves):
        stable = [f"After {move}, these of your discs can never be flipped again: {listed(profiles[move]['stable_gained'])}."
                  if profiles[move]["stable_gained"] else f"{move} makes none of your discs permanently safe."
                  for move in moves]
        facts.append({"id": f"p{revision}:stable", "text": " ".join(stable), "topic": "stable_discs", "revision": revision})
        lessons.append("stable_discs")
    if all(profiles[move]["region"] for move in moves):
        regions = "; ".join(f"{move} is in a region of {profiles[move]['region']} empty squares" for move in moves)
        facts.append({"id": f"p{revision}:parity", "text": f"Before your move, {regions}. A region is a group of "
                      "touching empty squares.", "topic": "parity", "revision": revision})
        lessons.append("parity")
    return facts, lessons, values
