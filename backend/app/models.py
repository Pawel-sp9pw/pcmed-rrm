import time
import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> int:
    return int(time.time())


def identifier() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Enrollment(Base):
    __tablename__ = "enrollments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[int] = mapped_column(Integer)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Gateway(Base):
    __tablename__ = "gateways"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("id", "tenant_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hostname: Mapped[str] = mapped_column(String(120))
    os_version: Mapped[str] = mapped_column(String(200))
    agent_version: Mapped[str] = mapped_column(String(50), default="")
    last_seen: Mapped[int] = mapped_column(Integer, default=now)
    gateway_id: Mapped[str | None] = mapped_column(ForeignKey("gateways.id"))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Definition(Base):
    __tablename__ = "definitions"
    __table_args__ = (UniqueConstraint("id", "tenant_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    spec: Mapped[dict] = mapped_column(JSON)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="draft")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        ForeignKeyConstraint(["device_id", "tenant_id"], ["devices.id", "devices.tenant_id"]),
        ForeignKeyConstraint(["definition_id", "tenant_id"], ["definitions.id", "definitions.tenant_id"]),
        Index("ix_jobs_dispatch", "device_id", "state", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    device_id: Mapped[str] = mapped_column(String(36))
    definition_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(20))
    spec: Mapped[dict] = mapped_column(JSON)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    created_at: Mapped[int] = mapped_column(Integer, default=now)
    started_at: Mapped[int | None] = mapped_column(Integer)
    finished_at: Mapped[int | None] = mapped_column(Integer)
    claim: Mapped[str | None] = mapped_column(String(36))
    deadline: Mapped[int | None] = mapped_column(Integer)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    output: Mapped[str | None] = mapped_column(Text)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_at: Mapped[int] = mapped_column(Integer, default=now, index=True)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(200))
