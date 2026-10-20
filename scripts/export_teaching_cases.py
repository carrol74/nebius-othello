import argparse
import json
import sqlite3
from pathlib import Path

from nemothello.position_lessons import position_at
from nemothello.teaching import compare_lesson


def export_cases(database):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT kind, id, owner, document FROM records "
                          "WHERE kind IN ('game','lesson','task') ORDER BY rowid").fetchall()
    records = {(kind, item_id, owner): json.loads(document) for kind, item_id, owner, document in rows}
    cases, evidence = [], []
    for (kind, _, owner), lesson in records.items():
        if kind != "lesson" or "evidence" not in lesson:
            continue
        game = records[("game", lesson["game_id"], owner)]
        if lesson["evidence"]["actor"] != game["human_color"]:
            continue
        revision = lesson["revision"]
        position = position_at(game, revision)
        case_number = len(cases) + 1
        cases.append({
            "case_number": case_number, "revision": revision,
            "initial_board": game["initial_board"], "initial_turn": game["initial_turn"],
            "human_color": game["human_color"],
            "history": [{key: event[key] for key in ("revision", "actor", "kind", "coordinate")}
                        for event in game["history"]],
            "board": list(position.board), "turn": position.turn, "legal_moves": list(position.moves),
            "independent_review": {"preferred_moves": None, "concrete_reason": None,
                                   "relevant_earlier_revision": None, "earlier_link_evidence": None,
                                   "search_settings": None, "reviewer": None},
        })
        comparison = compare_lesson({"evidence": [lesson["evidence"]]}, revision,
                                    lesson["evidence"]["actual_move"])
        questions = [{"question": task["inputs"]["question"], "view": task["inputs"].get("view"),
                      "status": task["status"], "answer": task.get("result")}
                     for (entry_kind, _, entry_owner), task in records.items()
                     if entry_kind == "task" and entry_owner == owner and task["kind"] == "question"
                     and task["game_id"] == game["game_id"] and task["inputs"].get("revision") == revision]
        evidence.append({
            "case_number": case_number, "engine_evidence": lesson["evidence"],
            "comparison": comparison, "player_reflection": lesson.get("reflection"),
            "coach_selection": lesson.get("coaching", []), "coaching_status": lesson.get("coaching_status"),
            "earlier_decision": lesson.get('earlier_decision'),
            "questions": questions,
            "expert_review": {"board_facts_correct": None, "scope_of_claims_correct": None,
                              "addresses_player_question": None, "explains_choice": None,
                              "counterexample": None, "correction": None, "reviewer": None},
        })
    return {"protocol": "decision-teaching-v1", "cases": cases}, {
        "protocol": "decision-teaching-v1", "cases": evidence,
    }


def main():
    parser = argparse.ArgumentParser(description="Export local teaching cases for independent review, without session or game identifiers.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Independent board and history packet, without engine or coaching conclusions")
    parser.add_argument("--evidence-output", type=Path, required=True, help="Separate application evidence packet to inspect after independent analysis")
    args = parser.parse_args()
    paths = [path.resolve() for path in (args.database, args.output, args.evidence_output)]
    if len(set(paths)) != 3:
        parser.error("Database and the two output paths must be distinct")
    packets = export_cases(args.database)
    for path, packet in zip((args.output, args.evidence_output), packets):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    print(f"Exported {len(packets[0]['cases'])} teaching cases in two separate review packets")


if __name__ == "__main__":
    main()
