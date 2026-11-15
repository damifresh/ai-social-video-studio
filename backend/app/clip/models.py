"""Engine B (AI Auto-Clip Studio) database models.

Additive only: Engine A's ``projects``/``jobs`` tables are untouched, so an
upgrade or a rollback can never invalidate existing video-creator projects.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.utcnow()


class ClipProject(Base):
    __tablename__ = "clip_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200), default="Untitled clip project")
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft,analyzing,ready,rendering,completed,failed
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="9:16")
    preset: Mapped[str] = mapped_column(String(40), default="tiktok")
    language: Mapped[str] = mapped_column(String(20), default="en")
    settings_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    sources = relationship("ClipSource", back_populates="project", cascade="all, delete-orphan")
    candidates = relationship("ClipCandidate", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("ClipJob", back_populates="project", cascade="all, delete-orphan")


class ClipSource(Base):
    __tablename__ = "clip_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    clip_project_id: Mapped[str] = mapped_column(String, ForeignKey("clip_projects.id", ondelete="CASCADE"), index=True)
    original_name: Mapped[str] = mapped_column(String(300), default="")
    original_path: Mapped[str] = mapped_column(Text, default="")
    ext: Mapped[str] = mapped_column(String(10), default=".mp4")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    vcodec: Mapped[str] = mapped_column(String(40), default="")
    acodec: Mapped[str] = mapped_column(String(40), default="")
    audio_streams: Mapped[int] = mapped_column(Integer, default=0)
    sample_rate: Mapped[int] = mapped_column(Integer, default=0)
    channels: Mapped[int] = mapped_column(Integer, default=0)
    probe_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    project = relationship("ClipProject", back_populates="sources")


class ClipJob(Base):
    __tablename__ = "clip_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    clip_project_id: Mapped[str] = mapped_column(String, ForeignKey("clip_projects.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40), default="analyze")  # analyze,transcribe,highlights,render,batch_export
    stage: Mapped[str] = mapped_column(String(50), default="queued")
    status: Mapped[str] = mapped_column(String(30), default="queued")  # queued,running,succeeded,failed,interrupted,canceled
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    canceled: Mapped[bool] = mapped_column(Boolean, default=False)
    peak_memory_mb: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project = relationship("ClipProject", back_populates="jobs")


class ClipCandidate(Base):
    __tablename__ = "clip_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    clip_project_id: Mapped[str] = mapped_column(String, ForeignKey("clip_projects.id", ondelete="CASCADE"), index=True)
    start_sec: Mapped[float] = mapped_column(Float, default=0.0)
    end_sec: Mapped[float] = mapped_column(Float, default=0.0)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    transcript_text: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    hook: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(40), default="informative")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(20), default="new")  # new,stale,rendered
    # Per-clip editing settings (crop / captions / audio) live here so a clip can
    # be re-rendered without re-running analysis.
    edit_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    project = relationship("ClipProject", back_populates="candidates")
    renders = relationship("ClipRender", back_populates="candidate", cascade="all, delete-orphan")


class ClipRender(Base):
    __tablename__ = "clip_renders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    candidate_id: Mapped[str] = mapped_column(String, ForeignKey("clip_candidates.id", ondelete="CASCADE"), index=True)
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="9:16")
    preset: Mapped[str] = mapped_column(String(40), default="tiktok")
    output_path: Mapped[str] = mapped_column(Text, default="")
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    probe_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="done")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    candidate = relationship("ClipCandidate", back_populates="renders")
