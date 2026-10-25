import json
from typing import Any

from nemothello.board_features import CORNERS
from nemothello.coaching import plan_schema, side, validate_plan
from nemothello.concepts import corner_moves, exposed_discs, names
from nemothello.corner_proof import prove_corner
from nemothello.errors import AppError
from nemothello.rules import apply_move, coordinate, flips, legal_moves, opponent, square

MAX_LINE = 8
MAX_REJECTIONS = 3


class ToolInputError(Exception):
    pass


class CoachTools:
    def __init__(self, review: dict[str, Any], context: dict[str, Any]) -> None:
        revisions = {item["revision"] for item in context["positions"] if item["values"]}
        self.roots = {item["revision"]: (tuple(item["analysis"]["board"]), item["actor"])
                      for item in review.get("evidence", review["key_moves"]) if item["revision"] in revisions}
        self.facts: list[dict[str, Any]] = []
        self.trace: list[dict[str, Any]] = []
        self.checked: dict[str, dict[str, Any]] = {}
        self.rejected: set[tuple[str, str]] = set()

    def definitions(self, context: dict[str, Any], answer_only: bool = False) -> list[dict[str, Any]]:
        revision = {"type": "integer", "enum": sorted(self.roots)}
        move = {"type": "string", "pattern": "^[a-h][1-8]$"}
        tools = []
        if self.roots and not answer_only:
            tools.append(function("play_line",
                "Play moves in order from a saved position, starting with the player to move. Passes are "
                "inserted automatically. Each step shows flipped discs, which of them end up next to an empty "
                "square, and any corner the move opens for the other side. Also returns who moves next, their "
                "legal moves, corner moves available to them, and disc counts.",
                {"revision": revision, "moves": {"type": "array", "items": move, "minItems": 1, "maxItems": MAX_LINE}}))
            tools.append(function("check_corner_threat",
                "Check, with the rules engine, whether the opponent can force any empty corner within three "
                "plies after the player's move: the opponent's move, the player's reply, the opponent's move.",
                {"revision": revision, "move": move}))
        tools.append(function("submit_answer",
            "Submit the final answer. Write every number as a {placeholder} from the values and cite the "
            "facts behind each text.", plan_schema(context, self.facts)["properties"]))
        return tools

    def run(self, name: str, raw: str) -> dict[str, Any]:
        try:
            arguments = parse_arguments(raw)
            key = json.dumps([name, arguments], sort_keys=True)
            if key in self.checked:
                fact = self.checked[key]
                return {"fact_id": fact["id"], "note": "Already checked; cite this fact instead of repeating the call.",
                        "text": fact["text"], "values": fact["values"]}
            revision = arguments.get("revision")
            if revision not in self.roots:
                raise ToolInputError(f"Position {revision} is not available; use one of {sorted(self.roots)}")
            if name == "play_line":
                fact = self.play_line(revision, arguments.get("moves"))
            elif name == "check_corner_threat":
                fact = self.check_corner_threat(revision, arguments.get("move"))
            else:
                raise ToolInputError(f"Unknown tool {name}")
        except ToolInputError as exc:
            if (name, raw) in self.rejected:
                return {"error": str(exc), "note": "This exact call already failed; change it or submit."}
            self.rejected.add((name, raw))
            self.trace.append({"name": name, "arguments": raw, "fact_id": None, "error": str(exc)})
            return {"error": str(exc)}
        self.facts.append(fact)
        self.checked[key] = fact
        self.trace.append({"name": name, "arguments": arguments, "fact_id": fact["id"], "error": None})
        return {"fact_id": fact["id"], "text": fact["text"], "values": fact["values"]}

    def new_fact(self, revision: int, text: str, values: dict[str, Any]) -> dict[str, Any]:
        identifier = f"t{len(self.facts) + 1}"
        return {"id": identifier, "text": text, "topic": "tool", "revision": revision,
                "values": {f"{identifier}.{key}": value for key, value in values.items()}}

    def play_line(self, revision: int, moves: Any) -> dict[str, Any]:
        if (not isinstance(moves, list) or not 1 <= len(moves) <= MAX_LINE
                or not all(isinstance(move, str) for move in moves)):
            raise ToolInputError(f"moves must list one to {MAX_LINE} coordinates")
        board, turn = self.roots[revision]
        human = turn
        steps, values = [], {}
        for index, move in enumerate(moves, start=1):
            move = move.lower()
            if turn is None:
                raise ToolInputError(f"The game has ended before {move}")
            legal = legal_moves(board, turn)
            if move not in legal:
                played = " → ".join(moves[:index - 1]) or "the saved position"
                raise ToolInputError(f"{move} is not legal for {side(turn, human)} after {played}; legal moves: {', '.join(legal)}")
            captured = flips(board, turn, move)
            before_corners = corner_moves(board, opponent(turn))
            board = apply_move(board, turn, move)
            flipped = [coordinate(row, col) for row, col in captured]
            exposed = names(exposed_discs(board, captured))
            opened = sorted(corner_moves(board, opponent(turn)) - before_corners)
            steps.append(f"{side(turn, human)}: {move}, flipping {', '.join(flipped)}"
                         + (f" ({', '.join(exposed)} now next to an empty square)" if exposed else " (a quiet move)")
                         + (f"; {side(opponent(turn), human)} can now take {', '.join(opened)}" if opened else ""))
            values.update({f"s{index}.flips": len(flipped), f"s{index}.flipped": flipped,
                           f"s{index}.exposed": len(exposed)})
            following = opponent(turn)
            if legal_moves(board, following):
                turn = following
            elif legal_moves(board, turn):
                steps.append(f"{side(following, human)}: no legal move, must pass")
            else:
                turn = None
        mine = sum(row.count(human) for row in board)
        theirs = sum(row.count(opponent(human)) for row in board)
        values.update({"your_discs": mine, "opponent_discs": theirs})
        if turn is None:
            ending = "Neither player can move, so the game ends."
        else:
            replies = legal_moves(board, turn)
            available = [move for move in replies if move in CORNERS]
            values["replies"] = len(replies)
            if available:
                values["corner_moves"] = available
            ending = (f"Next to move: {side(turn, human)}, with {len(replies)} legal moves: {', '.join(replies)}. "
                      + (f"Corner moves available to {side(turn, human)}: {', '.join(available)}."
                         if available else f"No corner move is available to {side(turn, human)}."))
        text = (f"Line from position {revision}: " + "; ".join(steps) + f". {ending} "
                f"Discs: you {mine}, the opponent {theirs}. This checks one line only; other replies are possible.")
        return self.new_fact(revision, text, values)

    def check_corner_threat(self, revision: int, move: Any) -> dict[str, Any]:
        board, actor = self.roots[revision]
        legal = legal_moves(board, actor)
        if move not in legal:
            raise ToolInputError(f"{move} is not legal at position {revision}; legal moves: {', '.join(legal)}")
        after = apply_move(board, actor, move)
        threats = []
        for target in CORNERS:
            row, col = square(target)
            if after[row][col] == ".":
                proof = prove_corner(after, actor, target)
                if proof["forced"]:
                    threats.append(proof)
        if not threats:
            text = (f"After {move} at position {revision}, the opponent cannot force any empty corner within "
                    f"three plies. This does not prove the corners are safe later.")
            return self.new_fact(revision, text, {})
        lines = [f"the opponent can take {proof['target']} immediately" if proof["attack"] == proof["target"]
                 else f"the opponent can play {proof['attack']}; every reply of yours still lets "
                      f"the opponent take {proof['target']} on the next turn"
                 for proof in threats]
        text = (f"After {move} at position {revision}: " + "; ".join(lines)
                + ". Verified by the rules engine within three plies.")
        return self.new_fact(revision, text, {"threatened": [proof["target"] for proof in threats]})


class CoachSession:
    def __init__(self, review: dict[str, Any], context: dict[str, Any]) -> None:
        self.context = context
        self.tools = CoachTools(review, context)
        self.rejections = 0
        self.plan = None

    def respond(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages = []
        for call in calls:
            name, raw = call["function"]["name"], call["function"]["arguments"]
            if name == "submit_answer":
                try:
                    self.plan = validate_plan(raw, self.context, self.tools.facts)
                except AppError as exc:
                    self.rejections += 1
                    if self.rejections >= MAX_REJECTIONS:
                        raise
                    result = {"error": exc.message, "instruction": "Correct this and call submit_answer again."}
                else:
                    result = {"accepted": True}
            else:
                result = self.tools.run(name, raw)
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, ensure_ascii=False)})
            if self.plan is not None:
                break
        return messages


def function(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "additionalProperties": False,
                       "required": list(properties), "properties": properties},
    }}


def parse_arguments(raw: str) -> dict[str, Any]:
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolInputError("Arguments must be one JSON object") from exc
    if not isinstance(arguments, dict):
        raise ToolInputError("Arguments must be one JSON object")
    return arguments
