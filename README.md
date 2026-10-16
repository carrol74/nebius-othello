# Nemothello

An Othello app with an Edax opponent, optional move hints, and post-game review by NVIDIA Nemotron through Nebius Token Factory.

The backend owns board rules, games, hint records, and branch replay. Separate Edax processes provide opponent moves and analysis. Nemotron explains completed games using the saved game and engine evidence, and answers review questions.

## Structure

- `web/`: Next.js board, game history, hints, reviews, and backend proxy.
- `backend/src/nemothello/`: FastAPI service, rules, storage, engine adapters, review tasks, and CLI tools.
- `backend/tests/`: product and research regression tests.
- `deploy/`: CPU backend, gateway, and Edax deployment configuration.
- `data/`, `artifacts/`, `eval/results/`: local datasets, model artifacts, and evaluation outputs; not required to run the app.

## Development

Requirements: Node.js 20.9+, Python 3.11–3.13, uv, and an Edax executable with compatible evaluation weights. Obtain the engine and weights separately; use a Linux engine for the container deployment.

Install web dependencies from the repository root:

```sh
npm ci
```

Install the product backend from `backend/`:

```sh
uv sync --extra dev
```

Configure `backend/.env` and `web/.env.local` from their examples. Supply Edax paths and a shared backend service token. Choose beginner, intermediate, or advanced when starting a game (Edax levels 1, 4, and 8). Intermediate is the default. Difficulty is saved per game and inherited by branches; changing the selector applies to new games. `EDAX_LEVEL` defaults to 8 for hints and review analysis. `EDAX_OPPONENT_LEVEL` is retained for compatibility with earlier engine configurations. The interface identifies the opponent used for each game.

Set both `TOKEN_FACTORY_API_KEY` and `TOKEN_FACTORY_MODEL_ID` to enable Nemotron reviews. Leave both empty to use games, hints, and branch replay without language-model calls; review requests then report that the service is not configured. Credentials stay on the backend.

Run the frontend from the root:

```sh
npm run dev
```

Run the backend from `backend/`:

```sh
uv run uvicorn nemothello.main:app --reload
```

Use one worker per database. Opponent identity includes the engine version, resource hashes, and search settings. Existing games cannot continue or replay against a changed opponent. `GET /health` checks process response; it does not verify external model readiness.

## Checks and tools

From the root: `npm run test:web`, `npm run typecheck`, `npm run build`, and `npm run check:api-types`.

From `backend/`:

```sh
uv run pytest tests/test_rules.py tests/test_history.py tests/test_storage.py tests/test_edax.py tests/test_product_runtime.py
uv run ruff check src tests
uv run nemothello --help
uv run nemothello check-edax --output ../eval/results/edax-check.json
```

`verify-demo` exercises the backend game, review, question, and branch APIs. It calls Token Factory and can incur charges. Browser hint display requires a separate UI check.

## Research tools

The CLI also contains policy calibration, cloud training, model evaluation, and adapter backup tools. Install their optional dependencies only when using them:

```sh
uv sync --extra dev --extra research
uv run pytest
```

Cloud research commands can incur charges. They use `PYTRIO_API_KEY` and optional `PYTRIO_BASE_MODEL` from the backend environment. Training and evaluation use the checkpoint paths and calibration reports specified through their CLI options. These tools do not configure the app's opponent.

`deploy/compose.yaml` provides a CPU backend deployment template; the Next.js app targets Vercel. Model credentials belong on the backend, never in public frontend variables.
