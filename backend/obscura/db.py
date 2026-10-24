"""Database (SQLite by default; set OBSCURA_DB_URL=postgresql+psycopg://… for a multi-user server)."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, TypeDecorator,
                        UniqueConstraint, create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import DATA_DIR
from .storage import get_cipher


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Encrypted(TypeDecorator):
    """A string column encrypted with the master key (AES-GCM). For names and titles."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return get_cipher().enc(value) if value is not None else None

    def process_result_value(self, value, dialect):
        return get_cipher().dec(value) if value is not None else None


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(20), default="redactor")  # admin|supervisor|redactor|viewer
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Encrypted)
    number: Mapped[str] = mapped_column(Encrypted, default="")
    description: Mapped[str] = mapped_column(Encrypted, default="")
    status: Mapped[str] = mapped_column(String(30), default="open")  # open|in_review|completed|closed
    request_type: Mapped[str] = mapped_column(String(40), default="")  # FOIA, discovery, subpoena, records request…
    due_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    default_profile: Mapped[str] = mapped_column(String(40), default="standard")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    # case-wide dictionary: values confirmed anywhere in the case are searched in every file
    dictionary_blob: Mapped[str | None] = mapped_column(String(64), nullable=True)
    files: Mapped[list["File"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    members: Mapped[list["CaseMember"]] = relationship(cascade="all, delete-orphan")


class CaseMember(Base):
    __tablename__ = "case_members"
    __table_args__ = (UniqueConstraint("case_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), default="redactor")  # redactor|reviewer|viewer


class CaseNote(Base):
    __tablename__ = "case_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Encrypted)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class File(Base):
    __tablename__ = "files"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"), nullable=True)  # email attachments
    name: Mapped[str] = mapped_column(Encrypted)
    kind: Mapped[str] = mapped_column(String(20))  # pdf|image|video|audio|docx|pptx|xlsx|email|text
    ext: Mapped[str] = mapped_column(String(12))
    mime: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    original_blob: Mapped[str] = mapped_column(String(64))
    working_blob: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. email → PDF print
    extract_blob: Mapped[str | None] = mapped_column(String(64), nullable=True)  # page text + geometry
    detections_blob: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tracks_blob: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transcript_blob: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    info: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="uploaded")  # uploaded|analyzing|ready|in_review|approved|exported|error
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    analyzed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    case: Mapped[Case] = relationship(back_populates="files")
    exports: Mapped[list["Export"]] = relationship(cascade="all, delete-orphan")


class Export(Base):
    __tablename__ = "exports"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    blob: Mapped[str] = mapped_column(String(64))
    log_blob: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(Encrypted)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # analyze|export|ingest|watcher|bulk
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|error|cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class TermList(Base):
    """Custom search lists ("redact these names everywhere") and allow-lists ("never redact our firm name")."""
    __tablename__ = "term_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10), default="redact")  # redact|allow
    terms_blob: Mapped[str] = mapped_column(String(64))  # encrypted JSON list of term dicts
    entity: Mapped[str] = mapped_column(String(40), default="CUSTOM")
    exemption: Mapped[str] = mapped_column(String(40), default="")
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Template(Base):
    """Zone templates: fixed regions redacted on every matching page (forms, invoices, statements)."""
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    zones: Mapped[list] = mapped_column(JSON, default=list)  # [{pages:"all|first|last|N", x0,y0,x1,y1 (0..1), entity, exemption}]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Preset(Base):
    """Saved detection settings (profile, entities, visual classes, thresholds, lists)."""
    __tablename__ = "presets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ExemptionCode(Base):
    __tablename__ = "exemption_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")


class Watcher(Base):
    __tablename__ = "watchers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    input_dir: Mapped[str] = mapped_column(Text)
    output_dir: Mapped[str] = mapped_column(Text)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id"))
    preset_id: Mapped[int | None] = mapped_column(ForeignKey("presets.id"), nullable=True)
    export_settings: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(80), default="system")
    action: Mapped[str] = mapped_column(String(60), index=True)
    object_type: Mapped[str] = mapped_column(String(30), default="")
    object_id: Mapped[str] = mapped_column(String(40), default="")
    case_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


_engine = None
_Session = None


def init_db(url: str | None = None):
    global _engine, _Session
    url = url or os.environ.get("OBSCURA_DB_URL") or f"sqlite:///{DATA_DIR / 'obscura.db'}"
    if url.startswith("sqlite:///"):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite")
                            else {}, pool_pre_ping=True)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _pragmas(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA secure_delete=ON")  # deleted rows are zeroed on disk
            cur.close()
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session():
    if _Session is None:
        init_db()
    return _Session()


@contextmanager
def tx():
    s = session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db():
    s = session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
