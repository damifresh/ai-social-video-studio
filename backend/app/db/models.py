from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.utcnow()


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200), default="Untitled")
    topic: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    duration_min: Mapped[int] = mapped_column(Integer, default=1)
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="16:9")  # 9:16,16:9,1:1
    resolution: Mapped[str] = mapped_column(String(10), default="720p")
    style: Mapped[str] = mapped_column(String(50), default="cinematic")
    language: Mapped[str] = mapped_column(String(20), default="en")
    voice: Mapped[str] = mapped_column(String(80), default="say:Samantha")
    subtitle_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    music_track: Mapped[str] = mapped_column(String(200), default="none")
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft,generating,completed,failed
    fps: Mapped[int] = mapped_column(Integer, default=30)
    burn_subs: Mapped[bool] = mapped_column(Boolean, default=True)
    subtitle_style: Mapped[str] = mapped_column(Text, default="{}")
    music_volume: Mapped[float] = mapped_column(Float, default=0.10)
    voice_speed: Mapped[int] = mapped_column(Integer, default=0)
    auto_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    thumbnail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    jobs = relationship("Job", back_populates="project", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(30), default="full")  # full,script,scene,render,tts,subtitles,rerender
    stage: Mapped[str] = mapped_column(String(50), default="queued")
    status: Mapped[str] = mapped_column(String(30), default="queued")  # queued,running,succeeded,failed,interrupted,canceled
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100, real/computed
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    peak_memory_mb: Mapped[int] = mapped_column(Integer, default=0)
    canceled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    project = relationship("Project", back_populates="jobs")
