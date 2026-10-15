FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home app \
    && mkdir -p /app/runtime && chown app:app /app/runtime
USER app
EXPOSE 8000

# One worker owns the Edax processes, database, and task queue.
CMD ["uvicorn", "nemothello.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
