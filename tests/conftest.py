from __future__ import annotations

import pytest

from src.config import settings
from src.database import close_db, init_db


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    """Point SQLAlchemy and persisted artifacts at a fresh temporary directory."""
    close_db()
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'crewflow.db'}")
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(settings, "CHECKPOINT_DB", tmp_path / "checkpoints" / "crewflow.sqlite")
    init_db()
    yield tmp_path
    close_db()
