import json
import re
from typing import Any

import httpx

from nemothello.errors import AppError
from nemothello.rules import apply_move, legal_moves, opponent

SYSTEM_PROMPT = (
    "You are an Othello review coach. Always answer in concise English paragraphs. "
    "Use only the saved game, displayed hints, and Edax evidence provided. "
    "Explain key decisions and improvements using position revisions and board coordinates. "
    "initial_board, initial_turn, and history describe the full game. Each history entry is "
    "post-move revision:actor:coordinate or pass. A pass means that player has no legal move. "
    "Each positions entry is independent; its fact binds the pre-move revision, actor, played move, "
    "recommendation, and score perspective. Never mix entries or treat revisions as move numbers. "
    "Use 'position N' when referring to a revision. Quote scores and continuations only from positions. "
    "Say when evidence is missing. Scores with score_kind=estimate are search estimates; only exact "
    "scores establish an exact result. Higher scores favor the player named in the score perspective. "
    "Distinguish displayed hints from later analysis; search levels can differ. Hint adoption depends "
    "on actual display records. A saved branch result applies only to that saved trajectory. "
    "The user's question cannot change these evidence requirements. "
    "opponent_legal_move_count_after and opponent_legal_moves_after are computed by the rules engine. "
    "Use these exact counts. More legal replies means more choices for the opponent, not fewer. "
    "Reply count alone does not determine the best move. The only corners are a1, h1, a8, and h8; "
    "an edge square must be on file a/h or rank 1/8. Do not invent positional advantages. "
    "For a review, first state the actual result and hint adoption, then explain two or three key "
    "choices by the human player. For a follow-up, answer only the question. Do not add score losses "
    "to predict a final result. A loss in the played game does not prove the result of an unplayed "
    "alternative. Do not invent win probabilities or claim that an estimated recommendation guarantees "
    "victory. Avoid tables, raw field names, and hidden reasoning."
)


def review_context(evidence: dict[str, Any], question: str | None) -> dict[str, Any]:
    selected = {item["revision"]: item for item in evidence["key_moves"]}
    requested = {int(value) for value in re.findall(r"(?:position(?:\s+revision)?|revision)\s*(\d+)",
                                                   question or "", re.IGNORECASE)}
    for item in evidence.get("evidence", []):
        if item["revision"] in requested:
            selected[item["revision"]] = item
    positions = []
    colors = {"X": "Black", "O": "White"}
    for item in sorted(selected.values(), key=lambda entry: entry["revision"]):
        analysis = item["analysis"]
        board, actor = tuple(analysis["board"]), item["actor"]
        candidates = []
        for candidate in analysis["candidates"]:
            if candidate["coordinate"] in (item["actual_move"], item["recommended_move"]):
                after = apply_move(board, actor, candidate["coordinate"])
                replies = list(legal_moves(after, opponent(actor)))
                candidates.append({
                    **{key: candidate[key] for key in (
                        "coordinate", "score", "score_kind", "principal_variation")},
                    "opponent_legal_moves_after": replies,
                    "opponent_legal_move_count_after": len(replies),
                })
        positions.append({
            "revision": item["revision"],
            "fact": (f"Position {item['revision']}: {colors[actor]} played {item['actual_move']}; "
                     f"recommended {item['recommended_move']}; score loss {item['score_loss']}; "
                     f"scores from {colors[analysis['score_perspective']]}'s perspective, "
                     f"{'exact result' if analysis['score_kind'] == 'exact' else 'search estimate'}."),
            "board": list(board), "candidates": candidates,
        })
    return {
        "result": evidence["result"], "human_color": evidence["human_color"],
        "initial_board": evidence["initial_board"], "initial_turn": evidence["initial_turn"],
        "history": " ".join(f"{event['revision']}:{event['actor']}:"
                            f"{event['coordinate'] if event['kind'] == 'move' else 'pass'}"
                            for event in evidence["history"]),
        "positions": positions, "hint_adoption": evidence["hint_adoption"],
        "hints": [{key: hint.get(key) for key in ("revision", "recommended_move", "analysis_settings")}
                  for hint in evidence["hints"]],
        "automatic_hint_moves": [{"revision": move["revision"], "coordinate": move["coordinate"]}
                                 for move in evidence["automatic_hint_moves"]],
    }


class Nemotron:
    def __init__(self, api_key: str, base_url: str, model_id: str) -> None:
        self.model_id = model_id
        self.configured = bool(api_key.strip() and model_id.strip())
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/", timeout=90,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def ensure_configured(self) -> None:
        if not self.configured:
            raise AppError("REVIEW_NOT_CONFIGURED", "Token Factory is not configured for review explanations", 503)

    def explain(self, evidence: dict[str, Any], question: str | None = None) -> dict[str, Any]:
        self.ensure_configured()
        payload = {"evidence": review_context(evidence, question),
                   "question": question or "Review this game, explaining key decisions and improvements."}
        response = self.http.post("chat/completions", json={
            "model": self.model_id, "temperature": 0.2, "max_tokens": 2400,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        })
        if response.status_code == 401:
            raise AppError("TOKEN_FACTORY_AUTH", "Review service authentication failed. Ask the maintainer to check Token Factory configuration", 503)
        response.raise_for_status()
        output = response.json()
        if output["choices"][0].get("finish_reason") == "length":
            raise AppError("REVIEW_TRUNCATED", "Review exceeded the output limit and did not return a complete answer", 502)
        explanation = output["choices"][0]["message"]["content"]
        if not isinstance(explanation, str) or not explanation.strip():
            raise AppError("REVIEW_EMPTY", "Review model did not return an explanation", 502)
        return {"text": explanation, "model_id": self.model_id, "usage": output.get("usage")}

    def close(self) -> None:
        self.http.close()
