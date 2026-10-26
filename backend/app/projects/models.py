"""PostgreSQL schema for IT department data: projects, sprint runs, tasks, code artifacts, QA findings.

Debate logs and trading plans stay in SQLite (app/db.py) as described in the master plan.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = sa.JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(120), unique=True)
    description: Mapped[str] = mapped_column(sa.Text, default="")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    runs: Mapped[list[ItRun]] = relationship(back_populates="project", cascade="all, delete-orphan", passive_deletes=True)


class ItRun(Base):
    """One brief sent to the PM and everything the team produced for it (one 'sprint')."""

    __tablename__ = "it_runs"
    __table_args__ = (
        sa.CheckConstraint("status IN ('running', 'done', 'failed')", name="status"),
        sa.Index("ix_it_runs_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)  # = socket session_id
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id", ondelete="CASCADE"))
    prompt: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(16), default="running")
    summary: Mapped[str] = mapped_column(sa.Text, default="")
    assumptions: Mapped[list] = mapped_column(JSONType, default=list)
    analysis: Mapped[dict] = mapped_column(JSONType, default=dict)
    review: Mapped[dict] = mapped_column(JSONType, default=dict)
    review_verdict: Mapped[str | None] = mapped_column(sa.String(32))
    error: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="runs")
    tasks: Mapped[list[ItTask]] = relationship(back_populates="run", cascade="all, delete-orphan",
                                               passive_deletes=True, order_by="ItTask.id")
    artifacts: Mapped[list[ItArtifact]] = relationship(cascade="all, delete-orphan", passive_deletes=True,
                                                       order_by="ItArtifact.id")
    findings: Mapped[list[QaFinding]] = relationship(cascade="all, delete-orphan", passive_deletes=True,
                                                     order_by="QaFinding.id")


class ItTask(Base):
    __tablename__ = "it_tasks"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "code", name="uq_it_tasks_run_code"),
        sa.CheckConstraint("status IN ('todo', 'doing', 'done')", name="status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.ForeignKey("it_runs.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(sa.String(16))  # T1, T2 ...
    title: Mapped[str] = mapped_column(sa.Text)
    assignee: Mapped[str] = mapped_column(sa.String(16))
    depends_on: Mapped[list] = mapped_column(JSONType, default=list)
    done_when: Mapped[str] = mapped_column(sa.Text, default="")
    status: Mapped[str] = mapped_column(sa.String(8), default="todo")
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    run: Mapped[ItRun] = relationship(back_populates="tasks")


class ItArtifact(Base):
    """Code written by the DB / BE / FE agents."""

    __tablename__ = "it_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.ForeignKey("it_runs.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(sa.String(16))
    language: Mapped[str] = mapped_column(sa.String(16), default="text")
    content: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class QaFinding(Base):
    __tablename__ = "qa_findings"
    __table_args__ = (sa.Index("ix_qa_findings_severity", "severity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.ForeignKey("it_runs.id", ondelete="CASCADE"), index=True)
    severity: Mapped[str] = mapped_column(sa.String(16))
    agent: Mapped[str] = mapped_column(sa.String(16))
    issue: Mapped[str] = mapped_column(sa.Text)
