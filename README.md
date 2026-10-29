# Nemothello

Nemothello is an Othello app that helps players learn from their games. Play against Edax at three difficulty levels, with optional move hints and legal-move highlights.

After a game, review your own moves, compare them with engine recommendations, and explore possible continuations on the board. NVIDIA Nemotron provides explanations, answers follow-up questions, and summarizes the game using analysis from Edax and the rules engine. You can continue playing from a reviewed position.

The interface supports English and Chinese. Nemothello uses Next.js for the web app, FastAPI for the backend, Edax for play and analysis, and NVIDIA Nemotron through Nebius Token Factory for coaching.

## How Nemotron and Token Factory are used

The backend calls Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) or Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`) through Token Factory's OpenAI-compatible chat completions API. Edax analyzes each finished game without a model call; Nemotron turns that analysis into coaching.

- **Move lessons and follow-up questions** run as a tool-calling agent. Nemotron calls `play_line` to play out a line on the rules engine and `check_corner_threat` to test whether a move gives up a corner, then answers through `submit_answer`, citing the facts those tools returned.
- **Game summaries** take two calls: Nemotron drafts a short summary from the whole game's evidence with thinking on, then a second call audits the draft against that evidence. The lesson shows the played move and a board mechanism the rules engine verified, and the summary ends with one question to ask before moves in the next game.
- **Verification**: Nemotron writes numbers as placeholders that the backend fills from verified values. The backend rejects text that cites unknown facts, names coordinates outside the evidence, or mentions engine scores, and sends it back to the model for correction.

Token Factory let one API key serve both model sizes: switching between Super and Ultra is a change to `TOKEN_FACTORY_MODEL_ID`, with no GPU hosting. Saved lessons and summaries reopen without another call, and `MODEL_TASKS_PER_DAY` (default 300) and `MODEL_TASKS_PER_SESSION_PER_DAY` (default 30) cap daily model use.

## Run locally

Requirements: Node.js 20.9+, Python 3.11–3.13, [uv](https://docs.astral.sh/uv/), a C compiler, and `bsdtar` (built into macOS; `libarchive-tools` on Debian and Ubuntu).

Build Edax and download its evaluation weights into `deploy/edax/`:

```sh
git clone --depth 1 --branch v4.6 https://github.com/abulmo/edax-reversi.git deploy/edax/source
git -C deploy/edax/source apply ../../patches/edax-4.6-aligned-alloc.patch
mkdir -p deploy/edax/source/bin
# Apple Silicon
make -C deploy/edax/source/src build ARCH=armv8-a CC=clang OS=osx
cp deploy/edax/source/bin/mEdax-armv8-a deploy/edax/edax
# Linux x86-64: make ... ARCH=x86-64-v2 CC=gcc OS=linux, then copy bin/lEdax-x86-64-v2
curl -fsSL -o deploy/edax/eval.7z https://github.com/abulmo/edax-reversi/releases/download/v4.4/eval.7z
bsdtar -xf deploy/edax/eval.7z -C deploy/edax --strip-components 1 data/eval.dat
```

Install dependencies and start both services:

```sh
npm ci
(cd backend && uv sync --extra dev)
./start.command
```

The launcher creates `backend/.env` and `web/.env.local` from their examples, generates the shared service token, and opens http://127.0.0.1:3000. Games, hints, review navigation, and board demonstrations work without a model. To enable Nemotron coaching, set `TOKEN_FACTORY_API_KEY` and `TOKEN_FACTORY_MODEL_ID` in `backend/.env` and restart.

Checks: `npm run test:web`, `npm run typecheck`, and, from `backend/`, `uv run ruff check src tests` and `uv run pytest`. The full test suite also covers the research tools, so install them first with `uv sync --extra dev --extra research`.

## Deploy

`deploy/compose.yaml` runs the app on one Linux VM: Caddy serves HTTPS and forwards to Next.js, which forwards API calls to the single-worker backend. The backend image compiles Edax itself, and SQLite persists in a Docker volume.

```sh
cd deploy
cp .env.example .env                       # DOMAIN, ACME_EMAIL, BACKEND_SERVICE_TOKEN
cp ../backend/.env.example backend.env     # TOKEN_FACTORY_API_KEY, TOKEN_FACTORY_MODEL_ID
docker compose up -d --build
```

Point the domain's DNS at the VM and open ports 80 and 443. Model credentials stay on the backend.

## License

MIT. Edax is a separate GPL-3.0 project; the repository contains only a patch to it, and the deployment downloads its source at build time.
