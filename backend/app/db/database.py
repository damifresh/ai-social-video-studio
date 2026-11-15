from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from ..core.config import settings

engine = create_engine(f"sqlite:///{settings.db_path}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    """Create tables and apply additive SQLite migrations for existing databases."""
    from . import models  # noqa: F401  (register Engine A metadata)
    from ..clip import models as clip_models  # noqa: F401  (register Engine B metadata)

    Base.metadata.create_all(bind=engine)
    additions = {
        "projects": {
            "fps": "INTEGER DEFAULT 30",
            "burn_subs": "BOOLEAN DEFAULT 1",
            "subtitle_style": "TEXT DEFAULT '{}'",
            "music_volume": "FLOAT DEFAULT 0.10",
            "voice_speed": "INTEGER DEFAULT 0",
            "auto_mode": "BOOLEAN DEFAULT 0",
            "thumbnail": "TEXT DEFAULT ''",
        },
        "jobs": {
            "peak_memory_mb": "INTEGER DEFAULT 0",
            "started_at": "DATETIME",
            "finished_at": "DATETIME",
            "canceled": "BOOLEAN DEFAULT 0",
        },
    }
    with engine.begin() as conn:
        for table, cols in additions.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def recover_interrupted_jobs() -> int:
    """Mark jobs left running/queued by a previous process as interrupted (no data loss)."""
    with engine.begin() as conn:
        res = conn.execute(
            text(
                "UPDATE jobs SET status='interrupted', message='Interrupted by app restart; "
                "artifacts preserved. Re-run to continue.', finished_at=datetime('now') "
                "WHERE status IN ('running','queued')"
            )
        )
        return res.rowcount or 0
