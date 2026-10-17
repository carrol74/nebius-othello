import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nemothello.board_features import CORNERS
from nemothello.nemotron import Nemotron
from nemothello.rules import apply_move, legal_moves, opponent


class BlindChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    move: str
    alternative: str
    explanation: str = Field(min_length=1, max_length=1600)
    opponent_replies: int = Field(ge=0, le=64)
    alternative_opponent_replies: int = Field(ge=0, le=64)
    opponent_corner_moves: list[str]
    alternative_opponent_corner_moves: list[str]


def blind_input(item):
    board, turn = tuple(item["analysis"]["board"]), item["actor"]
    moves = list(legal_moves(board, turn))
    if len(moves) < 2:
        raise ValueError("Blind comparison requires at least two legal moves")
    return {"board": list(board), "to_move": turn, "legal_moves": moves,
            "coordinates": "Rows 1-8 top to bottom; columns a-h left to right. X=Black, O=White, .=empty."}


def verify_choice(item, choice: BlindChoice):
    board, turn = tuple(item["analysis"]["board"]), item["actor"]
    candidates = {candidate["coordinate"]: candidate for candidate in item["analysis"]["candidates"]}
    best_score = max(candidate["score"] for candidate in candidates.values())
    best_moves = sorted(move for move, candidate in candidates.items() if candidate["score"] == best_score)
    checks = [{"claim": "distinct_alternative", "correct": choice.move != choice.alternative}]
    for move, count, corners, prefix in (
        (choice.move, choice.opponent_replies, choice.opponent_corner_moves, "selected"),
        (choice.alternative, choice.alternative_opponent_replies, choice.alternative_opponent_corner_moves, "alternative"),
    ):
        valid = move in legal_moves(board, turn)
        checks.append({"claim": f"{prefix}_legal", "model": move, "correct": valid})
        if valid:
            replies = legal_moves(apply_move(board, turn, move), opponent(turn))
            expected_corners = sorted(set(replies) & set(CORNERS))
            checks.extend([
                {"claim": f"{prefix}_reply_count", "model": count, "actual": len(replies), "correct": count == len(replies)},
                {"claim": f"{prefix}_corner_replies", "model": corners, "actual": expected_corners,
                 "correct": sorted(corners) == expected_corners},
            ])
    score = candidates.get(choice.move, {}).get("score")
    return {"model_choice": choice.model_dump(), "engine_best_moves": best_moves,
            "engine_best_score": best_score, "model_move_score": score,
            "score_gap": None if score is None else best_score - score,
            "matches_best_score": score == best_score, "checks": checks,
            "all_checked_claims_correct": all(check["correct"] for check in checks),
            "free_text_explanation_status": "Not automatically verified; inspect against the board and checked claims",
            "engine_score_kind": item["analysis"]["score_kind"],
            "engine_settings": item["analysis"]["settings"]}


def evaluate_blind(model: Nemotron, evidence, revisions, output: Path):
    if output.exists():
        raise ValueError("Output already exists; use a new path to preserve paid-call evidence")
    if not 1 <= len(revisions) <= 8 or len(revisions) != len(set(revisions)):
        raise ValueError("Choose one to eight distinct revisions")
    selected = [next(item for item in evidence if item["revision"] == revision) for revision in revisions]
    inputs = [blind_input(item) for item in selected]
    model.ensure_configured()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"model_id": model.model_id, "input_contract": "Board, side to move, legal moves only; no engine scores, recommendations, history or result",
              "max_calls": len(revisions), "calls": []}
    for item, payload in zip(selected, inputs):
        call = {"revision": item["revision"], "actor": item["actor"], "input": payload, "status": "started"}
        report["calls"].append(call)
        output.write_text(json.dumps(report, indent=2) + "\n")
        schema = BlindChoice.model_json_schema()
        for key in ("move", "alternative"):
            schema["properties"][key]["enum"] = payload["legal_moves"]
        started = time.monotonic()
        response = model.http.post("chat/completions", json={
            "model": model.model_id, "temperature": 0, "max_tokens": 650,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "blind_choice", "strict": True, "schema": schema}},
            "messages": [
                {"role": "system", "content": "Choose the strongest Othello move independently from the board. You have no engine evaluation. Compare with a different legal alternative. Explain your choice in concise English. Also calculate the exact number of legal opponent replies and list all immediately available opponent corner moves after each of the two choices. Apply all flips before counting. These factual claims will be checked separately from playing strength. Return only the required JSON object."},
                {"role": "user", "content": json.dumps(payload)},
            ],
        })
        call.update(elapsed_ms=round((time.monotonic() - started) * 1000, 2), http_status=response.status_code)
        response.raise_for_status()
        result = response.json()
        call["usage"] = result.get("usage")
        call["raw_choice"] = result["choices"][0]["message"]["content"]
        call["finish_reason"] = result["choices"][0].get("finish_reason")
        output.write_text(json.dumps(report, indent=2) + "\n")
        try:
            if call["finish_reason"] == "length":
                raise ValueError("Model output was truncated")
            choice = BlindChoice.model_validate_json(call["raw_choice"])
            call.update(status="checked", verification=verify_choice(item, choice))
        except (ValidationError, ValueError) as error:
            call.update(status="invalid", error=str(error))
        output.write_text(json.dumps(report, indent=2) + "\n")
    report["prompt_tokens"] = sum((call.get("usage") or {}).get("prompt_tokens", 0) for call in report["calls"])
    report["completion_tokens"] = sum((call.get("usage") or {}).get("completion_tokens", 0) for call in report["calls"])
    report["estimated_usd_at_user_quoted_rate"] = (report["prompt_tokens"] * .06 + report["completion_tokens"] * .24) / 1_000_000
    report["rate_note"] = "User-quoted rate, not a provider invoice"
    checks = [call["verification"] for call in report["calls"] if "verification" in call]
    report["summary"] = {"complete_responses": len(checks),
                         "matches_best_score": sum(check["matches_best_score"] for check in checks),
                         "all_checked_claims_correct": sum(check["all_checked_claims_correct"] for check in checks),
                         "invalid_responses": sum(call["status"] == "invalid" for call in report["calls"])}
    report["scope"] = "Small diagnostic sample; not a playing-strength benchmark. Non-exact engine scores are search estimates. Free-text explanations need separate review."
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report
