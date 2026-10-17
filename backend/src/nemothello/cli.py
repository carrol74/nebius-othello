import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from nemothello.contracts import export_openapi
from nemothello.data import (
    generate_games,
    generate_openings,
    prepare_dataset,
    read_jsonl,
    write_json,
    write_jsonl,
)
from nemothello.edax import Edax
from nemothello.edax_verification import verify_edax
from nemothello.policy_spec import GENERATION_MODE, POLICY_MODES, TEMPLATE_VERSIONS
from nemothello.verification import verify_demo


def api_key() -> str:
    key = os.environ.get("PYTRIO_API_KEY", "").strip()
    if not key:
        raise ValueError("PYTRIO_API_KEY is required")
    return key


def engine(level: int) -> Edax:
    executable = Path(os.environ["EDAX_EXECUTABLE"])
    eval_file = Path(os.environ["EDAX_EVAL_FILE"])
    if not executable.is_file() or not eval_file.is_file():
        raise ValueError("Edax executable and evaluation weights must exist")
    return Edax(executable, eval_file, os.environ["EDAX_VERSION"], level,
                float(os.environ.get("EDAX_TIMEOUT_SECONDS", "60")))


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Nemothello product checks, API export, and optional research tools")
    sub = parser.add_subparsers(dest="command", required=True)
    openings = sub.add_parser("openings", help="Generate fixed shared openings without model calls")
    openings.add_argument("--output", type=Path, required=True)
    openings.add_argument("--count", type=int, default=40)
    openings.add_argument("--plies", type=int, default=8)
    openings.add_argument("--seed", type=int, default=20261008)
    edax_check = sub.add_parser("check-edax", help="Check Edax through native Python pipes without cloud model calls")
    edax_check.add_argument("--output", type=Path, required=True)
    edax_check.add_argument("--level", type=int, default=8, choices=range(1, 11))
    blind = sub.add_parser("check-coach-blind", help="Ask Nemotron to choose without engine hints, then check saved native evidence; incurs inference charges")
    blind.add_argument("--input", type=Path, required=True, help="Saved review JSON, or native review fixture")
    blind.add_argument("--revisions", type=int, nargs="+", required=True)
    blind.add_argument("--output", type=Path, required=True)
    generate = sub.add_parser("generate", help="Run native Edax to generate full games and labels")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--openings", type=Path, required=True)
    generate.add_argument("--games", type=int, default=250)
    generate.add_argument("--level", type=int, default=8, choices=range(1, 11))
    generate.add_argument("--seed", type=int, default=42)
    prepare = sub.add_parser("prepare", help="Split data by game and validate it")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--seed", type=int, default=42)
    calibration = sub.add_parser("calibrate", help="Verify live cloud moves and save/restore; incurs API charges")
    calibration.add_argument("--data", type=Path, required=True)
    calibration.add_argument("--output", type=Path, required=True)
    calibration.add_argument("--name", required=True)
    calibration.add_argument("--model-path")
    calibration.add_argument("--sampler-path", help="Sampler path paired with the Train checkpoint for generation restoration")
    calibration.add_argument("--mode", choices=POLICY_MODES, default=GENERATION_MODE)
    calibration.add_argument("--template-version", choices=TEMPLATE_VERSIONS,
                             help="Select the input template paired with the weights; defaults to the original candidate template")
    calibration.add_argument("--repeats", type=int, default=3)
    calibration.add_argument("--limit", type=int, default=12)
    calibration.add_argument("--tolerance", type=float, default=1e-4)
    training = sub.add_parser("train", help="Run live cloud training; incurs training charges")
    training.add_argument("--dataset", type=Path, required=True)
    training.add_argument("--calibration", type=Path, required=True)
    training.add_argument("--output", type=Path, required=True)
    training.add_argument("--name", required=True)
    training.add_argument("--rank", type=int, default=32)
    training.add_argument("--learning-rate", type=float, default=1e-4)
    training.add_argument("--batch-size", type=int, default=16)
    training.add_argument("--epochs", type=int, default=2)
    training.add_argument("--seed", type=int, default=42)
    training.add_argument("--checkpoint-every", type=int, default=25)
    training.add_argument("--max-restarts", type=int, default=0,
                          help="Maximum checkpoint restarts in a new process after recoverable transport failures")
    training.add_argument("--resume", action="store_true", help="Restore weights and optimizer from the confirmed batch checkpoint in the output directory")
    evaluation = sub.add_parser("evaluate", help="Evaluate live base and fine-tuned models in matches; incurs inference charges")
    evaluation.add_argument("--model-path", required=True)
    evaluation.add_argument("--baseline-model-path", help="Saved reference model path; defaults to the untuned base model")
    evaluation.add_argument("--openings", type=Path, required=True)
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--seed", type=int, default=42)
    evaluation.add_argument("--mode", choices=POLICY_MODES, default=GENERATION_MODE)
    evaluation.add_argument("--pilot-openings", type=int, help="Pilot using the first N fixed openings; not a formal evaluation")
    evaluation.add_argument("--resume", action="store_true", help="Resume from saved histories without replaying completed games")
    evaluation.add_argument("--edax-level", type=int, choices=range(1, 11), default=2)
    evaluation.add_argument("--opponents", nargs="+", choices=("random", "edax"),
                            default=["random", "edax"], help="Run comparisons only against selected opponents")
    positions = sub.add_parser("evaluate-positions", help="Compare live base and fine-tuned models on held-out positions; incurs inference charges")
    positions.add_argument("--model-path", required=True)
    positions.add_argument("--dataset", type=Path, required=True)
    positions.add_argument("--output", type=Path, required=True)
    positions.add_argument("--seed", type=int, default=42)
    positions.add_argument("--limit", type=int, default=200)
    positions.add_argument("--equivalent-margin", type=float, default=1)
    positions.add_argument("--mode", choices=POLICY_MODES, default=GENERATION_MODE)
    failures = sub.add_parser("analyze-failures", help="Label saved losses using Edax without cloud model calls")
    failures.add_argument("--sources", type=Path, nargs="+", required=True)
    failures.add_argument("--dataset", type=Path, required=True)
    failures.add_argument("--output", type=Path, required=True)
    failures.add_argument("--level", type=int, choices=range(1, 11), default=8)
    failures.add_argument("--resume", action="store_true")
    backup = sub.add_parser("backup", help="Download the sampler adapter archive and inspect PEFT files without running a model")
    backup.add_argument("--metadata", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--tmp-dir", type=Path, default=Path("../.tmp"))
    contracts = sub.add_parser("export-openapi", help="Export API definitions from backend schemas without starting services or calling models")
    contracts.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify-demo", help="Verify the live backend flow; calls models and engines and incurs charges")
    verify.add_argument("--url", required=True)
    verify.add_argument("--output", type=Path, required=True)
    verify.add_argument("--task-timeout", type=float, default=1800)
    args = parser.parse_args()
    base_model = os.environ.get("PYTRIO_BASE_MODEL", "Qwen/Qwen3.5-4B")
    if args.command == "openings":
        write_json(args.output, generate_openings(args.count, args.plies, args.seed))
    elif args.command == "check-coach-blind":
        from nemothello.blind_review import evaluate_blind
        from nemothello.nemotron import Nemotron

        data = json.loads(args.input.read_text())
        review = data.get("review", data)
        model = Nemotron(os.environ.get("TOKEN_FACTORY_API_KEY", ""),
                         os.environ.get("TOKEN_FACTORY_BASE_URL", "https://api.tokenfactory.nebius.com/v1"),
                         os.environ.get("TOKEN_FACTORY_MODEL_ID", ""))
        try:
            report = evaluate_blind(model, review["evidence"], args.revisions, args.output)
            print(f"Blind comparison completed: {len(report['calls'])} calls; report: {args.output}")
        finally:
            model.close()
    elif args.command == "check-edax":
        verify_edax(engine(args.level), args.output)
        print(f"Edax adapter check passed; report: {args.output}")
    elif args.command == "generate":
        edax = engine(args.level)
        try:
            records = generate_games(edax, args.games, args.seed, json.loads(args.openings.read_text()))
            write_jsonl(args.output, records)
        finally:
            edax.close()
    elif args.command == "prepare":
        prepare_dataset(read_jsonl(args.input), args.output, args.seed)
    elif args.command == "calibrate":
        from nemothello.generation_calibration import calibrate_generation
        from nemothello.training import calibrate

        if args.template_version is not None and args.mode != GENERATION_MODE:
            parser.error("Explicit template selection supports only single-token generation calibration")
        if args.output.exists():
            parser.error("Calibration output already exists. Use a new file to preserve original evidence")
        try:
            if args.mode == GENERATION_MODE:
                calibrate_generation(api_key(), base_model, args.data, args.output, args.name,
                                     args.model_path, args.sampler_path,
                                     args.limit, args.tolerance, args.repeats,
                                     template_version=args.template_version)
            else:
                calibrate(api_key(), base_model, args.data, args.output, args.name,
                          args.model_path, args.limit, args.tolerance)
        except Exception as exc:
            if args.output.exists():
                report = json.loads(args.output.read_text(encoding="utf-8"))
                if report.get("status") == "running":
                    report.update(status="failed", error_type=type(exc).__name__)
                    write_json(args.output, report)
            raise
        print(f"Move calibration passed; report: {args.output}")
    elif args.command == "train":
        from nemothello.training import train
        from nemothello.training_recovery import supervise_training

        if args.max_restarts < 0:
            parser.error("max-restarts must be nonnegative")
        if args.max_restarts:
            supervise_training(args)
        else:
            train(api_key(), base_model, args.dataset, args.output, args.name,
                  json.loads(args.calibration.read_text()), args.rank, args.learning_rate,
                  args.batch_size, args.epochs, args.seed, args.resume, args.checkpoint_every)
    elif args.command == "evaluate-positions":
        from nemothello.evaluation import evaluate_positions

        evaluate_positions(api_key(), base_model, args.model_path, args.dataset,
                           args.output, args.seed, args.limit, args.equivalent_margin, args.mode)
    elif args.command == "analyze-failures":
        from nemothello.failure_analysis import analyze_failures

        edax = engine(args.level)
        try:
            analyze_failures(args.sources, args.dataset, edax, args.output, args.resume)
        finally:
            edax.close()
    elif args.command == "backup":
        from nemothello.artifacts import backup_adapter

        backup_adapter(api_key(), args.metadata, args.output, args.tmp_dir)
    elif args.command == "export-openapi":
        export_openapi(args.output)
    elif args.command == "verify-demo":
        verify_demo(args.url, os.environ["BACKEND_SERVICE_TOKEN"], args.output, args.task_timeout)
    else:
        from nemothello.evaluation import evaluate

        edax = engine(args.edax_level)
        try:
            openings = json.loads(args.openings.read_text())
            if args.pilot_openings is not None:
                if not 1 <= args.pilot_openings <= len(openings):
                    parser.error("pilot-openings exceeds the available opening count")
                openings = openings[:args.pilot_openings]
            evaluate(api_key(), base_model, args.model_path, openings, edax, args.output,
                     args.seed, args.mode, args.pilot_openings is not None, args.resume,
                     tuple(args.opponents), args.baseline_model_path)
        finally:
            edax.close()


if __name__ == "__main__":
    main()
