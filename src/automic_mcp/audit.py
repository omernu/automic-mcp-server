"""Local, append-only audit log for execution attempts (stage 4).

One JSON object per line (JSON Lines), so it's easy to tail/grep and never
needs a full rewrite. Never committed to git - see .gitignore.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log_event(path: str, event: dict[str, Any]) -> None:
    # timezone.utc, not the datetime.UTC constant, since pyproject.toml
    # declares requires-python = ">=3.10" and that constant needs 3.11+.
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
