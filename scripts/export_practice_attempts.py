import argparse
import json
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Export practice evidence for local human review without session or game identifiers.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT document FROM records WHERE kind='practice_attempt' ORDER BY rowid").fetchall()
    attempts = []
    for row in rows:
        attempt = json.loads(row[0])
        attempts.append({"question": attempt["question"], "answer": attempt["answer"],
                         "automatic_feedback": attempt["feedback"],
                         "human_review": {"facts_correct": None, "mechanism_relevant": None,
                                          "reason_score": None, "notes": None}})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"protocol": "capture-lines-v1", "attempts": attempts}, indent=2) + "\n")
    print(f"Exported {len(attempts)} attempts for human review")


if __name__ == "__main__":
    main()
