from __future__ import annotations

"""SQLAlchemy ORM models.

Sensitive fields (Garmin password, WHOOP tokens) are stored encrypted
using Fernet symmetric encryption via security.py.
The raw plaintext values are NEVER persisted to disk.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Telegram user with device credentials.

    garmin_password_enc  — Fernet-encrypted password ciphertext
    whoop_token_enc      — Fernet-encrypted JSON token ciphertext
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user ID
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(64))

    garmin_email: Mapped[str | None] = mapped_column(String(256))
    # Encrypted with Fernet — never stored as plaintext
    garmin_password_enc: Mapped[str | None] = mapped_column(Text)
    # Garmin OAuth session token (garth base64 dump) — encrypted.
    # Reusing this avoids re-login on every sync → no 429 rate limit.
    garmin_oauth_token_enc: Mapped[str | None] = mapped_column(Text)

    # Encrypted JSON token — never stored as plaintext
    whoop_token_enc: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DailySnapshot(Base):
    """Cached daily health snapshot (Garmin + WHOOP combined).

    Numeric metrics are stored in plain columns for easy querying.
    Raw API payloads (raw_garmin_enc, raw_whoop_enc) are Fernet-encrypted
    because they may contain PII (HR data, GPS, etc.).
    """

    __tablename__ = "daily_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD

    # WHOOP — aggregated numeric metrics (not sensitive enough to encrypt)
    whoop_recovery_score: Mapped[float | None] = mapped_column(Float)
    whoop_hrv_ms: Mapped[float | None] = mapped_column(Float)
    whoop_resting_hr: Mapped[float | None] = mapped_column(Float)
    whoop_strain: Mapped[float | None] = mapped_column(Float)
    whoop_sleep_performance: Mapped[float | None] = mapped_column(Float)
    whoop_sleep_duration_h: Mapped[float | None] = mapped_column(Float)

    # Garmin — aggregated numeric metrics
    garmin_steps: Mapped[int | None] = mapped_column(Integer)
    garmin_active_calories: Mapped[int | None] = mapped_column(Integer)
    garmin_body_battery_end: Mapped[int | None] = mapped_column(Integer)
    garmin_stress_avg: Mapped[int | None] = mapped_column(Integer)
    garmin_training_readiness: Mapped[int | None] = mapped_column(Integer)

    # Full raw API responses — encrypted at rest
    raw_garmin_enc: Mapped[str | None] = mapped_column(Text)
    raw_whoop_enc: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class Activity(Base):
    """Individual workout/activity record."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    source: Mapped[str] = mapped_column(String(16))  # 'garmin' | 'whoop'
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)

    sport: Mapped[str] = mapped_column(String(32), index=True)
    activity_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD

    duration_s: Mapped[float | None] = mapped_column(Float)
    distance_m: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[int | None] = mapped_column(Integer)
    avg_hr: Mapped[int | None] = mapped_column(Integer)
    max_hr: Mapped[int | None] = mapped_column(Integer)
    avg_pace_s_per_km: Mapped[float | None] = mapped_column(Float)
    avg_power_w: Mapped[float | None] = mapped_column(Float)
    avg_cadence: Mapped[float | None] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class TrainingPlan(Base):
    """AI-generated training plan."""

    __tablename__ = "training_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    sport: Mapped[str] = mapped_column(String(32))
    plan_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # The plan text is AI-generated and not sensitive — stored in plain text
    plan_text: Mapped[str] = mapped_column(Text)

    # Recovery/readiness values used when generating — stored plain for audit
    recovery_score_at_gen: Mapped[float | None] = mapped_column(Float)
    hrv_at_gen: Mapped[float | None] = mapped_column(Float)
    readiness_at_gen: Mapped[int | None] = mapped_column(Integer)
