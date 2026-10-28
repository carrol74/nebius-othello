# Nemothello

An Othello app with an Edax opponent, optional move hints, and post-game review by NVIDIA Nemotron through Nebius Token Factory.

The backend owns board rules, games, hint records, and branches. Separate Edax processes provide opponent moves and analysis. Nemotron writes the coaching in the player's language: it explains each reviewed decision, responds to what the player says they intended, and answers follow-up questions. As an agent, it calls rules-engine tools to play out lines and check corner threats before it answers. The backend verifies every number and claim before the text is shown.

Beginner, intermediate, and advanced opponents use Edax levels 1, 4, and 8; their move hints use levels 4, 8, and 10. Games save their hint level, and branches inherit it. `EDAX_LEVEL` sets the general analysis level. Reviews use the game's hint level, so recommendations match the hints shown at that difficulty. In demonstrations, the opponent's replies come from the game's own opponent at its difficulty. Corner threats are checked against every opponent reply, whatever the difficulty. Search levels do not guarantee a win.

## Structure

- `web/`: Next.js board, game history, hints, reviews, and backend proxy.
- `backend/src/nemothello/`: FastAPI service, rules, storage, engine adapters, review tasks, and CLI tools.
- `backend/tests/`: product and research regression tests.
- `deploy/`: CPU backend, gateway, and Edax deployment configuration.
- `data/`, `artifacts/`, `eval/results/`: local datasets, model artifacts, and evaluation outputs; not required to run the app.

## Development

Requirements: Node.js 20.9+, Python 3.11–3.13, uv, and an Edax executable with compatible evaluation weights. Obtain the engine and weights separately for local development; the container deployment builds its own Linux engine.

Install web dependencies from the repository root:

```sh
npm ci
```

Install the product backend from `backend/`:

```sh
uv sync --extra dev
```

For manual startup, configure `backend/.env` and `web/.env.local` from their examples. Supply Edax paths and a shared backend service token. The app prepares a game automatically. Choose Black or White and beginner, intermediate, or advanced (Edax levels 1, 4, and 8). Intermediate is the default. Before your first move, changing these settings replaces the opening game; after play begins, they apply to the next game. Difficulty and hint level are saved per game and inherited by branches. `EDAX_LEVEL` defaults to 8 for general analysis, older games' hints, and the minimum review level. `EDAX_OPPONENT_LEVEL` supports earlier engine configurations. The interface identifies the opponent used for each game.

Set both `TOKEN_FACTORY_API_KEY` and `TOKEN_FACTORY_MODEL_ID` to enable Nemotron coaching. The model must support OpenAI-format tool calls; `nvidia/nemotron-3-super-120b-a12b` and `nvidia/Nemotron-3-Ultra-550b-a55b` both work. Leave both empty to use games, hints, review navigation, board demonstrations, and branches without language-model calls; the teaching panel then notes that Nemotron is not set up. Credentials stay on the backend. Nemotron lessons, questions, and summaries are capped per UTC day: `MODEL_TASKS_PER_DAY` (default 300) for the whole service and `MODEL_TASKS_PER_SESSION_PER_DAY` (default 30) for one browser session. Sessions are free to create, so the service-wide cap is what bounds spending. When a cap is reached, the teaching panel says so and board demonstrations keep working.

Switch between English and Chinese with the header buttons; the app remembers your language. Play and Review share the board. Review navigation visits your recorded moves and applies the intervening opponent moves and passes automatically. When a finished game opens in Review, Edax analyzes each of your moves once, without a model call.

The game summary combines all your choices, phase totals, displayed hints, and verified comparisons from the selected review positions. Nemotron writes the paragraphs and chooses a learning priority from that evidence; no prewritten coaching paragraphs or fixed topic priority are used. The renderer normalizes paragraph order, whitespace and inline references, and fills move labels from the game record. Code checks evidence references and coordinates, then a separate Nemotron call reviews the displayed text for factual support and whether the advice follows from this game. Presentation preferences do not reject supported prose. Generation permits at most two drafts and two audits. Completed summaries are cached by game, language, and summary version. A single game does not establish a skill rank, and a local comparison does not establish the cause of the final result.

