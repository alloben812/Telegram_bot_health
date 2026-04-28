from __future__ import annotations

"""SQLAlchemy ORM models.

Sensitive fields (Garmin password, WHOOP tokens) are stored encrypted
using Fernet symmetric encryption via security.py.
The raw plaintext values are NEVER persisted to disk.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Telegram user with device credentials.

    garmin_password_enc  — Fernet-encrypted password ciphertext
    garmin_oauth_token_enc — Fernet-encrypted garth OAuth session (avoids 429)
    whoop_token_enc      — Fernet-encrypted JSON token ciphertext
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user ID
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[Optional[str]] = mapped_column(String(64))

    garmin_email: Mapped[Optional[str]] = mapped_column(String(256))
    # Encrypted with Fernet — never stored as plaintext
    garmin_password_enc: Mapped[Optional[str]] = mapped_column(Text)
    # Garmin OAuth session token (garth base64 dump) — encrypted.
    # Reusing this avoids re-login on every sync → no 429 rate limit.
    garmin_oauth_token_enc: Mapped[Optional[str]] = mapped_column(Text)

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
    whoop_strain: Mapped[Optional[float]] = mapped_column(Float)
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


class UserTrainingProfile(Base):
    """Athlete training profile: goals, HR zones, weekly limits.

    One row per user. Created on first /start onboarding.
    available_training_days — JSON list, e.g. '["mon","tue","thu","sat"]'
    """

    __tablename__ = "user_training_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)

    # Heart rate
    max_hr: Mapped[Optional[int]] = mapped_column(Integer)
    max_hr_source: Mapped[Optional[str]] = mapped_column(String(16))  # manual|garmin|whoop

    # Goal preset key, e.g. "run_10k_60"
    active_goal_key: Mapped[Optional[str]] = mapped_column(String(32))

    # Weekly schedule
    available_training_days: Mapped[Optional[str]] = mapped_column(Text)  # JSON list
    max_run_days_per_week: Mapped[Optional[int]] = mapped_column(Integer)
    strength_days_per_week: Mapped[Optional[int]] = mapped_column(Integer)

    # Onboarding completed flag
    onboarding_done: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DailyRecommendationRecord(Base):
    """Persisted structured daily recommendation from AI.

    Stores validated DailyRecommendation JSON fields separately
    for easy querying. Lists stored as JSON text.
    source_data_hash — hash of the athlete context used to generate,
    allows detecting when a re-generation is needed.
    """

    __tablename__ = "daily_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD

    readiness_score: Mapped[Optional[int]] = mapped_column(Integer)
    status_label: Mapped[Optional[str]] = mapped_column(String(128))
    main_recommendation: Mapped[Optional[str]] = mapped_column(Text)

    reasoning_json: Mapped[Optional[str]] = mapped_column(Text)   # JSON list
    avoid_json: Mapped[Optional[str]] = mapped_column(Text)        # JSON list
    control_json: Mapped[Optional[str]] = mapped_column(Text)      # JSON list
    data_gaps_json: Mapped[Optional[str]] = mapped_column(Text)    # JSON list

    confidence: Mapped[Optional[str]] = mapped_column(String(8))   # low|medium|high
    source_data_hash: Mapped[Optional[str]] = mapped_column(String(64))

    ai_provider: Mapped[Optional[str]] = mapped_column(String(32))
    ai_model: Mapped[Optional[str]] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlannedWorkoutRecord(Base):
    """Planned workout linked to a daily recommendation.

    blocks_json — JSON list of WorkoutBlock dicts.
    status: proposed|accepted|completed|skipped
    source: ai|coach|user
    """

    __tablename__ = "planned_workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    daily_recommendation_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD

    sport: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    intensity: Mapped[Optional[str]] = mapped_column(String(16))
    blocks_json: Mapped[Optional[str]] = mapped_column(Text)  # JSON list

    source: Mapped[str] = mapped_column(String(16), default="ai")
    status: Mapped[str] = mapped_column(String(16), default="proposed")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkoutCompletion(Base):
    """User feedback on a planned workout (Сделал / Не сделал + comment)."""

    __tablename__ = "workout_completions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    planned_workout_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    # done|skipped
    completion_status: Mapped[str] = mapped_column(String(16))
    comment: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConnectToken(Base):
    """One-time web connect token for device linking.

    Raw token is never stored — only SHA-256 hash.
    Tokens expire after 15 minutes and are single-use.
    """

    __tablename__ = "connect_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WhoopOAuthState(Base):
    """Pending WHOOP OAuth flow — maps random state token to user_id."""

    __tablename__ = "whoop_oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class DeviceRawEvent(Base):
    """Raw provider payload stored indefinitely for future re-analysis.

    payload_hash (SHA-256 of plaintext JSON) prevents duplicate inserts
    when the same sync runs multiple times.
    payload_encrypted — Fernet-encrypted JSON payload.
    """

    __tablename__ = "device_raw_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)

    provider: Mapped[str] = mapped_column(String(16))    # garmin|whoop
    data_type: Mapped[str] = mapped_column(String(32))   # cycle|recovery|sleep|workout|activity
    external_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    payload_encrypted: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)  # SHA-256 hex

    source_timestamp: Mapped[Optional[str]] = mapped_column(String(32))  # ISO from provider
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    parser_version: Mapped[str] = mapped_column(String(8), default="1")
