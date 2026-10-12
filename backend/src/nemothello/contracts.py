from pathlib import Path

from nemothello.data import write_json
from nemothello.main import app


def export_openapi(output: Path) -> None:
    write_json(output, app.openapi())
