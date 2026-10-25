# Nemothello

An Othello app with an Edax opponent, optional move hints, and post-game review by NVIDIA Nemotron through Nebius Token Factory.

The backend owns board rules, games, hint records, and branch replay. Separate Edax processes provide opponent moves and analysis. Nemotron writes the coaching in the player's language: it explains each reviewed decision, responds to what the player says they intended, and answers follow-up questions. As an agent, it calls rules-engine tools to play out lines and check corner threats before it answers. The backend verifies every number and claim before the text is shown.

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

Set both `TOKEN_FACTORY_API_KEY` and `TOKEN_FACTORY_MODEL_ID` to enable Nemotron coaching. The model must support OpenAI-format tool calls; `nvidia/nemotron-3-super-120b-a12b` and `nvidia/Nemotron-3-Ultra-550b-a55b` both work. Leave both empty to use games, hints, review navigation, engine analysis, and branch replay without language-model calls; Nemotron coaching then reports that it is not configured. Credentials stay on the backend.

Switch between English and Chinese with the header buttons; the app remembers your language. Play and Review share the same board. Review lets you step backward or forward through the entire game, including passes, or drag the timeline to any position. When a finished game opens in Review, Edax analyzes each of your moves once, without a model call, and the timeline lists up to three moves worth reviewing, preferring one each from the opening, midgame, and endgame. Select **Teach this position** to analyze that position and request a Nemotron lesson. Saved lessons reopen without another model call. Compare the played move with the recommendation, step through their consequences on the board, or ask a follow-up in the same panel. Until Nemotron's explanation is ready, or if it fails, the panel shows a short lesson generated from the rules engine; once Nemotron's explanation is ready, it replaces that lesson, and the board demonstration opens at the step it cites. Optional continuations create a separate game without changing the original history.

In Play, **Slow** first shows the opponent's placed disc, then its flips, before enabling your next move. **Normal** keeps the last placement marked. The speed choice persists across visits.

Before calling the model, the backend computes teaching concepts from standard Othello strategy for the played and recommended moves: flipped discs left next to an empty square (quiet versus loud moves), the opponent's safe replies, discs that can never be flipped again, and endgame empty regions. It ranks the concepts that most clearly separate the two moves and gives the top ones to Nemotron as focus facts, after any verified corner threat. The glossary button in the teaching panel explains these terms.

Coaching runs as a tool-calling loop with Nemotron's thinking mode on; in a test on eight saved positions with Super, every answer passed the checks with thinking on, versus six of eight with it off, at a similar token count. Nemotron may call `play_line` and `check_corner_threat`, then submits its answer through `submit_answer`. The model writes numbers as placeholders such as `{p16.b1.replies}`, and the backend fills in the verified values. The coach explains board consequences such as flips, replies, and capture lines; it never sees or reports engine scores, and it addresses the player as "you" and the other side as "the opponent". Text with a digit, an unknown placeholder, a coordinate outside the evidence, score talk, a side named by color, or a claim about corners, hints, passes, or winning without a matching cited fact is returned to the model for correction, at most twice. If the answer still fails, coaching reports an error; saved analysis remains available, and coaching can be retried separately. Forced moves need no model call. Opening saved reviews and exploring continuations make no model calls.

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
