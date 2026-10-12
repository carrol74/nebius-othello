# Nemothello

An Othello app with a trained AI opponent, optional move hints, and post-game review.

The planned opponent is a Jev-style Qwen3.5-4B model fine-tuned through PyTRIO. Edax supplies training labels, move hints, and analysis evidence. NVIDIA Nemotron, accessed through Nebius Token Factory, explains completed games and answers review questions. Following hints creates a new game branch with newly computed opponent responses.

## Current status

The first implementation is written: board rules, SQLite games and tasks, PyTRIO candidate scoring, Edax hints, post-game Nemotron review, manual and automatic game branches, and a Next.js interface. Data preparation, scoring calibration, training, held-out evaluation, paired matches, and CPU deployment templates are included.

Checkpoint-based training resume, PEFT adapter backup, OpenAPI export, and a live backend acceptance command are included. The live acceptance command checks real games, reviews, questions, and branches without recording a programmatic hint query as a player viewing a hint.

On 2026-10-12, all **21 Python tests**, Ruff checks, web type checking, the production build, and generated API type verification passed locally. Tests include actual SDK batch planning, real Edax output parsing, board rules, history, SQLite recovery, and exclusive worker ownership.

The user built patched Edax 4.6 on macOS ARM64 and passed the real Python adapter check, including black and white candidates, forced-pass parsing, and exact endgame scores. The report is [edax-check.json](eval/results/edax-check.json). Data generation produced 250 complete games and 14,479 policy positions, split into 200/25/25 games; [dataset-split.json](eval/results/dataset-split.json) preserves the statistics and shared-position counts. Raw data, binaries, weights, credentials, and build output are ignored by Git.

PyTRIO 0.2.9 rejected two-dimensional candidate targets before submission. Scoring now batches one one-dimensional sample per candidate and records repeated input tokens. Real calibration then failed DNS resolution at API-key verification in the sandbox; [calibration.json](eval/results/calibration.json) records this failure. Network retry requires explicit approval after automatic review rejected data transmission and potentially charged tasks. Model training, cloud scoring accuracy, end-to-end games, and public deployment remain unverified.

## Development

| Component | Location | Target |
| --- | --- | --- |
| Web | `web/` | Next.js 16, React 19, TypeScript; Vercel |
| Backend | `backend/` | Python 3.11–3.13, FastAPI; Nebius CPU VM |
| Data | `data/` | Whole-game splits before position extraction |
| Artifacts | `artifacts/` | Adapter exports and training metadata |
| Measurements | `eval/results/` | Actual evaluation results |

The backend owns board rules and game state. The web app displays backend results and proxies requests. Model credentials remain on the backend. A single backend worker owns the SDK client, Edax process, and durable task queue.

After execution is authorized, follow the [runbook](docs/runbook.md) for setup, local checks, real scoring calibration, training, evaluation, and deployment. Install web dependencies at the repository root and Python dependencies in `backend/`. Generate and verify lockfiles before publishing. The manifests include SDK and tokenizer dependencies; Edax and its evaluation weights must be supplied separately.

With actual resources configured, use `npm run dev` at the root and `uv run uvicorn nemothello.main:app --reload` in `backend/`. Startup checks required configuration, engine files, and a passing calibration report for the configured adapter. A file lock rejects additional workers for the same database before task recovery. `GET /health` reports process response, not external model readiness. Creating or viewing a game does not prove that model scoring works.

Environment examples are in `web/.env.example` and `backend/.env.example`. Never put provider secrets in a `NEXT_PUBLIC_` variable. `deploy/compose.yaml` targets a Nebius CPU VM; configure Vercel with this repository's npm workspace and the backend HTTPS URL. Neither target has been deployed.

## Documentation

- [Authoritative project plan](plan.md)
- [Development tasks and acceptance criteria](docs/development-plan.md)
- [API contract and implementation limits](docs/api-contract.md)
- [Setup, training, evaluation, and deployment runbook](docs/runbook.md)
- [Third-party license checklist](docs/licenses.md)
- [Technical design](docs/technical-design.md)
- [Product behavior and deployment](docs/product-integration.md)
- [Open technical questions](docs/review/open-questions.md)

The project is intended for the Best Apps and Agents Track of the Nebius x NVIDIA Global AI Hackathon. Public release still requires real Nemotron integration, evaluation evidence, a working demo, and code and asset license notices.
