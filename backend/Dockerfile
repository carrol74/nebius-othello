FROM python:3.12-slim AS edax

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gcc git libarchive-tools libc6-dev make \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY deploy/patches/edax-4.6-aligned-alloc.patch ./
RUN git clone --depth 1 --branch v4.6 https://github.com/abulmo/edax-reversi.git edax \
    && git -C edax apply ../edax-4.6-aligned-alloc.patch \
    && mkdir edax/bin \
    && make -C edax/src build ARCH=x86-64-v2 CC=gcc OS=linux
# Evaluation weights are published only with the v4.4 release
RUN curl -fsSL -o eval.7z https://github.com/abulmo/edax-reversi/releases/download/v4.4/eval.7z \
    && bsdtar -xf eval.7z data/eval.dat

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-install-project
COPY backend/src ./src
RUN uv sync --locked --no-editable
COPY --from=edax /build/edax/bin/lEdax-x86-64-v2 /opt/edax/edax
COPY --from=edax /build/data/eval.dat /opt/edax/eval.dat
RUN useradd --uid 10001 --create-home app \
    && mkdir -p /app/runtime && chown app:app /app/runtime
USER app
EXPOSE 8000

# One worker owns the Edax processes, database, and task queue.
CMD ["uvicorn", "nemothello.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
