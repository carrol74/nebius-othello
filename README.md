# Nemothello

An Othello app with an AI opponent, optional move hints, and post-game review.

The opponent uses Jev-style candidate scoring with Qwen3.5-4B through PyTRIO. Edax supplies training labels, hints, and analysis. NVIDIA Nemotron through Nebius Token Factory explains completed games and answers review questions.

AI games require a trained policy checkpoint and its passing scoring calibration report.

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

`deploy/compose.yaml` provides a CPU backend deployment template; the Next.js app targets Vercel.
