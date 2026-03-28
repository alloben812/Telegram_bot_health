"""SQLAlchemy ORM models.

Sensitive fields (Garmin password, WHOOP tokens) are stored encrypted
using Fernet symmetric encryption via security.py.
The raw plaintext values are NEVER persisted to disk.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional

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
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[Optional[str]] = mapped_column(String(64))

    garmin_email: Mapped[Optional[str]] = mapped_column(String(256))
    # Encrypted with Fernet — never stored as plaintext
    garmin_password_enc: Mapped[Optional[str]] = mapped_column(Text)

    # Encrypted JSON token — never stored as plaintext
    whoop_token_enc: Mapped[Optional[str]] = mapped_column(Text)

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
    whoop_recovery_score: Mapped[Optional[float]] = mapped_column(Float)
    whoop_hrv_ms: Mapped[Optional[float]] = mapped_column(Float)
    whoop_resting_hr: Mapped[Optional[float]] = mapped_column(Float)
    whoop_strain: Mapped[Optional[float]] = mapped_column(Float)
    whoop_avg_hr: Mapped[Optional[int]] = mapped_column(Integer)
    whoop_max_hr: Mapped[Optional[int]] = mapped_column(Integer)
    whoop_kilojoule: Mapped[Optional[float]] = mapped_column(Float)
    whoop_sleep_performance: Mapped[Optional[float]] = mapped_column(Float)
    whoop_sleep_duration_h: Mapped[Optional[float]] = mapped_column(Float)
    whoop_respiratory_rate: Mapped[Optional[float]] = mapped_column(Float)
    whoop_spo2: Mapped[Optional[float]] = mapped_column(Float)
    whoop_skin_temp: Mapped[Optional[float]] = mapped_column(Float)
    whoop_workout_count: Mapped[Optional[int]] = mapped_column(Integer)

    # Garmin — aggregated numeric metrics
    garmin_steps: Mapped[Optional[int]] = mapped_column(Integer)
    garmin_active_calories: Mapped[Optional[int]] = mapped_column(Integer)
    garmin_body_battery_end: Mapped[Optional[int]] = mapped_column(Integer)
    garmin_stress_avg: Mapped[Optional[int]] = mapped_column(Integer)
    garmin_training_readiness: Mapped[Optional[int]] = mapped_column(Integer)

    # Full raw API responses — encrypted at rest
    raw_garmin_enc: Mapped[Optional[str]] = mapped_column(Text)
    raw_whoop_enc: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class Activity(Base):
    """Individual workout/activity record."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    source: Mapped[str] = mapped_column(String(16))  # 'garmin' | 'whoop'
    external_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    sport: Mapped[str] = mapped_column(String(32), index=True)
    activity_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD

    duration_s: Mapped[Optional[float]] = mapped_column(Float)
    distance_m: Mapped[Optional[float]] = mapped_column(Float)
    calories: Mapped[Optional[int]] = mapped_column(Integer)
    avg_hr: Mapped[Optional[int]] = mapped_column(Integer)
    max_hr: Mapped[Optional[int]] = mapped_column(Integer)
    avg_pace_s_per_km: Mapped[Optional[float]] = mapped_column(Float)
    avg_power_w: Mapped[Optional[float]] = mapped_column(Float)
    avg_cadence: Mapped[Optional[float]] = mapped_column(Float)
    elevation_gain_m: Mapped[Optional[float]] = mapped_column(Float)

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
    recovery_score_at_gen: Mapped[Optional[float]] = mapped_column(Float)
    hrv_at_gen: Mapped[Optional[float]] = mapped_column(Float)
    readiness_at_gen: Mapped[Optional[int]] = mapped_column(Integer)
