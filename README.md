# Nemothello

An Othello app with an Edax opponent, optional move hints, and post-game review by NVIDIA Nemotron through Nebius Token Factory.

The backend owns board rules, games, hint records, and branch replay. Separate Edax processes provide opponent moves and analysis. Nemotron selects personalized lessons using verified game and engine evidence. The backend checks its references and supplies the displayed facts and teaching content.

Beginner, intermediate, and advanced opponents use Edax levels 1, 4, and 8; their move hints use levels 4, 8, and 10. Games save their hint level, and branches inherit it. `EDAX_LEVEL` sets the general analysis level and minimum review level; reviews use at least the game's hint level. Search levels do not guarantee a win.

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

For manual startup, configure `backend/.env` and `web/.env.local` from their examples. Supply Edax paths and a shared backend service token. The app prepares a game automatically. Choose Black or White and beginner, intermediate, or advanced (Edax levels 1, 4, and 8). Intermediate is the default. Before your first move, changing these settings replaces the opening game; after play begins, they apply to the next game. Difficulty and hint level are saved per game and inherited by branches. `EDAX_LEVEL` defaults to 8 for general analysis, older games' hints, and the minimum review level. `EDAX_OPPONENT_LEVEL` supports earlier engine configurations. The interface identifies the opponent used for each game.

Set both `TOKEN_FACTORY_API_KEY` and `TOKEN_FACTORY_MODEL_ID` to enable Nemotron reviews. Leave both empty to use games, hints, and branch replay without language-model calls; review requests then report that the service is not configured. Credentials stay on the backend.

Switch between English and Chinese with the header buttons; the app remembers your language. After a game, select a decision and compare any legal move with the engine recommendation. A short explanation shows the score difference and relevant board facts. Practice, search continuations, full analysis, and questions remain available as optional controls. Tied best-scoring alternatives count as equally rated.

Coaching uses a checked JSON lesson plan with thinking disabled. Invalid or incomplete plans report an error; saved analysis and practice remain available, and coaching can be retried separately. Opening saved reviews, practising moves, and exploring continuations make no model calls. Hint-adoption and result queries use saved facts when they can be answered directly.

To evaluate the configured model independently, run `nemothello check-coach-blind --input saved-review.json --revisions 2 16 19 47 --output blind-check.json` from `backend/`. This sends only boards, sides to move, and legal moves; saved engine recommendations and scores are used afterward to check the answers. It incurs one bounded API call per position, with no automatic retries. The report separates move quality, factual accuracy, and unchecked free-text reasoning.

To start both services locally, double-click `start.command` on macOS or run:

```sh
./start.command
```

The launcher uses the existing virtual environment and Node.js dependencies. It fills missing Edax paths from `deploy/edax/`, preserves the backend service token when configured, and synchronizes the token and local backend URL into `web/.env.local`. It opens the app at `http://127.0.0.1:3000`. Keep the terminal open; press Ctrl+C to stop both services. Logs are written to `backend/runtime/local-start/` and replaced on each launch. Dependencies are never installed automatically.

Use `./start.command --check` for a read-only environment check, or `--no-browser` to suppress opening the browser. If the default ports are occupied, select ports with `--backend-port 8017 --web-port 3017`.

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