Up to three buttons open decisions worth reviewing, selected from the largest search differences above the review threshold. The summary's selected focus appears first. **← Game summary** returns from an individual lesson. The backend supplies a primary reason and matching board highlights for each comparison. For capture mechanisms, factual sentences come from verified board changes; Nemotron chooses the relevant change and writes a reusable observation question. Other lessons and follow-up answers use Nemotron's grounded explanations. Saved explanations reopen without another model call.

Board demonstrations compare the played and recommended moves. When a shared opponent response changes your next choices, both variations show that same response. For a verified corner threat, **Try defending** lets you test legal alternatives against the rules engine. The earlier-decision check can locate a previous opportunity to prevent a threat that is already unavoidable at the selected turn. **Continue from this position** starts a separate game from the currently displayed board against the same opponent.

In Play, **Slow** first shows the opponent's placed disc, then its flips, before enabling your next move. **Normal** keeps the last placement marked. The speed choice persists across visits.

Before calling the model, the backend computes teaching concepts from standard Othello strategy for the played and recommended moves: flipped discs left next to an empty square (quiet versus loud moves), the opponent's safe replies, discs that can never be flipped again, and endgame empty regions. It ranks the concepts that most clearly separate the two moves; they join the ranked reasons above, after any verified corner or reply difference, and the top three reach Nemotron as focus facts. The glossary button in the teaching panel explains these terms.

Individual coaching runs as a tool-calling loop with Nemotron's thinking mode on. Nemotron may call `play_line`, at most four moves, the length of the longest lesson reason, and `check_corner_threat`, then submits its answer through `submit_answer`. The model writes numbers as placeholders such as `{p16.b1.replies}`, and the backend fills in the verified values. The coach explains board consequences such as flips, replies, and capture lines; it never sees or reports engine scores, and it addresses the player as "you" and the other side as "the opponent". Text with a digit, an unknown placeholder, a coordinate outside the evidence, score talk, a side named by color, or a claim about corners, hints, passes, or winning without a matching cited fact is returned to the model for correction, at most twice. If the answer still fails, Nemotron starts once more from a fresh conversation. If that also fails, a quiet note says Nemotron could not give a reliable explanation, the board demonstration stays, and coaching can be retried; only service errors are shown as errors. Forced moves need no model call and offer no coaching request. Opening saved reviews and exploring continuations make no model calls.

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

Use one worker per database. Opponent identity includes the engine version, resource hashes, and search settings. Existing games cannot continue against a changed opponent. `GET /health` checks process response; it does not verify external model readiness.

## Checks and tools

From the root: `npm run test:web`, `npm run typecheck`, `npm run build`, and `npm run check:api-types`.

From `backend/`:

```sh
uv run pytest tests/test_rules.py tests/test_history.py tests/test_storage.py tests/test_edax.py tests/test_product_runtime.py
uv run ruff check src tests
uv run nemothello --help
uv run nemothello check-edax --output ../eval/results/edax-check.json
```

`verify-demo` plays a full game, then exercises the review, lesson, follow-up question, and branch APIs. It calls Token Factory and can incur charges. Browser hint display requires a separate UI check.

## Research tools

The CLI also contains policy calibration, cloud training, model evaluation, and adapter backup tools. Install their optional dependencies only when using them:

```sh
uv sync --extra dev --extra research
uv run pytest
```

Cloud research commands can incur charges. They use `PYTRIO_API_KEY` and optional `PYTRIO_BASE_MODEL` from the backend environment. Training and evaluation use the checkpoint paths and calibration reports specified through their CLI options. These tools do not configure the app's opponent.

`deploy/compose.yaml` runs the backend, the Next.js app, and Caddy on one VM; [deploy/README.md](deploy/README.md) walks through a Google Cloud setup. Model credentials belong on the backend, never in public frontend variables.
