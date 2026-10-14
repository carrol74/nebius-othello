import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from nemothello.artifacts import backup_adapter
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
from nemothello.evaluation import evaluate, evaluate_positions
from nemothello.generation_calibration import calibrate_generation
from nemothello.policy import GENERATION_MODE, POLICY_MODES
from nemothello.training import calibrate, train
from nemothello.training_recovery import supervise_training
from nemothello.verification import verify_demo


def api_key() -> str:
    key = os.environ.get("PYTRIO_API_KEY", "").strip()
    if not key:
        raise ValueError("需要配置 PYTRIO_API_KEY")
    return key


def engine(level: int) -> Edax:
    executable = Path(os.environ["EDAX_EXECUTABLE"])
    eval_file = Path(os.environ["EDAX_EVAL_FILE"])
    if not executable.is_file() or not eval_file.is_file():
        raise ValueError("Edax 程序与评估权重文件必须存在")
    return Edax(executable, eval_file, os.environ["EDAX_VERSION"], level,
                float(os.environ.get("EDAX_TIMEOUT_SECONDS", "60")))


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Nemothello 数据、评分核验、训练与评测")
    sub = parser.add_subparsers(dest="command", required=True)
    openings = sub.add_parser("openings", help="生成固定共享开局，不调用模型")
    openings.add_argument("--output", type=Path, required=True)
    openings.add_argument("--count", type=int, default=40)
    openings.add_argument("--plies", type=int, default=8)
    openings.add_argument("--seed", type=int, default=20261008)
    edax_check = sub.add_parser("check-edax", help="通过真实 Python 管道检查 Edax，不调用云端模型")
    edax_check.add_argument("--output", type=Path, required=True)
    edax_check.add_argument("--level", type=int, default=8, choices=range(1, 11))
    generate = sub.add_parser("generate", help="运行真实 Edax 生成完整棋谱与标签")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--openings", type=Path, required=True)
    generate.add_argument("--games", type=int, default=250)
    generate.add_argument("--level", type=int, default=8, choices=range(1, 11))
    generate.add_argument("--seed", type=int, default=42)
    prepare = sub.add_parser("prepare", help="按整盘划分并检查数据")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--seed", type=int, default=42)
    calibration = sub.add_parser("calibrate", help="真实云端落子与保存恢复核验，会产生调用费用")
    calibration.add_argument("--data", type=Path, required=True)
    calibration.add_argument("--output", type=Path, required=True)
    calibration.add_argument("--name", required=True)
    calibration.add_argument("--model-path")
    calibration.add_argument("--sampler-path", help="生成模式恢复时，与 Train 检查点配对的 Sampler 路径")
    calibration.add_argument("--mode", choices=POLICY_MODES, default=GENERATION_MODE)
    calibration.add_argument("--repeats", type=int, default=3)
    calibration.add_argument("--limit", type=int, default=12)
    calibration.add_argument("--tolerance", type=float, default=1e-4)
    training = sub.add_parser("train", help="真实云端训练，会产生训练费用")
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
                          help="遇到可恢复的传输错误时，从检查点启动新进程的最大次数")
    training.add_argument("--resume", action="store_true", help="从输出目录已确认的批次检查点恢复权重和优化器")
    evaluation = sub.add_parser("evaluate", help="真实基座与微调对弈评测，会产生推理费用")
    evaluation.add_argument("--model-path", required=True)
    evaluation.add_argument("--openings", type=Path, required=True)
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--seed", type=int, default=42)
    evaluation.add_argument("--mode", choices=POLICY_MODES, default=GENERATION_MODE)
    evaluation.add_argument("--pilot-openings", type=int, help="仅做前 N 个固定开局的试验，不作为正式评测")
    evaluation.add_argument("--resume", action="store_true", help="从已保存棋谱继续，不重复完成对局")
    evaluation.add_argument("--edax-level", type=int, choices=range(1, 11), default=2)
    evaluation.add_argument("--opponents", nargs="+", choices=("random", "edax"),
                            default=["random", "edax"], help="只运行选定对手的对照")
    positions = sub.add_parser("evaluate-positions", help="真实保留测试局面的基座与微调比较，会产生推理费用")
    positions.add_argument("--model-path", required=True)
    positions.add_argument("--dataset", type=Path, required=True)
    positions.add_argument("--output", type=Path, required=True)
    positions.add_argument("--seed", type=int, default=42)
    positions.add_argument("--limit", type=int, default=200)
    positions.add_argument("--equivalent-margin", type=float, default=1)
    positions.add_argument("--mode", choices=POLICY_MODES, default=GENERATION_MODE)
    backup = sub.add_parser("backup", help="下载真实 sampler adapter 归档并检查 PEFT 文件，不运行模型")
    backup.add_argument("--metadata", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--tmp-dir", type=Path, default=Path("../.tmp"))
    contracts = sub.add_parser("export-openapi", help="根据后端类型导出接口定义，不启动服务或调用模型")
    contracts.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify-demo", help="真实后端全流程验收，会调用模型与引擎并产生费用")
    verify.add_argument("--url", required=True)
    verify.add_argument("--output", type=Path, required=True)
    verify.add_argument("--task-timeout", type=float, default=1800)
    args = parser.parse_args()
    base_model = os.environ.get("PYTRIO_BASE_MODEL", "Qwen/Qwen3.5-4B")
    if args.command == "openings":
        write_json(args.output, generate_openings(args.count, args.plies, args.seed))
    elif args.command == "check-edax":
        verify_edax(engine(args.level), args.output)
        print(f"Edax 适配器检查通过，报告：{args.output}")
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
        if args.output.exists():
            parser.error("校准输出已存在，请使用新文件保留原始证据")
        try:
            if args.mode == GENERATION_MODE:
                calibrate_generation(api_key(), base_model, args.data, args.output, args.name,
                                     args.model_path, args.sampler_path,
                                     args.limit, args.tolerance, args.repeats)
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
        print(f"落子校准通过，报告：{args.output}")
    elif args.command == "train":
        if args.max_restarts < 0:
            parser.error("max-restarts 不能为负")
        if args.max_restarts:
            supervise_training(args)
        else:
            train(api_key(), base_model, args.dataset, args.output, args.name,
                  json.loads(args.calibration.read_text()), args.rank, args.learning_rate,
                  args.batch_size, args.epochs, args.seed, args.resume, args.checkpoint_every)
    elif args.command == "evaluate-positions":
        evaluate_positions(api_key(), base_model, args.model_path, args.dataset,
                           args.output, args.seed, args.limit, args.equivalent_margin, args.mode)
    elif args.command == "backup":
        backup_adapter(api_key(), args.metadata, args.output, args.tmp_dir)
    elif args.command == "export-openapi":
        export_openapi(args.output)
    elif args.command == "verify-demo":
        verify_demo(args.url, os.environ["BACKEND_SERVICE_TOKEN"], args.output, args.task_timeout)
    else:
        edax = engine(args.edax_level)
        try:
            openings = json.loads(args.openings.read_text())
            if args.pilot_openings is not None:
                if not 1 <= args.pilot_openings <= len(openings):
                    parser.error("pilot-openings 超出可用开局范围")
                openings = openings[:args.pilot_openings]
            evaluate(api_key(), base_model, args.model_path, openings, edax, args.output,
                     args.seed, args.mode, args.pilot_openings is not None, args.resume,
                     tuple(args.opponents))
        finally:
            edax.close()


if __name__ == "__main__":
    main()
