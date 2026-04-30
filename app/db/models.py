# ORM models for ai_control_plane audit and run tables — Nicholas Hidalgo
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class AuditRecord(Base):
    __tablename__ = "ai_control_plane_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(String, index=True, nullable=False)
    requester_email_hash = Column(String, nullable=False)
    intake_text = Column(Text, nullable=True)
    policy_decision = Column(String, nullable=False)
    assigned_agent = Column(String, nullable=True)
    resolution = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    redacted = Column(Boolean, nullable=False, default=False)
    approved = Column(Boolean, nullable=False, default=False)
    summary = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class RunRecord(Base):
    __tablename__ = "ai_control_plane_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    phase = Column(String, nullable=False)
    status = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
