from __future__ import annotations

from datetime import datetime
from pathlib import Path


def log_date_folder(at: datetime | None = None) -> str:
    """Return the local calendar date used to group one logging session."""
    moment = datetime.now().astimezone() if at is None else at
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%Y%m%d")


def dated_log_directory(base: Path, at: datetime | None = None) -> Path:
    """Return ``base/YYYYMMDD`` using the local calendar date."""
    return Path(base) / log_date_folder(at)
