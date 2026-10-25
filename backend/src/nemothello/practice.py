import json
from functools import lru_cache
from pathlib import Path

from nemothello.data import canonical_board
from nemothello.errors import AppError
from nemothello.reply_practice import grade_reply
from nemothello.rules import Position, flips, legal_moves, opponent
from nemothello.teaching import capture_lines


def position_key(board):
    swapped = tuple(row.translate(str.maketrans("XO", "OX")) for row in board)
    return min(canonical_board(tuple(board)), canonical_board(swapped))


def practice_position(moves, ply):
    position, history = Position(), []
    for move in moves[:ply]:
        actor = position.turn
        captured = [f"{chr(97 + c)}{r + 1}" for r, c in flips(position.board, actor, move)]
        position, _ = position.play(move)
        history.append({"actor": actor, "coordinate": move, "flipped": captured})
    return position, history


def answer_lines(position, context, objective):
    if position.turn is None:
        return []
    gains = {context[0]["coordinate"], *context[0]["flipped"]}
    if objective == "anchor" and (len(context) != 2 or context[0]["actor"] != position.turn
                                  or context[1]["actor"] != opponent(position.turn)):
        return []
    if objective == "recapture" and context[0]["actor"] != opponent(position.turn):
        return []
    result = []
    for move in position.moves:
        for ray in capture_lines(position.board, position.turn, move):
            if (objective == "reply" or objective == "anchor" and ray[-1] in gains
                    or objective == "recapture" and gains.intersection(ray[1:-1])):
                result.append(ray)
    return result


@lru_cache
def practice_bank():
    return json.loads(Path(__file__).with_name("practice-bank.json").read_text())


def case_position(case, bank):
    position, history = practice_position(bank["games"][case["game_index"]]["moves"], case["ply"])
    context = history[-2:] if case["objective"] == "anchor" else history[-1:]
    return position, context


def grade_practice(question, move, anchor, alternative=None):
    if question["objective"] == "reply_access":
        if alternative is None or anchor is not None:
            raise AppError("PRACTICE_PAIR", "Choose a blocking move and a comparison move", 422)
        return grade_reply(question, move, alternative)
    if anchor is None or alternative is not None:
        raise AppError("PRACTICE_ANCHOR", "Choose the disc at the other end of the capture", 422)
    position = Position(tuple(question["board"]), question["turn"])
    lines = answer_lines(position, question["context"], question["objective"])
    if not lines:
        raise AppError("PRACTICE_DATA", "This exercise has no rule-verified answer", 500)
    move_lines = [line for line in lines if line[0] == move]
    matched = next((line for line in move_lines if line[-1] == anchor), None)
    explanation = matched or next(iter(move_lines), lines[0])
    return {"legal": move in legal_moves(position.board, position.turn),
            "move_matches_goal": bool(move_lines), "anchor_matches": matched is not None,
            "capture_line": explanation, "reason_reviewed": False,
            "rubric_version": question["rubric_version"]}
