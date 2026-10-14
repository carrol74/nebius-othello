# Nemothello

An Othello app with an AI opponent, optional move hints, and post-game review.

The opponent uses Qwen3.5-4B through PyTRIO to generate one candidate symbol per move. The backend validates the symbol against legal moves. Edax supplies training labels, hints, and analysis. NVIDIA Nemotron through Nebius Token Factory explains completed games and answers review questions.

AI games require a trained Sampler checkpoint and its passing generation calibration report. The optional `candidate-batch-1d` policy requires a Train checkpoint and a passing score calibration report instead. Reports must match the configured policy mode.

## Development

Requirements: Node.js 20.9+, Python 3.11–3.13, uv, and a compatible Edax executable with evaluation weights.

Install web dependencies at the repository root:

```sh
npm ci
```

Install backend dependencies in `backend/`:

```sh
uv sync --extra dev
```

Configure `backend/.env` and `web/.env.local` from their `.env.example` files. Supply real PyTRIO and Token Factory credentials, the policy checkpoint and calibration report, Edax paths, and a shared backend service token. Model credentials stay on the backend.

Run the web app from the root:

```sh
npm run dev
```

Run the backend from `backend/`:

```sh
uv run uvicorn nemothello.main:app --reload
```

The backend owns board rules, SQLite games, and the task queue. Use one worker per database. Startup validates resources and requires a passing calibration report for the configured policy. `GET /health` checks process response; it does not validate external model readiness.

## Checks and tools

From the root: `npm run typecheck`, `npm run build`, and `npm run check:api-types`.

From `backend/`: `uv run pytest`, `uv run ruff check src tests`, and `uv run nemothello --help`. The CLI provides Edax checks, data preparation, calibration, training, evaluation, adapter backup, API export, and live acceptance checks. Cloud model operations can incur charges.

Training saves weights and optimizer state every 25 batches. Use `train --resume` to continue from the last confirmed checkpoint, or `--max-restarts 2` to enable bounded recovery in fresh processes after transport failures. Batch checkpoints expire after seven days; completed epoch checkpoints are saved without an expiry.

Match evaluation uses 40 fixed openings with both colors. Add `evaluate --pilot-openings 4` to run a 32-game pilot against random play and Edax level 2. Each accepted move is saved; use `evaluate --resume` with the same options and output path after a transport interruption. Invalid model outputs are recorded separately from wins, draws, and losses. Scores and comparisons use complete games and complete opening groups, with completion coverage reported alongside them.

Use `--edax-level 1 --opponents edax` to select Edax level 1 without repeating random-opponent games. With four pilot openings, this runs 16 games. The opponent selection and engine level must stay unchanged when resuming.

`analyze-failures --sources REPORT... --dataset DATASET_DIR --output OUTPUT` uses the configured Edax engine to label model decisions in saved losses. It does not call cloud models or modify training data. The default teacher level is 8; use `--resume` to continue an interrupted analysis with unchanged sources and dataset files. Diagnostic positions from evaluation games stay separate from training data.

`deploy/compose.yaml` provides a CPU backend deployment template; the Next.js app targets Vercel.
